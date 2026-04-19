"""Heuristics for how strongly the human chapter outline binds downstream agents."""

from __future__ import annotations

# Match UX hint on frontend; outline shorter than this is never FULL binding.
OUTLINE_MIN_CHARS_FOR_FULL_BINDING = 100


def outline_text_for_binding(chapter_outline: str, author_chapter_plan: str = "") -> str:
    raw = (chapter_outline or "").strip() or (author_chapter_plan or "").strip()
    return raw


def compute_outline_binding_mode(chapter_outline: str, author_chapter_plan: str = "") -> str:
    """
    FULL: enough text to treat human-specified beats as binding (with strict freedom).
    PARTIAL: some text but below threshold — AI may fill gaps; strict applies only to what is written.
    ABSENT: empty — full AI planning latitude for structure.
    """
    text = outline_text_for_binding(chapter_outline, author_chapter_plan)
    if not text:
        return "ABSENT"
    if len(text) >= OUTLINE_MIN_CHARS_FOR_FULL_BINDING:
        return "FULL"
    return "PARTIAL"
