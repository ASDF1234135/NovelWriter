from __future__ import annotations

import json


def estimate_word_count(text: str) -> int:
    if not text.strip():
        return 0
    if " " in text:
        return len([part for part in text.split() if part.strip()])
    return len(text)


def normalized_text_length(text: str) -> int:
    return sum(1 for char in text if char.isalnum())


def truncate_json_payload(payload: dict, max_chars: int = 5000) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(encoded) <= max_chars:
        return encoded
    return encoded[:max_chars] + "\n...TRUNCATED..."
