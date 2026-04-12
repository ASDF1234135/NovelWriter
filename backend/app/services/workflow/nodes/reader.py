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
        return _normalize_reader_output(structured_output, from_llm=True).model_dump(mode="json")

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
    return _normalize_reader_output(output, from_llm=False).model_dump(mode="json")


def _build_reader_prompt(draft: str) -> str:
    return (
        "【評分標準與級距定義】\n"
        "請嚴格依據以下級距給出 literary_score。你的評分必須 100% 聚焦於「文學敘事體驗（如情緒張力、角色還原度、流暢度、展示而非告知）」。"
        "絕對不要去猜測系統的核准標準，你的唯一職責是給出最客觀的絕對分數。\n"
        "特別豁免規則：本內容為未經最終後處理的草稿。只要不導致語意斷裂或嚴重閱讀困難，請「完全忽略」輕微的排版與格式瑕疵"
        "（例如：多餘的空行、Markdown 標記殘留、標點符號半全形混用等），絕對不可因此扣分。\n"
        "* 【90–100】極致沉浸：細節極具畫面感，角色情緒飽滿且充滿說服力。對話與行動自然推動劇情，完美展現「展示而非告知（Show, Don't Tell）」，毫無閱讀阻力。\n"
        "* 【80–89】優秀引人：敘事流暢，戲劇張力充足，角色特徵鮮明。僅在極少數過渡段落或詞彙選擇上略顯平凡，但整體極具吸引力。\n"
        "* 【70–79】扎實平穩：故事推進順利，邏輯合理。但可能存在輕微的「套路感」，部分情緒鋪墊不夠深入，或場景描寫偏向平鋪直敘，缺乏亮點。\n"
        "* 【60–69】瑕疵明顯：核心劇情雖有傳達，但存在明顯缺陷，如：過度依賴「直接告知」而非動作展示、對話略顯生硬、或出現輕微的動作/心理描寫重複（如慣性回放同一種情緒）。\n"
        "* 【50–59】體驗中斷：角色行為出現違和感（OOC），情節推進過於生硬或淪為流水帳。缺乏足夠的細節支撐，讀者難以產生共鳴或沉浸。\n"
        "* 【40–49】嚴重出戲：敘事邏輯出現明顯斷層，存在嚴重的動作或對話重複（鬼打牆），情境轉換突兀，嚴重破壞閱讀體驗。\n"
        "* 【0–39】難以閱讀：語意不連貫、前言不對後語、角色徹底崩壞或產生嚴重幻覺，完全無法構成一篇正常的小說章節。\n"
        "分數偏低或未達核准時，critique 必須具體指出 1–3 個可改面向（例如節奏、對白、畫面、情緒轉折），避免只寫『尚可』『需加強』等空泛評語。\n"
        "分數高時 critique 保持簡短總結，不要要求重寫。\n"
        "**禁止**在 critique 中提及字數、篇幅、增刪字、擴寫／縮寫以符合某長度，或任何與章節長度目標有關的要求；"
        "長度與字數範圍由 draft_supervisor 處理，與你無關。只評文筆、節奏、情緒張力、對白、畫面與可讀性。\n\n"
        f"draft=\n{draft[:6000]}"
    )


# Only pad when the model returns a near-empty critique (specific feedback stays untouched).
_READER_VAGUE_CRITIQUE_MAX_LEN = 8
_READER_FALLBACK_HINT = (
    "請自查：節奏是否拖沓、對白是否功能化不足、畫面是否單薄、情緒轉折是否突兀。"
)


def _normalize_reader_output(output: ReaderOutput, *, from_llm: bool = False) -> ReaderOutput:
    is_approved = output.literary_score >= READER_PASS_SCORE
    critique = (output.critique or "").strip()
    if not is_approved:
        if from_llm and len(critique) < _READER_VAGUE_CRITIQUE_MAX_LEN:
            critique = f"{critique} {_READER_FALLBACK_HINT}".strip()
        critique = critique or _READER_FALLBACK_HINT
    else:
        critique = critique or "文筆穩定，節奏合格。"
    return ReaderOutput(
        is_approved=is_approved,
        literary_score=output.literary_score,
        suggestion_type=SuggestionType.NONE if is_approved else SuggestionType.MODIFY,
        critique=critique,
    )
