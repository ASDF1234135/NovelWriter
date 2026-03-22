from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.domain.schema import PlanSupervisorOutput, SuggestionType, ViolationType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_plan_supervisor_payload
from app.services.workflow.profiles import get_profile


def run_plan_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_plan_supervisor_payload(state)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("plan_supervisor")
        prompt = _build_plan_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, PlanSupervisorOutput, profile)
        output = _apply_deterministic_checks(structured_output, payload)
        return output.model_dump(mode="json"), payload.model_dump(mode="json")

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
    if requires_anchor_completion and payload.target_anchor_id and payload.target_anchor_id not in payload.narrative_script:
        violations.append(ViolationType.ANCHOR_DIVERGENCE)
        feedback.append("表層劇本沒有明確朝目標錨點收斂。")
    elif payload.partial_convergence_allowed and payload.target_anchor_id:
        feedback.append("目前仍在遠期錨點前期章節，允許 partial convergence，只要求方向一致與伏筆有效。")

    deterministic_violations, deterministic_feedback = _detect_continuity_violations(payload)
    violations.extend(violation for violation in deterministic_violations if violation not in violations)
    feedback.extend(deterministic_feedback)

    output = PlanSupervisorOutput(
        is_approved=not violations,
        violation_type=violations or [ViolationType.NONE],
        suggestion_type=SuggestionType.MODIFY if violations else SuggestionType.NONE,
        feedback_to_agent=" ".join(feedback),
        anchor_achieved=bool(
            not violations
            and payload.target_anchor_id
            and requires_anchor_completion
        ),
    )
    return output.model_dump(mode="json"), payload.model_dump(mode="json")


def _build_plan_supervisor_prompt(payload) -> str:
    return (
        "請依下列規則審核 JSON payload：\n"
        "1. 若 target_anchor_chapter > current_chapter_id，允許 partial convergence。\n"
        "2. partial convergence 只要求本章方向正確、伏筆有效、不能有物理/時序/因果硬衝突。\n"
        "3. 遠期錨點尚未完成時，anchor_achieved=false 屬正常，不可單獨作為 blocking 理由。\n"
        "4. 只有 current_chapter_id >= target_anchor_chapter 時，才以明確達成錨點作為主要要求。\n"
        "5. 若 chapter_target - current_chapter >= 2，禁止因『尚未完成最終錨點』直接否決。\n"
        "6. Timeline Rollback：把 previous_chapter_summary 或 recent_chapter_context 中已完成的事件，重新包裝成本章新的 ground_truth_events，可視為 INCONSISTENCY。\n"
        "7. Teleportation / Location Paradox（僅由你判斷，後端不做字串規則）："
        "比對 last_known_location 與 chapter_start_location，並閱讀 ground_truth_events、narrative_script。"
        "若兩處在空間上明顯銜接不上、又沒有合理移動／轉場／時間跳接的敘事支撐，應否決並標 PHYSICAL_CONFLICT（或 INCONSISTENCY）；"
        "若語意上為同一地點或別名、或過渡已寫清楚，則不可誤判。\n"
        "8. 若表層劇本把秘密行動、私下發現或 POV 不可能知道的資訊寫成公開常識，可使用 POV_LEAK。\n"
        "9. 若劇本涉及移動，必須能清楚判斷角色章末有效位置；若移動後位置無法落地，也可視為問題。\n"
        f"\nPayload:\n{payload.model_dump_json(indent=2)}"
    )


def _apply_deterministic_checks(output: PlanSupervisorOutput, payload) -> PlanSupervisorOutput:
    violations, feedback = _detect_continuity_violations(payload)
    if not violations:
        return output

    merged_violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    for violation in violations:
        if violation not in merged_violations:
            merged_violations.append(violation)
    merged_feedback = output.feedback_to_agent.strip()
    for message in feedback:
        if message not in merged_feedback:
            merged_feedback = f"{merged_feedback} {message}".strip()

    return PlanSupervisorOutput(
        is_approved=False,
        violation_type=merged_violations or [ViolationType.NONE],
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=merged_feedback,
        anchor_achieved=False if violations else output.anchor_achieved,
    )


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
