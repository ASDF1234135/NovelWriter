from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.domain.schema import PlanSupervisorOutput, SuggestionType, ViolationType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_plan_supervisor_payload, compact_plan_supervisor_payload_for_prompt
from app.services.workflow.profiles import get_profile

_PLAN_VIOLATION_FEEDBACK: list[tuple[ViolationType, str, tuple[str, ...]]] = [
    (
        ViolationType.WORD_COUNT_UNMATCH,
        "（系統補充）target_word_count 或節點／字數配比不符合硬性區間，請調整大綱、beats 或目標字數。",
        ("target_word_count", "字數", "beats"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "（系統補充）大綱與底層事件、時序或連續性不一致，請對照 ground_truth_events 與前情修正。",
        ("底層", "事件", "連續", "時序"),
    ),
    (
        ViolationType.ANCHOR_DIVERGENCE,
        "（系統補充）表層劇本未朝目標錨點收斂或偏離過遠，請調整 narrative_script。",
        ("錨點", "收斂"),
    ),
    (
        ViolationType.PHYSICAL_CONFLICT,
        "（系統補充）規劃與已知空間／因果狀態衝突，請對照 last_known_location 與事件鏈修正。",
        ("空間", "因果", "位置"),
    ),
    (
        ViolationType.POV_LEAK,
        "（系統補充）劇本將不應公開的資訊寫成讀者可見常識，請調整敘述層級。",
        ("POV", "公開"),
    ),
    (
        ViolationType.MISSING_DIRECTIVE,
        "（系統補充）未滿足導演硬性要求（如新元素未進 proposed_new_nodes），請補齊。",
        ("導演", "proposed_new", "元素"),
    ),
]


def _ensure_plan_supervisor_feedback_covers_violations(output: PlanSupervisorOutput) -> PlanSupervisorOutput:
    if output.is_approved:
        return output
    violations = [v for v in output.violation_type if v != ViolationType.NONE]
    if not violations:
        return output
    feedback = output.feedback_to_agent.strip()
    extras: list[str] = []
    for vtype, snippet, skip_tokens in _PLAN_VIOLATION_FEEDBACK:
        if vtype not in violations:
            continue
        if snippet in feedback:
            continue
        if any(tok in feedback for tok in skip_tokens):
            continue
        extras.append(snippet)
    if not extras:
        return output
    merged = f"{feedback} {' '.join(extras)}".strip()
    return output.model_copy(update={"feedback_to_agent": merged})


def run_plan_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_plan_supervisor_payload(state)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("plan_supervisor")
        prompt = _build_plan_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, PlanSupervisorOutput, profile)
        output = _apply_deterministic_checks(structured_output, payload)
        output = _ensure_plan_supervisor_feedback_covers_violations(output)
        data = output.model_dump(mode="json")
        if not data.get("soft_warnings"):
            data["soft_warnings"] = []
        return data, payload.model_dump(mode="json")

    violations: list[ViolationType] = []
    feedback: list[str] = []

    if not payload.ground_truth_events:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append("缺少底層真實事件。")

    if payload.target_anchor_chapter is not None and payload.target_anchor_chapter < payload.current_chapter_id:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append("目標錨點章數早於當前章節，錨點狀態可能已過期或工作流狀態不一致。")

    requires_anchor_completion = (
        payload.target_anchor_chapter is not None
        and payload.current_chapter_id >= payload.target_anchor_chapter
    )
    ct = str(payload.chapter_type or "PLOT_DRIVEN")
    dist = payload.distance_to_anchor
    strict_anchor = ct == "PLOT_DRIVEN" or (dist is not None and int(dist) <= 1)
    if (
        strict_anchor
        and requires_anchor_completion
        and payload.target_anchor_id
        and payload.target_anchor_id not in payload.narrative_script
    ):
        violations.append(ViolationType.ANCHOR_DIVERGENCE)
        feedback.append("表層劇本沒有明確朝目標錨點收斂。")
    elif payload.partial_convergence_allowed and payload.target_anchor_id and strict_anchor:
        feedback.append("目前仍在遠期錨點前期章節，允許 partial convergence，只要求方向一致與伏筆有效。")

    directive_violations, directive_feedback = _detect_directive_structural_violations(payload)
    violations.extend(v for v in directive_violations if v not in violations)
    feedback.extend(directive_feedback)

    wc_violations, wc_feedback = _detect_word_count_violations(payload)
    violations.extend(violation for violation in wc_violations if violation not in violations)
    feedback.extend(wc_feedback)
    gran_violations, gran_feedback = _detect_event_granularity_violations(payload)
    violations.extend(violation for violation in gran_violations if violation not in violations)
    feedback.extend(gran_feedback)

    output = PlanSupervisorOutput(
        is_approved=not violations,
        violation_type=violations or [ViolationType.NONE],
        suggestion_type=SuggestionType.MODIFY if violations else SuggestionType.NONE,
        feedback_to_agent=" ".join(feedback),
        anchor_achieved=bool(
            not violations
            and payload.target_anchor_id
            and requires_anchor_completion
            and strict_anchor
        ),
        soft_warnings=_timeline_rollback_soft_warnings(payload),
    )
    data = output.model_dump(mode="json")
    return data, payload.model_dump(mode="json")


def _build_plan_supervisor_prompt(payload) -> str:
    compact_json = compact_plan_supervisor_payload_for_prompt(payload)
    return (
        "請依下列規則審核 JSON payload：\n"
        "1. 若 target_anchor_chapter > current_chapter_id，允許 partial convergence。\n"
        "2. partial convergence 只要求本章方向正確、伏筆有效、不能有物理/時序/因果硬衝突。\n"
        "3. 遠期錨點尚未完成時，anchor_achieved=false 屬正常，不可單獨作為 blocking 理由。\n"
        "4. 只有 current_chapter_id >= target_anchor_chapter 時，才以明確達成錨點作為主要要求。\n"
        "5. 若 chapter_target - current_chapter >= 2，禁止因『尚未完成最終錨點』直接否決。\n"
        "5b. 若 chapter_type 為 CHARACTER_DRIVEN 或 WORLD_BUILDING，不得以『未推進主線錨點』單獨否決；"
        "但若超前揭曉錨點或因果硬衝突仍可否決。\n"
        "5c. Hard（語意由你判斷）：Director 的 new_elements_to_introduce 各項是否在 proposed_new_nodes 中有語意對應"
        "（別名、職能濃縮、組織 vs 個人均可）；不得以字面子字串強制對齊。後端僅檢查「有非空新元素要求時 proposed_new_nodes 不可為空」。\n"
        "5c-b. b_story_directive 若非預設空泛句且非空，由你判斷 narrative_script 是否實質編織該副線（動機、意象、事件或情緒線）；"
        "不可要求 narrative 複製導演原句。明顯缺席則 MISSING_DIRECTIVE，語意已涵蓋則放行。\n"
        "5d. Soft：idle beat 不足、超前解錨疑慮可記入 soft_warnings 但仍可 is_approved=true（若無其他 Hard）。\n"
        "6. Timeline Rollback：後端不以字元重疊率否決；若 previous_chapter_summary／recent_chapter_context 與本章 ground_truth_events"
        " 在敘事上重播已完成節拍、缺少新狀態變化，由你標 INCONSISTENCY。後端可能附加非阻斷的 soft_warning 作為提醒。\n"
        "7. Teleportation / Location Paradox（僅由你判斷，後端不做字串規則）："
        "比對 last_known_location 與 chapter_start_location，並閱讀 ground_truth_events、narrative_script。"
        "若兩處在空間上明顯銜接不上、又沒有合理移動／轉場／時間跳接的敘事支撐，應否決並標 PHYSICAL_CONFLICT（或 INCONSISTENCY）；"
        "若語意上為同一地點或別名、或過渡已寫清楚，則不可誤判。\n"
        "8. 若表層劇本把秘密行動、私下發現或 POV 不可能知道的資訊寫成公開常識，可使用 POV_LEAK。\n"
        "9. 若劇本涉及移動，必須能清楚判斷角色章末有效位置；若移動後位置無法落地，也可視為問題。\n"
        "10. 字數邊界：target_word_count 必須落在 chapter_word_min ~ chapter_word_max；否則標 WORD_COUNT_UNMATCH。\n"
        "11. 字數與節點：若 len(must_include_beats) * words_per_beat_floor 明顯大於 target_word_count，"
        "表示節點過多或字數過低，應標 WORD_COUNT_UNMATCH，並在 feedback 要求提高字數或刪減／合併 beats。\n"
        "12. 字數與劇本密度：若 narrative_script 明顯過短、空泛，但 target_word_count 極高，可標 WORD_COUNT_UNMATCH，"
        "要求降低字數或充實大綱；若 narrative_script 極度具體繁複但 target_word_count 過低，亦可標 WORD_COUNT_UNMATCH。\n"
        "（後端已做部分確定性檢查；你的判斷用於補足邊界案例。）\n"
        "13. 邊界與實體衝突檢查（Hard，僅在明顯衝突時否決）：請想像你是 Author。"
        "比對 Payload 中的 ending_boundary_rule、forbidden_next_scene_actions、chapter_end_location_hint 與 proposed_new_nodes（本章 planned_graph_nodes，"
        "含 mandatory: true 者）及 must_include_beats、narrative_script、ground_truth_events。"
        "若某必選實體依敘事只能在本章邊界『之後』才能自然出場、接觸或完成互動，導致 Author 無法在不越界的情況下寫入正文，"
        "應否決（is_approved=false）、suggestion_type=MODIFY，violation_type 宜用 INCONSISTENCY（大綱自相矛盾）或 PHYSICAL_CONFLICT（空間／時序上不可能在邊界前落地）。"
        "feedback_to_agent 須具體點名 node_id 或 beat、說明與哪條邊界衝突，並要求 Planner 將該實體延到下一章，或後移／放寬 ending_boundary_rule（二擇一或並陳）。"
        "若 Payload 未含 proposed_new_nodes 或無必選項，則勿臆造檢查項目。\n"
        "14. 當 ai_freedom_level=strict 且 outline_binding_mode=FULL 且 chapter_outline 有具體內容："
        "若 narrative_script／ground_truth_events **明顯背離**人類大綱已寫明的情節，標 Hard（INCONSISTENCY）；"
        "大綱極短或僅關鍵詞時改為 soft_warnings 提醒即可，避免過度否決。\n"
        f"\nPayload:\n{compact_json}"
    )


def _apply_deterministic_checks(output: PlanSupervisorOutput, payload) -> PlanSupervisorOutput:
    directive_violations, directive_feedback = _detect_directive_structural_violations(payload)
    word_violations, word_feedback = _detect_word_count_violations(payload)
    gran_violations, gran_feedback = _detect_event_granularity_violations(payload)
    violations = [*directive_violations, *word_violations, *gran_violations]

    soft = list(output.soft_warnings or [])
    for w in _timeline_rollback_soft_warnings(payload):
        if w and w not in soft:
            soft.append(w)

    if not violations:
        prev_soft = list(output.soft_warnings or [])
        if soft != prev_soft:
            return output.model_copy(update={"soft_warnings": soft})
        return output

    merged_violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    for violation in violations:
        if violation not in merged_violations:
            merged_violations.append(violation)
    merged_feedback = output.feedback_to_agent.strip()
    for message in [*directive_feedback, *word_feedback, *gran_feedback]:
        if message not in merged_feedback:
            merged_feedback = f"{merged_feedback} {message}".strip()

    return PlanSupervisorOutput(
        is_approved=False,
        violation_type=merged_violations or [ViolationType.NONE],
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=merged_feedback,
        anchor_achieved=False if violations else output.anchor_achieved,
        soft_warnings=soft,
    )


def _detect_word_count_violations(payload) -> tuple[list[ViolationType], list[str]]:
    violations: list[ViolationType] = []
    feedback: list[str] = []
    tw = int(payload.target_word_count)
    low = int(payload.chapter_word_min)
    high = int(payload.chapter_word_max)
    if tw < low:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"target_word_count={tw} 低於允許下限 {low}，請提高字數或調整大綱。")
    if tw > high:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"target_word_count={tw} 高於允許上限 {high}，請降低字數或簡化大綱。")
    beats = payload.must_include_beats or []
    per = int(payload.words_per_beat_floor)
    needed = len(beats) * per
    if beats and needed > tw:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(
            f"字數目標 {tw} 與 {len(beats)} 個必寫節點不匹配（粗略下限約 {needed}，每節點 {per}）；"
            "請提高 target_word_count 或刪減／合併 must_include_beats。"
        )
    script = (payload.narrative_script or "").strip()
    if len(script) < 80 and tw > 5000:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append("表層劇本過短但字數目標過高；請降低 target_word_count 或充實 narrative_script。")
    return violations, feedback


def _detect_event_granularity_violations(payload) -> tuple[list[ViolationType], list[str]]:
    events = getattr(payload, "ground_truth_events", None) or []
    if len(events) < 5:
        return [], []
    violations: list[ViolationType] = []
    feedback: list[str] = []
    micro_markers = ("閃避", "揮拳", "出手", "反擊", "翻滾", "轉身", "格擋", "刺擊", "扣下", "躍起")
    micro_count = 0
    for e in events:
        desc = str(getattr(e, "description", "") or "")
        if any(tok in desc for tok in micro_markers):
            micro_count += 1
    if micro_count >= 4:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append(
            "ground_truth_events 疑似過度微拆（連續動作事件過多）；請合併為宏觀事件，僅保留目標/場景/結果相位變化。"
        )
    return violations, feedback


_TIMELINE_ROLLBACK_SOFT_WARNING = (
    "提醒：底層事件與上一章摘要在字面上高度重疊，請確認是否為時序重演；若為承接敘述則可忽略。"
)


def _non_empty_new_element_items(items: list) -> bool:
    for x in items or []:
        if isinstance(x, dict):
            if str(x.get("need") or "").strip() or str(x.get("reason") or "").strip():
                return True
        elif str(x or "").strip():
            return True
    return False


def _detect_directive_structural_violations(payload) -> tuple[list[ViolationType], list[str]]:
    """Python-only structural check: if Director asked for new elements, Planner must propose at least one node."""
    violations: list[ViolationType] = []
    feedback: list[str] = []
    proposed = payload.proposed_new_nodes or []
    has_element_request = _non_empty_new_element_items(payload.new_elements_to_introduce)
    if has_element_request and len(proposed) == 0:
        violations.append(ViolationType.MISSING_DIRECTIVE)
        feedback.append("導演要求引入新元素，但 proposed_new_nodes 為空；請補齊節點。")
    for node in proposed:
        if not isinstance(node, dict):
            continue
        if str(node.get("node_type") or "") != "CHARACTER":
            continue
        prof = node.get("character_profile")
        if not isinstance(prof, dict):
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER 節點缺少 character_profile；請補齊與宏觀 cast 對齊的人設欄位。")
            continue
        if not str(prof.get("core_motivation") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER 的 character_profile.core_motivation 不可為空。")
        if not str(prof.get("fatal_flaw") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER 的 character_profile.fatal_flaw 不可為空。")
        if not str(prof.get("speech_style") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER 的 character_profile.speech_style 不可為空。")
    seeds = getattr(payload, "new_active_b_stories", None) or []
    for seed in seeds:
        if not isinstance(seed, dict):
            continue
        if str(seed.get("id") or "").strip() and not str(seed.get("resolution_condition") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append(f"副線 {seed.get('id')} 缺少 resolution_condition；請補齊可核銷條件。")
    cooldown = getattr(payload, "resolution_cooldown_constraint", None) or {}
    if cooldown.get("active"):
        narrative = str(getattr(payload, "narrative_script", "") or "")
        if any(k in narrative.lower() for k in ("mental duel", "mind link", "neural hack", "精神連結", "神經駭入", "腦機")):
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("RESOLUTION_COOLDOWN_HARD_VIOLATION: 本章規劃仍沿用被禁解法，請改為物理/環境/談判/暴力破局。")
    vibe = getattr(payload, "ending_vibe_cooldown_constraint", None) or {}
    if vibe.get("active"):
        boundary = str(getattr(payload, "ending_boundary_rule", "") or "")
        narrative = str(getattr(payload, "narrative_script", "") or "")
        if "安全屋" in boundary or "密室" in boundary or "總結對話" in narrative:
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("ENDING_VIBE_COOLDOWN_HARD_VIOLATION: 本章結尾節奏仍落入 SAFE_ROOM_EXPOSITION，請改為 ACTION_CLIFFHANGER。")
    return violations, feedback


def _timeline_rollback_soft_warnings(payload) -> list[str]:
    if _looks_like_timeline_rollback(payload.previous_chapter_summary, payload.ground_truth_events):
        return [_TIMELINE_ROLLBACK_SOFT_WARNING]
    return []


def _looks_like_timeline_rollback(previous_summary: str, ground_truth_events: list) -> bool:
    if not previous_summary:
        return False
    previous = _normalize(previous_summary)
    if len(previous) < 12:
        return False

    candidates = [_normalize(event.description) for event in ground_truth_events]
    for candidate in candidates:
        if len(candidate) < 12:
            continue
        if previous in candidate or candidate in previous:
            return True
        if SequenceMatcher(None, previous, candidate).ratio() >= 0.62:
            return True

    return False


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())
