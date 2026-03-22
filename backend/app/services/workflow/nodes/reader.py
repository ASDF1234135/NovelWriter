from __future__ import annotations

from app.domain.schema import ReaderOutput, SuggestionType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile
READER_PASS_SCORE = 60


def run_reader(state: dict, context: WorkflowContext) -> dict:
    draft = state["current_draft"]
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("reader")
        prompt = _build_reader_prompt(draft)
        structured_output, _ = context.llm_client.invoke_json(prompt, ReaderOutput, profile)
        return _normalize_reader_output(structured_output).model_dump(mode="json")

    score = 70
    critique: list[str] = []

    # 字數由 draft_supervisor 審核；reader 的 critique 不得涉及篇幅／字數，避免污染 reader_feedback。

    if "夜色" not in draft and "陰影" not in draft:
        score -= 10
        critique.append("環境描寫可再鮮明。")

    if "真相" not in draft:
        score -= 8
        critique.append("懸念推進稍弱。")

    output = ReaderOutput(
        is_approved=score >= READER_PASS_SCORE,
        literary_score=max(0, min(100, score)),
        suggestion_type=SuggestionType.MODIFY if score < READER_PASS_SCORE else SuggestionType.NONE,
        critique=" ".join(critique) or "文筆穩定，節奏合格。",
    )
    return _normalize_reader_output(output).model_dump(mode="json")


def _build_reader_prompt(draft: str) -> str:
    return (
        "你是讀者體驗評審，只負責給出文學層分數與評論。\n"
        "literary_score 必須是 0–100 的整數，100 為滿分；請依文筆、節奏、情緒張力、對白、畫面與可讀性 **客觀** 評分，"
        "不要猜測或迎合任何通過線／及格分，你也未被告知此類數值。\n"
        "是否核准與後續建議類型由系統依內部規則從 literary_score 換算；"
        "若模型仍須填 is_approved、suggestion_type，可與你的直覺一致即可，實際以系統覆寫結果為準。\n"
        "分數偏低時請給 1–3 句具體修改建議；分數高時 critique 保持簡短總結，不要要求重寫。\n"
        "**禁止**在 critique 中提及字數、篇幅、增刪字、擴寫／縮寫以符合某長度，或任何與章節長度目標有關的要求；"
        "長度與字數範圍由 draft_supervisor 處理，與你無關。只評文筆、節奏、情緒張力、對白、畫面與可讀性。\n\n"
        f"draft=\n{draft[:6000]}"
    )


def _normalize_reader_output(output: ReaderOutput) -> ReaderOutput:
    is_approved = output.literary_score >= READER_PASS_SCORE
    return ReaderOutput(
        is_approved=is_approved,
        literary_score=output.literary_score,
        suggestion_type=SuggestionType.NONE if is_approved else SuggestionType.MODIFY,
        critique=output.critique if not is_approved else (output.critique or "文筆穩定，節奏合格。"),
    )
