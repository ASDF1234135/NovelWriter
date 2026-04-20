from __future__ import annotations

import re
from dataclasses import replace
from typing import Literal

from app.domain.schema import StoryOutputLanguage
from app.services.workflow.profiles import AgentPromptProfile

DEFAULT_OUTPUT_LANGUAGE: StoryOutputLanguage = "zh-Hant"
_OUTPUT_LANGUAGE_ALIASES: dict[str, StoryOutputLanguage] = {
    "en-us": "en",
    "en-gb": "en",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "zh-mo": "zh-Hant",
    "zh-hant": "zh-Hant",
}

OUTPUT_LANGUAGE_LABEL: dict[str, str] = {
    "en": "English",
    "zh-Hant": "Traditional Chinese",
    "zh-Hans": "Simplified Chinese",
}


def normalize_output_language(code: str | None) -> StoryOutputLanguage:
    s = (code or "").strip()
    if s in ("en", "zh-Hant", "zh-Hans"):
        return s  # type: ignore[return-value]
    alias = _OUTPUT_LANGUAGE_ALIASES.get(s.lower())
    if alias:
        return alias
    return DEFAULT_OUTPUT_LANGUAGE


def default_chapter_target_words(normalized_lang: str) -> int:
    """Default per-chapter target from settings: English vs non-English (e.g. CJK) budgets."""
    from app.core.config import get_settings

    s = get_settings()
    if normalized_lang == "en":
        return int(s.default_chapter_words_en)
    return int(s.default_chapter_words)


_CHAPTER_HEAD_ZH_RE = re.compile(r"^第\s*(\d+)\s*章\s*$")
_CHAPTER_HEAD_EN_RE = re.compile(r"^chapter\s*(\d+)\s*$", re.I)


def chapter_heading_line(chapter_id: int, lang: str | None) -> str:
    """First-line chapter title prefix stored in chapter body (matches story output_language)."""
    norm = normalize_output_language(lang)
    if norm == "en":
        return f"Chapter {chapter_id}"
    return f"第{chapter_id}章"


def chapter_context_line(chapter_id: int, body: str, lang: str | None) -> str:
    """One-line label for recent_chapter_context (supervisor/planner continuity)."""
    norm = normalize_output_language(lang)
    text = (body or "").strip()
    if norm == "en":
        return f"Chapter {chapter_id}: {text}"
    return f"第{chapter_id}章：{text}"


def milestone_arc_markers(prev_chapter_id: int, arc_chapter_id: int, lang: str | None) -> tuple[str, str]:
    """Bracket labels for cast arc history snippets in author/supervisor payloads."""
    norm = normalize_output_language(lang)
    if norm == "en":
        return (f"[Before Ch.{prev_chapter_id}]", f"[After Ch.{arc_chapter_id}]")
    return (f"[第{prev_chapter_id}章前]", f"[第{arc_chapter_id}章後]")


def heading_first_line_matches_chapter(first_line: str, chapter_id: int) -> bool:
    first = first_line.strip()
    m = _CHAPTER_HEAD_ZH_RE.match(first)
    if m and int(m.group(1)) == chapter_id:
        return True
    m = _CHAPTER_HEAD_EN_RE.match(first)
    if m and int(m.group(1)) == chapter_id:
        return True
    return False


def strip_leading_chapter_heading_line(text: str) -> str:
    """Remove first-line chapter heading (第N章 or Chapter N) if present."""
    cleaned = (text or "").strip()
    lines = cleaned.splitlines()
    if not lines:
        return cleaned
    first = lines[0].strip()
    if _CHAPTER_HEAD_ZH_RE.match(first) or _CHAPTER_HEAD_EN_RE.match(first):
        return "\n".join(lines[1:]).lstrip()
    return cleaned


def output_language_contract_block(lang: str) -> str:
    """English system suffix appended to every agent profile (single source of truth)."""
    norm = normalize_output_language(lang)
    label = OUTPUT_LANGUAGE_LABEL.get(norm, OUTPUT_LANGUAGE_LABEL[DEFAULT_OUTPUT_LANGUAGE])
    return (
        "\n\n---\n"
        "CRITICAL LANGUAGE REQUIREMENT: While this system prompt is in English, ALL generated "
        "natural-language content—including the actual story prose, character dialogues, chapter "
        "outlines, internal feedback/critiques, and summaries—MUST be written entirely in "
        f"{label}. Only JSON keys and ENUM values must remain in exact English as defined by the schema.\n"
        "Do NOT translate or transliterate user-provided proper nouns (character names, locations, "
        "special terms). Keep them in their original language as provided in the context."
    )


_OUTPUT_LANG_GENERATIVE_GUARD = "CRITICAL LANGUAGE REQUIREMENT:"
_OUTPUT_LANG_AUDIT_GUARD = "OUTPUT_LANGUAGE_AUDIT:"


def output_language_audit_contract_block(lang: str) -> str:
    """Suffix for agents that judge pre-written payloads (draft_supervisor, reader, plan_supervisor)."""
    norm = normalize_output_language(lang)
    label = OUTPUT_LANGUAGE_LABEL.get(norm, OUTPUT_LANGUAGE_LABEL[DEFAULT_OUTPUT_LANGUAGE])
    return (
        "\n\n---\n"
        f"{_OUTPUT_LANG_AUDIT_GUARD} The story's configured output language is {label}.\n"
        "You are auditing pre-written content (e.g. current_draft, narrative_script, or plan fields in the user message). "
        f"When that content's dominant natural language matches {label}, language requirements are satisfied.\n"
        "Do NOT reject, downgrade, or cite language non-compliance solely because these instructions are in English.\n"
        "Do NOT invoke the generative 'critical language requirement' rule against drafts that already match "
        f"{label}.\n"
        "JSON keys and ENUM values must remain exactly as defined by the schema (English where specified)."
    )


OutputLanguagePromptKind = Literal["generative", "audit"]


def augment_profile_system_prompt(
    profile: AgentPromptProfile,
    lang: str | None,
    *,
    prompt_kind: OutputLanguagePromptKind = "generative",
) -> AgentPromptProfile:
    if prompt_kind == "audit":
        suffix = output_language_audit_contract_block(lang or DEFAULT_OUTPUT_LANGUAGE)
        guard = _OUTPUT_LANG_AUDIT_GUARD
    else:
        suffix = output_language_contract_block(lang or DEFAULT_OUTPUT_LANGUAGE)
        guard = _OUTPUT_LANG_GENERATIVE_GUARD
    if guard in profile.system_prompt:
        return profile
    return replace(profile, system_prompt=f"{profile.system_prompt.rstrip()}{suffix}")
