"""Normalize bible writing_note list for prompts and UI (naming discipline defaults)."""

from __future__ import annotations

NAMING_DISCIPLINE_WRITING_NOTES: tuple[str, ...] = (
    "命名節制：新名詞只在必要時使用；若不影響後文辨識與決策，優先不用命名。",
    "去標籤化：遇到陌生現象或物件，先用可觀察的感官與行為結果描述，不要先貼術語標籤。",
)


def normalize_writing_note(raw: object) -> list[str]:
    src = raw if isinstance(raw, list) else []
    out: list[str] = []
    for item in src:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        if text not in out:
            out.append(text)
    for text in NAMING_DISCIPLINE_WRITING_NOTES:
        if text not in out:
            out.append(text)
    return out[:24]
