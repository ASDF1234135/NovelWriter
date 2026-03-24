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

    directive_violations, directive_feedback = _detect_genesis_and_bstory_violations(payload)
    violations.extend(v for v in directive_violations if v not in violations)
    feedback.extend(directive_feedback)

    deterministic_violations, deterministic_feedback = _detect_continuity_violations(payload)
    violations.extend(violation for violation in deterministic_violations if violation not in violations)
    feedback.extend(deterministic_feedback)

    wc_violations, wc_feedback = _detect_word_count_violations(payload)
    violations.extend(violation for violation in wc_violations if violation not in violations)
    feedback.extend(wc_feedback)

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
        soft_warnings=[],
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
        "5c. Hard：Director 的 new_elements_to_introduce 每一項都必須在 proposed_new_nodes 有對應 role／canonical_name；"
        "b_story_directive 非空時 narrative_script 必須涵蓋其核心動詞或對象（不可空泛帶過）。否則 MISSING_DIRECTIVE。\n"
        "5d. Soft：idle beat 不足、超前解錨疑慮可記入 soft_warnings 但仍可 is_approved=true（若無其他 Hard）。\n"
        "6. Timeline Rollback：把 previous_chapter_summary 或 recent_chapter_context 中已完成的事件，重新包裝成本章新的 ground_truth_events，可視為 INCONSISTENCY。\n"
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
        f"\nPayload:\n{compact_json}"
    )


def _apply_deterministic_checks(output: PlanSupervisorOutput, payload) -> PlanSupervisorOutput:
    directive_violations, directive_feedback = _detect_genesis_and_bstory_violations(payload)
    continuity_violations, continuity_feedback = _detect_continuity_violations(payload)
    word_violations, word_feedback = _detect_word_count_violations(payload)
    violations = [*directive_violations, *continuity_violations, *word_violations]
    if not violations:
        return output

    merged_violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    for violation in violations:
        if violation not in merged_violations:
            merged_violations.append(violation)
    merged_feedback = output.feedback_to_agent.strip()
    for message in [*directive_feedback, *continuity_feedback, *word_feedback]:
        if message not in merged_feedback:
            merged_feedback = f"{merged_feedback} {message}".strip()

    return PlanSupervisorOutput(
        is_approved=False,
        violation_type=merged_violations or [ViolationType.NONE],
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=merged_feedback,
        anchor_achieved=False if violations else output.anchor_achieved,
        soft_warnings=list(output.soft_warnings or []),
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


def _detect_genesis_and_bstory_violations(payload) -> tuple[list[ViolationType], list[str]]:
    violations: list[ViolationType] = []
    feedback: list[str] = []
    script = payload.narrative_script or ""
    proposed = payload.proposed_new_nodes or []

    def _role_match(label: str) -> bool:
        label = (label or "").strip()
        if not label:
            return True
        for p in proposed:
            if not isinstance(p, dict):
                continue
            role = str(p.get("role") or "")
            cname = str(p.get("canonical_name") or "")
            if label in role or label in cname or role in label or cname in label:
                return True
        return False

    for label in payload.new_elements_to_introduce or []:
        if not _role_match(str(label)):
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append(f"導演要求的新元素「{label}」未在 proposed_new_nodes 具現化。")

    bdir = (payload.b_story_directive or "").strip()
    if bdir and not bdir.startswith("探索周遭環境與風土民情"):
        # 取前段作為核心片段，避免過長比對失敗
        core = bdir[:24].strip()
        if core and core not in script:
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("b_story_directive 的核心內容未編入 narrative_script。")

    return violations, feedback


def _detect_continuity_violations(payload) -> tuple[list[ViolationType], list[str]]:
    violations: list[ViolationType] = []
    feedback: list[str] = []

    if _looks_like_timeline_rollback(payload.previous_chapter_summary, payload.ground_truth_events):
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append("規劃看起來在重演上一章已完成的事件，缺少本章新的狀態變化。")

    return violations, feedback


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
