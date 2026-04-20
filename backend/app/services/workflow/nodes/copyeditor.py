from __future__ import annotations

import re

from app.core.config import get_settings
from app.services.llm import MockLLMClient
from app.services.workflow.continuity import chapter_content_tail_snippet
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.author import _ensure_chapter_heading
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile
from app.services.workflow.utils import latin_word_boundary_sub, looks_like_latin_word


def _completed_chapter_tail(
    story_repository,
    story_id: str,
    chapter_id: int,
    max_chars: int,
) -> str:
    row = story_repository.get_chapter(story_id, chapter_id)
    if not row:
        return ""
    if (str(row.get("status") or "").strip().lower()) != "completed":
        return ""
    raw = str(row.get("content") or "")
    return chapter_content_tail_snippet(raw, max_chars=max_chars) if raw else ""


def _load_read_only_prev_tails(
    state: dict,
    context: WorkflowContext,
    *,
    n1_max: int,
    n2_max: int,
) -> tuple[str, str]:
    story_id = state["story_id"]
    cid = int(state["chapter_id"])
    repo = context.story_repository
    tail_m2 = _completed_chapter_tail(repo, story_id, cid - 2, n2_max) if cid > 2 else ""
    tail_m1 = _completed_chapter_tail(repo, story_id, cid - 1, n1_max) if cid > 1 else ""
    return tail_m2, tail_m1


def _strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _collapse_leading_noise(text: str) -> str:
    """Drop common LLM preamble lines before the chapter heading."""
    t = text.strip()
    for _ in range(4):
        lowered = t[:80].lower()
        if lowered.startswith(("好的", "以下是", "這是", "here is", "below is", "certainly")):
            lines = t.splitlines()
            t = "\n".join(lines[1:]).strip() if len(lines) > 1 else t
            continue
        break
    return t


def _strip_stray_markdown(text: str) -> str:
    # Light cleanup: paired ** and stray list markers at line starts are reduced in prose pass.
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    out = re.sub(r"(?m)^[\*\-]\s+", "", out)
    return out


def _identity_tokens_to_block(state: dict) -> list[str]:
    allowed = {
        str(x).strip().casefold()
        for x in (state.get("allowed_identity_reveals_this_chapter") or [])
        if str(x).strip()
    }
    blocked: set[str] = set()
    for row in (state.get("forbidden_reveals") or []):
        if not isinstance(row, str) or not row.strip():
            continue
        if not any(
            k in row
            for k in (
                "身分",
                "身份",
                "真名",
                "真相",
                "其實是",
                "真正是",
                "identity",
                "true name",
                "actually",
            )
        ):
            continue
        for token in re.findall(r"「([^」]{1,30})」", row):
            t = token.strip()
            if t and t.casefold() not in allowed:
                blocked.add(t)
    return sorted(blocked, key=len, reverse=True)


def _redact_identity_terms(text: str, blocked_terms: list[str]) -> str:
    out = text
    for term in blocked_terms:
        if looks_like_latin_word(term):
            # Prefer Latin word-boundary redaction to avoid substring pollution (e.g. \"key\" in \"monkey\").
            out = latin_word_boundary_sub(term, "[REDACTED_IDENTITY]", out)
            # Light plural handling for single-word Latin tokens: redact \"key\" and \"keys\".
            if " " not in term and term and not term.lower().endswith("s"):
                out = latin_word_boundary_sub(f"{term}s", "[REDACTED_IDENTITY]", out)
            continue
        out = re.sub(re.escape(term), "[REDACTED_IDENTITY]", out, flags=re.IGNORECASE)
    return out


def _build_copyeditor_prompt(
    state: dict,
    *,
    tail_n2: str,
    tail_n1: str,
    chapter_draft: str,
) -> str:
    cid = int(state["chapter_id"])
    read_only_blocks: list[str] = []
    if cid > 2:
        read_only_blocks.append(
            f"## Read-only: end excerpt from chapter {cid - 2} (do not rewrite; do not copy into output)\n"
            f"{tail_n2 if tail_n2 else '(none)'}"
        )
    if cid > 1:
        read_only_blocks.append(
            f"## Read-only: end excerpt from chapter {cid - 1} (do not rewrite; do not copy into output)\n"
            f"{tail_n1 if tail_n1 else '(none)'}"
        )
    read_only_section = (
        "\n\n".join(read_only_blocks)
        if read_only_blocks
        else "## Read-only reference\n(Chapter 1 - no prior completed chapters.)"
    )
    return f"""You are a line/copy editor. You may polish sentences, cut redundancy and Markdown, tune punctuation and transitions - do not change facts or plot information.

{read_only_section}

## Editable: full draft text for chapter {cid} (output ONLY this chapter's polished full text)
{chapter_draft}

## Hard rules
1. Information conservation (highest): do not delete props, key dialogue, locations, or events; do not invent new plot; do not replace concrete referents with vague metaphor in ways that break mandatory on-page entities.
2. De-dupe: if this chapter's opening repeats the prior chapter's ending beat/sentiment, trim redundant lines here and stitch seamlessly (do not delete events).
3. Layout: strip decorative Markdown (bold stars, ornaments); avoid boilerplate recap closers.
4. Jargon pruning: if the draft uses stiff, gamified, or quote-stuffed proper nouns (e.g. "Hound Synergy Logic", "Strategic Buffer Node"), rewrite into natural narration.
5. Pruning principle: keep causal facts identical - unpack label-naming into observable action, sensation, spatial change, or system response.
6. Keep necessary names when they are core identifiers needed later; remove decorative subtitles, excess quotes, and term-stacking.
7. Example rewrite:
   - Before: He saw "Void Node: Collapse Zone".
   - After: He saw the weakest seam in the space; light bent unstably there.
8. Output: ONLY the polished chapter {cid} body - no preamble, no JSON, no commentary.
"""


def run_copyeditor(state: dict, context: WorkflowContext) -> dict[str, object]:
    settings = get_settings()
    cid = int(state["chapter_id"])
    draft = (state.get("best_draft_content") or state.get("current_draft") or "").strip()
    if not draft:
        return {"current_draft": "", "best_draft_content": ""}

    tail_m2, tail_m1 = _load_read_only_prev_tails(
        state,
        context,
        n1_max=int(settings.copyeditor_prev_tail_n1_max_chars),
        n2_max=int(settings.copyeditor_prev_tail_n2_max_chars),
    )

    if isinstance(context.llm_client, MockLLMClient):
        polished = _ensure_chapter_heading(cid, draft, context.output_language)
        polished = _redact_identity_terms(polished, _identity_tokens_to_block(state))
        return {"current_draft": polished, "best_draft_content": polished}

    profile = augment_profile_system_prompt(get_profile("copyeditor"), context.output_language)
    prompt = _build_copyeditor_prompt(state, tail_n2=tail_m2, tail_n1=tail_m1, chapter_draft=draft)
    result = context.llm_client.invoke_text(prompt, profile)
    body = _strip_markdown_fences(result.content)
    body = _collapse_leading_noise(body)
    body = _strip_stray_markdown(body)
    polished = _ensure_chapter_heading(cid, body, context.output_language)
    polished = _redact_identity_terms(polished, _identity_tokens_to_block(state))
    if not polished.strip():
        polished = _ensure_chapter_heading(cid, draft, context.output_language)
    return {"current_draft": polished, "best_draft_content": polished}
