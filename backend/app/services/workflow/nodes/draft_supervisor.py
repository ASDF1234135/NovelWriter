from __future__ import annotations

from app.domain.schema import DraftSupervisorOutput, LengthAdjustment, SuggestionType, ViolationType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_draft_supervisor_payload
from app.services.workflow.profiles import get_profile
from app.services.workflow.utils import normalized_text_length


def run_draft_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_draft_supervisor_payload(state)
    normalized_count = normalized_text_length(payload.current_draft)
    lower = int(payload.target_word_count * 0.65)
    upper = int(payload.target_word_count * 1.35)

    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("draft_supervisor")
        prompt = _build_draft_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, DraftSupervisorOutput, profile)
        output = _apply_word_count_gate(structured_output, normalized_count, lower, upper)
        output = _apply_boundary_gate(output, payload)
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
    return (
        "請只審核當前版本草稿，忽略歷史退稿。\n"
        "後端會用 deterministic 規則硬性檢查字數，允許範圍是目標字數的 65% 到 135%，你不需要自行估算字數。\n"
        "若草稿被判定為字數不足，請把 suggestion_type 維持在 MODIFY，並讓 length_adjustment 表示為 EXPAND；若字數過長則標成 COMPRESS。\n"
        "只有『明確硬衝突』才能使用 PHYSICAL_CONFLICT 或 INCONSISTENCY；"
        "正常小說化擴寫、感官描寫、氣氛鋪陳、象徵反覆不算違規。\n"
        "若 partial_convergence_allowed=true，遠期錨點尚未顯性達成不是退稿理由；"
        "只有當前草稿讓未來錨點不可達時，才可使用 ANCHOR_DIVERGENCE。\n"
        "若草稿把秘密行動、私下發現或 POV 不可能知道的資訊寫成公開事實，可使用 POV_LEAK。\n"
        "若草稿涉及移動，必須能判斷角色離開了哪裡、抵達或停留在哪裡；若章末位置模糊到無法建立穩定空間狀態，也可視為問題。\n"
        "若 chapter_end_location_hint、ending_boundary_rule 或 forbidden_next_scene_actions 已定義，"
        "你必須把它們視為本章硬邊界；一旦草稿寫到邊界之後的進屋、會面、轉場、抵達新據點或提前揭曉，都應視為 INCONSISTENCY。\n"
        "請輸出單一 JSON 物件。\n\n"
        f"{payload.model_dump_json(indent=2)}"
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
