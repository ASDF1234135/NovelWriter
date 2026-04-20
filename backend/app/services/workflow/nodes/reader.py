from __future__ import annotations

from app.domain.schema import ReaderOutput, SuggestionType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile
READER_PASS_SCORE = 60


def run_reader(state: dict, context: WorkflowContext) -> dict:
    draft = state["current_draft"]
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(get_profile("reader"), context.output_language, prompt_kind="audit")
        prompt = _build_reader_prompt(draft)
        structured_output, _ = context.llm_client.invoke_json(prompt, ReaderOutput, profile)
        return _normalize_reader_output(structured_output, from_llm=True).model_dump(mode="json")

    score = 70
    critique: list[str] = []

    # Word count is enforced by draft_supervisor; reader critique must never discuss length targets.

    has_atmosphere = (
        "夜色" in draft or "陰影" in draft or "night" in draft.casefold() or "shadow" in draft.casefold()
    )
    if not has_atmosphere:
        score -= 10
        critique.append("Setting/atmosphere could be more vivid.")

    has_mystery_hook = ("真相" in draft) or ("truth" in draft.casefold())
    if not has_mystery_hook:
        score -= 8
        critique.append("Mystery forward motion feels thin.")

    output = ReaderOutput(
        is_approved=score >= READER_PASS_SCORE,
        literary_score=max(0, min(100, score)),
        suggestion_type=SuggestionType.MODIFY if score < READER_PASS_SCORE else SuggestionType.NONE,
        critique=" ".join(critique) or "Prose is steady; pacing is acceptable.",
    )
    return _normalize_reader_output(output, from_llm=False).model_dump(mode="json")


def _build_reader_prompt(draft: str) -> str:
    return (
        "## Rubric (literary_score bands)\n"
        "Score literary_score strictly using the bands below. Focus 100% on narrative reading experience "
        "(emotional tension, character fidelity, flow, show-don't-tell). Do not try to guess approval heuristics—give an honest absolute score.\n"
        "Draft exemption: this is not final copy. Unless meaning breaks or reading is severely impaired, **fully ignore** minor formatting noise "
        "(extra blank lines, stray Markdown, mixed punctuation width, etc.)—never deduct for that alone.\n"
        "* [90–100] Immersive: vivid detail, convincing emotion, dialogue/action naturally advance plot, strong show-don't-tell, no friction.\n"
        "* [80–89] Strong: fluent, good tension, distinct characters; only minor flat spots in transitions or diction.\n"
        "* [70–79] Solid: plot moves and logic holds, but mild tropeyness, shallow emotional setup, or plain scene work.\n"
        "* [60–69] Flawed: plot is conveyed but with clear issues—too much telling, stiff dialogue, or light repetitive motion/emotion loops.\n"
        "* [50–59] Broken flow: OOC behavior, stiff or list-like progression, too little detail for immersion.\n"
        "* [40–49] Severely distracting: logic gaps, heavy repetitive dialogue/action, abrupt transitions.\n"
        "* [0–39] Unreadable: incoherent, contradictory, character collapse/hallucination-level failures.\n"
        "When score is low or not approved, critique must name 1–3 concrete levers (pacing, dialogue, imagery, emotional turns)—no vague 'needs work'.\n"
        "When score is high, keep critique short; do not demand rewrite.\n"
        "**Forbidden** in critique: word counts, length targets, expand/trim-to-fit, or any length policy—draft_supervisor owns length. "
        "You only judge prose, pacing, tension, dialogue, imagery, readability.\n\n"
        f"draft=\n{draft[:6000]}"
    )


# Only pad when the model returns a near-empty critique (specific feedback stays untouched).
_READER_VAGUE_CRITIQUE_MAX_LEN = 8
_READER_FALLBACK_HINT = (
    "Self-check: pacing drag, under-functional dialogue, thin imagery, or abrupt emotional turns."
)


def _normalize_reader_output(output: ReaderOutput, *, from_llm: bool = False) -> ReaderOutput:
    is_approved = output.literary_score >= READER_PASS_SCORE
    critique = (output.critique or "").strip()
    if not is_approved:
        if from_llm and len(critique) < _READER_VAGUE_CRITIQUE_MAX_LEN:
            critique = f"{critique} {_READER_FALLBACK_HINT}".strip()
        critique = critique or _READER_FALLBACK_HINT
    else:
        critique = critique or "Prose is steady; pacing is acceptable."
    return ReaderOutput(
        is_approved=is_approved,
        literary_score=output.literary_score,
        suggestion_type=SuggestionType.NONE if is_approved else SuggestionType.MODIFY,
        critique=critique,
    )
