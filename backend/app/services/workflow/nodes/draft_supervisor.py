from __future__ import annotations

import json
import re

from app.domain.schema import DraftSupervisorOutput, LengthAdjustment, SuggestionType, ViolationType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_draft_supervisor_payload
from app.services.workflow.profiles import get_profile
from app.services.workflow.utils import normalized_text_length

_DRAFT_VIOLATION_FEEDBACK: list[tuple[ViolationType, str, tuple[str, ...]]] = [
    (
        ViolationType.WORD_COUNT_UNMATCH,
        "（系統補充）字數與本章允許範圍不符，請擴寫或縮寫以落入區間。",
        ("正規化後字數", "不在允許範圍"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "（系統補充）草稿與表層劇本、事件鏈或本章硬邊界不一致，請逐項對照 narrative_script 與 ending_boundary_rule 修正。",
        ("硬邊界", "越界", "表層劇本", "草稿沒有充分貼合"),
    ),
    (
        ViolationType.PHYSICAL_CONFLICT,
        "（系統補充）與已知世界狀態、事件因果或空間銜接存在硬衝突，請對照 bible／圖譜上下文修正。",
        ("物理", "因果", "銜接"),
    ),
    (
        ViolationType.ANCHOR_DIVERGENCE,
        "（系統補充）本章敘事方向可能使目標錨點不可達或明顯偏離規劃，請收斂本章任務。",
        ("錨點", "偏離"),
    ),
    (
        ViolationType.POV_LEAK,
        "（系統補充）可能存在 POV 不可能得知的資訊被寫成公開事實，請調整敘述視角或資訊揭露方式。",
        ("POV", "洩漏", "私下"),
    ),
    (
        ViolationType.MISSING_DIRECTIVE,
        "（系統補充）未滿足導演或企劃硬性指令（如新元素未具現化），請補齊對應內容。",
        ("導演", "指令", "具現"),
    ),
    (
        ViolationType.MISSING_MANDATORY_ENTITY_MAPPING,
        "（系統補充）必選實體在稿中不可辨識或無法對齊規劃 node，請補寫可抽稱呼與 surface hints。",
        ("必選實體", "surface", "精確子字串"),
    ),
]


def _ensure_feedback_covers_violations(output: DraftSupervisorOutput) -> DraftSupervisorOutput:
    """Append deterministic lines when the model flagged violations but gave empty or vague feedback."""
    if output.is_approved:
        return output
    violations = [v for v in output.violation_type if v != ViolationType.NONE]
    if not violations:
        return output
    feedback = output.feedback_to_agent.strip()
    extras: list[str] = []
    for vtype, snippet, skip_tokens in _DRAFT_VIOLATION_FEEDBACK:
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


def _length_bounds(payload) -> tuple[int, int]:
    lo = int(payload.normalized_length_min or 0)
    hi = int(payload.normalized_length_max or 0)
    if lo <= 0 or hi <= 0:
        tw = int(payload.target_word_count or 0)
        lo = int(tw * 0.65)
        hi = int(tw * 1.35)
    return lo, hi


def _mandatory_hints_violation(state: dict, payload) -> str:
    """Require each mandatory entity to have non-empty validated surface_forms in author hints."""
    draft = payload.current_draft or ""
    mandatory = payload.mandatory_new_entities or []
    if not mandatory:
        return ""
    hints_raw = state.get("author_extraction_surface_hints") or []
    hints_by_id = {
        str(h.get("node_id", "")).strip(): h
        for h in hints_raw
        if isinstance(h, dict) and str(h.get("node_id", "")).strip()
    }
    missing: list[str] = []
    for ent in mandatory:
        nid = ent.node_id
        entry = hints_by_id.get(nid)
        if not entry:
            missing.append(nid)
            continue
        surfaces = [s for s in (entry.get("surface_forms") or []) if isinstance(s, str) and s and s in draft]
        if not surfaces:
            missing.append(nid)
    if not missing:
        return ""
    hints_note = json.dumps(hints_raw, ensure_ascii=False)[:1200]
    return (
        "必選實體未定稿可驗證的表面稱呼（精確子字串）："
        + ", ".join(missing)
        + "。請在正文中寫入可摘錄稱呼，並確保 Author 抽取提示含出現在正文中的精確子字串。"
        + f" 當前 author_extraction_surface_hints（摘要）：{hints_note}"
    )


def run_draft_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_draft_supervisor_payload(state)
    normalized_count = normalized_text_length(payload.current_draft)
    lower, upper = _length_bounds(payload)

    hint_fail = _mandatory_hints_violation(state, payload)
    if hint_fail:
        out = DraftSupervisorOutput(
            is_approved=False,
            violation_type=[ViolationType.MISSING_MANDATORY_ENTITY_MAPPING],
            suggestion_type=SuggestionType.REWRITE,
            feedback_to_agent=hint_fail,
            length_adjustment=LengthAdjustment.NONE,
        )
        return out.model_dump(mode="json"), payload.model_dump(mode="json")

    jargon_fail = _jargon_pruning_violation(payload)
    if jargon_fail:
        out = DraftSupervisorOutput(
            is_approved=False,
            violation_type=[ViolationType.INCONSISTENCY],
            suggestion_type=SuggestionType.REWRITE,
            feedback_to_agent=jargon_fail,
            length_adjustment=LengthAdjustment.NONE,
        )
        return out.model_dump(mode="json"), payload.model_dump(mode="json")

    identity_fail = _identity_reveal_violation(state, payload)
    if identity_fail:
        out = DraftSupervisorOutput(
            is_approved=False,
            violation_type=[ViolationType.POV_LEAK],
            suggestion_type=SuggestionType.REWRITE,
            feedback_to_agent=identity_fail,
            length_adjustment=LengthAdjustment.NONE,
        )
        return out.model_dump(mode="json"), payload.model_dump(mode="json")

    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("draft_supervisor")
        prompt = _build_draft_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, DraftSupervisorOutput, profile)
        output = _apply_word_count_gate(structured_output, normalized_count, lower, upper)
        output = _apply_boundary_gate(output, payload)
        output = _ensure_feedback_covers_violations(output)
        return output.model_dump(mode="json"), payload.model_dump(mode="json")

    violations: list[ViolationType] = []
    feedback: list[str] = []
    if normalized_count < lower or normalized_count > upper:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"正規化後字數 {normalized_count} 不在允許範圍 {lower}-{upper}。")

    if payload.narrative_script and payload.narrative_script[:10] not in payload.current_draft:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append("草稿沒有充分貼合表層劇本內容。")

    boundary_feedback = _detect_boundary_violation(payload)
    if boundary_feedback:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append(boundary_feedback)

    output = DraftSupervisorOutput(
        is_approved=not violations,
        violation_type=violations or [ViolationType.NONE],
        suggestion_type=SuggestionType.MODIFY if violations else SuggestionType.NONE,
        feedback_to_agent=" ".join(feedback),
        length_adjustment=_resolve_length_adjustment(normalized_count, lower, upper),
    )
    return output.model_dump(mode="json"), payload.model_dump(mode="json")


def _apply_word_count_gate(
    output: DraftSupervisorOutput,
    normalized_count: int,
    lower: int,
    upper: int,
) -> DraftSupervisorOutput:
    if lower <= normalized_count <= upper:
        return output.model_copy(update={"length_adjustment": LengthAdjustment.NONE})

    violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    if ViolationType.WORD_COUNT_UNMATCH not in violations:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
    feedback = output.feedback_to_agent.strip()
    message = f"正規化後字數 {normalized_count} 不在允許範圍 {lower}-{upper}。"
    if message not in feedback:
        feedback = f"{feedback} {message}".strip()

    return DraftSupervisorOutput(
        is_approved=False,
        violation_type=violations,
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=feedback,
        length_adjustment=_resolve_length_adjustment(normalized_count, lower, upper),
    )


def _build_draft_supervisor_prompt(payload) -> str:
    lo, hi = _length_bounds(payload)
    return (
        "請只審核當前版本草稿，忽略歷史退稿。\n"
        f"後端會用 deterministic 規則硬性檢查字數，允許範圍為 normalized_length {lo}～{hi}（來自 state，與 Author 一致）。\n"
        "若草稿被判定為字數不足，請把 suggestion_type 維持在 MODIFY，並讓 length_adjustment 表示為 EXPAND；若字數過長則標成 COMPRESS。\n"
        "只有『明確硬衝突』才能使用 PHYSICAL_CONFLICT 或 INCONSISTENCY；"
        "正常小說化擴寫、感官描寫、氣氛鋪陳、象徵反覆不算違規；"
        "符合 tone 的生活細節、心理活動、微小互動（喝水、天氣等）不得判為矛盾。\n"
        "必選實體是否出場已由後端依 author_extraction_surface_hints（精確子字串）決定性檢查；"
        "請勿再為 MISSING_MANDATORY_ENTITY_MAPPING 做判斷。\n"
        "若 partial_convergence_allowed=true，遠期錨點尚未顯性達成不是退稿理由；"
        "只有當前草稿讓未來錨點不可達時，才可使用 ANCHOR_DIVERGENCE。\n"
        "若草稿把秘密行動、私下發現或 POV 不可能知道的資訊寫成公開事實，可使用 POV_LEAK。\n"
        "若草稿涉及移動，必須能判斷角色離開了哪裡、抵達或停留在哪裡；若章末位置模糊到無法建立穩定空間狀態，也可視為問題。\n"
        "若草稿出現過量生硬術語、遊戲化專名或『引號+標籤化命名』，而且可改以自然感官敘述呈現，應視為 INCONSISTENCY 並要求重寫。\n"
        "若 chapter_end_location_hint、ending_boundary_rule 或 forbidden_next_scene_actions 已定義，"
        "你必須把它們視為本章硬邊界；一旦草稿寫到邊界之後的進屋、會面、轉場、抵達新據點或提前揭曉，都應視為 INCONSISTENCY。\n"
        "請輸出單一 JSON 物件。\n\n"
        f"{payload.model_dump_json(indent=2)}"
    )


def _jargon_pruning_violation(payload) -> str:
    draft = (payload.current_draft or "").strip()
    if not draft:
        return ""
    quoted_terms = re.findall(r"「([^」]{2,30})」", draft)
    suspicious_quoted = [
        t
        for t in quoted_terms
        if ("：" in t)
        or any(k in t for k in ("節點", "邏輯", "協同", "模組", "矩陣", "協議", "模式", "演算", "緩衝"))
    ]
    jargon_tokens = ("節點", "協同邏輯", "緩衝節點", "戰術模組", "策略模組", "演算", "協議棧")
    jargon_hits = sum(draft.count(tok) for tok in jargon_tokens)
    if len(suspicious_quoted) < 2 and jargon_hits < 3:
        return ""
    samples = "、".join(suspicious_quoted[:3]) if suspicious_quoted else "（術語密度偏高）"
    return (
        "草稿存在免洗專有名詞/標籤化命名過量，閱讀負擔過高。"
        f"偵測樣本：{samples}。"
        "請改寫為自然敘述：保留事件事實與因果，但把做作術語拆成可觀察的動作、感官與結果。"
    )


def _apply_boundary_gate(output: DraftSupervisorOutput, payload) -> DraftSupervisorOutput:
    boundary_feedback = _detect_boundary_violation(payload)
    if not boundary_feedback:
        return output

    violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    if ViolationType.INCONSISTENCY not in violations:
        violations.append(ViolationType.INCONSISTENCY)
    feedback = output.feedback_to_agent.strip()
    if boundary_feedback not in feedback:
        feedback = f"{feedback} {boundary_feedback}".strip()

    return DraftSupervisorOutput(
        is_approved=False,
        violation_type=violations,
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.REWRITE,
        feedback_to_agent=feedback,
        length_adjustment=output.length_adjustment,
    )


def _detect_boundary_violation(payload) -> str:
    draft = payload.current_draft
    lowered_draft = draft.casefold()
    matched_actions: list[str] = []
    for action in payload.forbidden_next_scene_actions:
        for cue in _extract_boundary_cues(action):
            if cue.casefold() in lowered_draft:
                matched_actions.append(action)
                break

    if not matched_actions:
        return ""

    action_list = "；".join(matched_actions[:3])
    if payload.ending_boundary_rule:
        return (
            f"草稿已超出本章硬邊界：{payload.ending_boundary_rule}。"
            f"目前觸發的越界動作包括：{action_list}。"
            "請將結尾收束在指定章末位置之前，不可把下一場景提前寫入本章。"
        )
    return f"草稿已提前寫入下一場景或越界動作：{action_list}。請將結尾截斷在本章規劃終點。"


def _extract_boundary_cues(action: str) -> list[str]:
    raw_parts = [part.strip() for part in action.replace("，", " ").replace("、", " ").replace("。", " ").split() if part.strip()]
    cues: list[str] = []
    for part in raw_parts:
        normalized = part
        for prefix in ("不要", "不可", "不得", "避免", "本章", "提前"):
            normalized = normalized.removeprefix(prefix)
        normalized = normalized.strip()
        if len(normalized) >= 3:
            cues.append(normalized)
    return cues


def _resolve_length_adjustment(normalized_count: int, lower: int, upper: int) -> LengthAdjustment:
    if normalized_count < lower:
        return LengthAdjustment.EXPAND
    if normalized_count > upper:
        return LengthAdjustment.COMPRESS
    return LengthAdjustment.NONE


def _identity_reveal_violation(state: dict, payload) -> str:
    draft = str(payload.current_draft or "")
    if not draft.strip():
        return ""
    allowed = {
        str(x).strip().casefold()
        for x in (state.get("allowed_identity_reveals_this_chapter") or [])
        if str(x).strip()
    }
    violations: list[str] = []
    for rule in (state.get("forbidden_reveals") or []):
        if not isinstance(rule, str) or not rule.strip():
            continue
        if not _looks_like_identity_rule(rule):
            continue
        for token in _extract_identity_tokens(rule):
            if token.casefold() in allowed:
                continue
            if re.search(re.escape(token), draft, flags=re.IGNORECASE):
                violations.append(token)
    if not violations:
        return ""
    terms = "、".join(sorted(set(violations))[:5])
    return (
        "檢測到草稿出現本章尚未允許揭露的身分資訊："
        f"{terms}。請改寫為讀者可見層級，不可直接揭露真身分或對應關係。"
    )


def _looks_like_identity_rule(text: str) -> bool:
    markers = ("身分", "身份", "真名", "真相", "其實是", "真正是", "revea")
    return any(m in text for m in markers)


def _extract_identity_tokens(text: str) -> list[str]:
    candidates: set[str] = set()
    for pat in (r"「([^」]{1,30})」", r"'([^']{1,30})'", r"\"([^\"]{1,30})\""):
        for m in re.findall(pat, text):
            t = m.strip()
            if t:
                candidates.add(t)
    for pat in (r"(?:其實是|真正是|就是)([A-Za-z\u4e00-\u9fff]{2,20})",):
        for m in re.findall(pat, text):
            t = m.strip()
            if t:
                candidates.add(t)
    return sorted(candidates)
