from __future__ import annotations

import json
import re
from difflib import SequenceMatcher


_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def _looks_like_latin_word(term: str) -> bool:
    """Heuristic: treat ASCII-ish terms as word-like for \\b matching.

    This is intentionally conservative: if we can't safely word-boundary match, callers should fall back to
    non-boundary substring logic (useful for CJK, mixed scripts, or punctuated tokens).
    """
    t = str(term or "").strip()
    if not t:
        return False
    if not _LATIN_LETTER_RE.search(t):
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'’ ")
    return all(ch in allowed for ch in t)


def looks_like_latin_word(term: str) -> bool:
    """Public wrapper for Latin-ish token detection (used to avoid substring pollution)."""
    return _looks_like_latin_word(term)


def latin_word_boundary_search(term: str, text: str) -> bool:
    """Case-insensitive \\b...\\b match for Latin-ish terms; False when term is not suitable."""
    t = str(term or "").strip()
    if not _looks_like_latin_word(t):
        return False
    # Collapse whitespace inside multi-word names: \"Van  Helsing\" matches \"van helsing\" etc.
    parts = [p for p in t.split() if p]
    if not parts:
        return False
    inner = r"\s+".join(re.escape(p) for p in parts)
    pat = re.compile(rf"\b{inner}\b", flags=re.IGNORECASE)
    return bool(pat.search(text or ""))


def latin_word_boundary_sub(term: str, repl: str, text: str) -> str:
    """Regex replace using Latin \\b boundaries when possible; otherwise returns input text unchanged."""
    t = str(term or "").strip()
    if not _looks_like_latin_word(t):
        return text
    parts = [p for p in t.split() if p]
    if not parts:
        return text
    inner = r"\s+".join(re.escape(p) for p in parts)
    pat = re.compile(rf"\b{inner}\b", flags=re.IGNORECASE)
    return pat.sub(repl, text or "")


def normalize_surface_text_for_match(text: str) -> str:
    """Light normalization for fallback matching (keeps language content intact)."""
    t = str(text or "")
    t = t.casefold()
    t = re.sub(r"[-_]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def surface_form_match_with_fallback(surface: str, draft: str) -> bool:
    s = str(surface or "").strip()
    d = str(draft or "")
    if not s or not d:
        return False
    if looks_like_latin_word(s):
        if latin_word_boundary_search(s, d):
            return True
        # Lightweight fallback for punctuation/spacing variants.
        ns = normalize_surface_text_for_match(s)
        nd = normalize_surface_text_for_match(d)
        return bool(ns and ns in nd)
    return s in d


def suggest_nearest_surface_candidates(surface: str, draft: str, limit: int = 3) -> list[str]:
    """Best-effort nearby string suggestions from draft for diagnostics only."""
    s = normalize_surface_text_for_match(surface)
    d = normalize_surface_text_for_match(draft)
    if not s or not d:
        return []
    tokens = [tok for tok in re.split(r"\s+", d) if tok]
    if not tokens:
        return []
    window = max(1, len(s.split()))
    spans: list[str] = []
    for i in range(len(tokens)):
        chunk = " ".join(tokens[i : i + window])
        if chunk:
            spans.append(chunk)
        chunk2 = " ".join(tokens[i : i + window + 1])
        if chunk2:
            spans.append(chunk2)
    scored = sorted(
        ((SequenceMatcher(None, s, c).ratio(), c) for c in spans),
        key=lambda x: x[0],
        reverse=True,
    )
    out: list[str] = []
    for score, cand in scored:
        if score < 0.45:
            continue
        if cand not in out:
            out.append(cand)
        if len(out) >= limit:
            break
    return out


def estimate_word_count(text: str) -> int:
    if not text.strip():
        return 0
    if " " in text:
        return len([part for part in text.split() if part.strip()])
    return len(text)


_EN_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


def english_word_count(text: str) -> int:
    """English prose length: whitespace-separated tokens; if none, count Latin alphanumeric runs (e.g. TITLE without spaces)."""
    s = (text or "").strip()
    if not s:
        return 0
    if re.search(r"\s", s):
        return len([p for p in re.split(r"\s+", s) if p])
    return len(_EN_WORD_TOKEN_RE.findall(s))


def normalized_text_length(text: str) -> int:
    """Legacy normalized length for CJK paths: count Unicode alphanumeric characters (punctuation/space excluded)."""
    return sum(1 for char in text if char.isalnum())


def chapter_content_length(text: str, output_language: str | None) -> int:
    """Single length unit for gates: English word count; non-en uses normalized_text_length (isalnum)."""
    from app.services.workflow.output_language import normalize_output_language

    if normalize_output_language(output_language) == "en":
        return english_word_count(text)
    return normalized_text_length(text)


def truncate_json_payload(payload: dict, max_chars: int = 5000) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(encoded) <= max_chars:
        return encoded
    return encoded[:max_chars] + "\n...TRUNCATED..."
