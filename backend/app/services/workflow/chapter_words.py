"""Chapter target word count helpers (volume-agnostic)."""


def clamp_chapter_word_count(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
