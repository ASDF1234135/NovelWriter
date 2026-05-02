"""Single markdown bible field `general_world_lore` plus legacy-key synthesis."""

from __future__ import annotations

from typing import Any

from app.services.workflow.bible_writing_notes import NAMING_DISCIPLINE_WRITING_NOTES


def _as_lines(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, str):
        return [line.strip() for line in value.replace("\r\n", "\n").split("\n") if line.strip()]
    text = str(value).strip()
    return [text] if text else []


def _append_section(parts: list[str], title: str, body_lines: list[str]) -> None:
    if not body_lines:
        return
    parts.append(title)
    parts.append("")
    for line in body_lines:
        parts.append(line if line.startswith("- ") else f"- {line}")
    parts.append("")


def synthesize_general_world_lore_from_legacy(bible: dict[str, Any]) -> str:
    """Build markdown from legacy top-level bible keys (when general_world_lore absent)."""
    b = bible or {}
    parts: list[str] = []

    genre = str(b.get("story_genre") or b.get("genre") or "").strip()
    if genre:
        parts.append("## Genre")
        parts.append("")
        parts.append(genre)
        parts.append("")

    tone = str(b.get("tone") or "").strip()
    if tone:
        parts.append("## Tone")
        parts.append("")
        parts.append(tone)
        parts.append("")

    themes: list[str] = []
    if b.get("theme"):
        themes.extend(_as_lines(b.get("theme")))
    if b.get("themes"):
        themes.extend(_as_lines(b.get("themes")))
    if themes:
        _append_section(parts, "## Themes", list(dict.fromkeys(themes)))

    np = str(b.get("narrative_pov") or "").strip()
    if np:
        parts.append("## Narrative POV")
        parts.append("")
        parts.append(np)
        parts.append("")

    ws = str(b.get("writing_style") or "").strip()
    if ws:
        parts.append("## Writing style")
        parts.append("")
        parts.append(ws)
        parts.append("")

    wr = _as_lines(b.get("world_rules"))
    if wr:
        _append_section(parts, "## World rules", wr)

    fac = _as_lines(b.get("factions"))
    if fac:
        _append_section(parts, "## Factions", fac)

    wn = _as_lines(b.get("writing_note"))
    if wn:
        _append_section(parts, "## Writing notes", wn)

    return "\n".join(parts).strip()


def _with_naming_discipline(lore: str) -> str:
    base = (lore or "").strip()
    blocks = [base] if base else []
    for rule in NAMING_DISCIPLINE_WRITING_NOTES:
        if rule and rule not in base:
            blocks.append(rule)
    if not blocks:
        return ""
    return "\n\n".join(blocks).strip()


def effective_general_world_lore(bible: dict[str, Any] | None) -> str:
    """
    Resolved lore for prompts and workflow state.
    Prefer bible.general_world_lore; otherwise synthesize legacy keys.
    Appends default naming-discipline lines when missing (parity with former normalize_writing_note).
    """
    b = bible or {}
    raw = b.get("general_world_lore")
    if isinstance(raw, str) and raw.strip():
        core = raw.strip()
    else:
        core = synthesize_general_world_lore_from_legacy(dict(b))
    return _with_naming_discipline(core)
