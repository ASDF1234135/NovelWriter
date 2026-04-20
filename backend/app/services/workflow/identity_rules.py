from __future__ import annotations

import re

_IDENTITY_RULE_MARKERS = (
    "身分",
    "身份",
    "真名",
    "真相",
    "其實是",
    "真正是",
    "identity",
    "true identity",
    "true name",
    "reveal identity",
)

_LOW_RISK_LABEL_PATTERNS = (
    re.compile(r"^\s*memory\s*[-_#]?\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*file\s*[-_#]?\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*case\s*[-_#]?\s*[A-Za-z]?\d+(?:-\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*log\s*[-_#]?\s*\d+\s*$", re.IGNORECASE),
)

_IDENTITY_MAPPING_PATTERNS = (
    re.compile(r"(?:其實是|真正是|就是)\s*([A-Za-z\u4e00-\u9fff]{2,40})"),
    re.compile(r"(?:is|was)\s+(?:actually|really)\s+([A-Za-z][A-Za-z0-9 _'’-]{1,40})", re.IGNORECASE),
    re.compile(r"(?:true identity(?: is|:)?|true name(?: is|:)?)\s*([A-Za-z][A-Za-z0-9 _'’-]{1,40})", re.IGNORECASE),
)


def looks_like_identity_rule(text: str) -> bool:
    lowered = str(text or "").casefold()
    return any(marker.casefold() in lowered for marker in _IDENTITY_RULE_MARKERS)


def is_low_risk_identity_label(token: str) -> bool:
    t = str(token or "").strip()
    if not t:
        return True
    return any(pat.match(t) for pat in _LOW_RISK_LABEL_PATTERNS)


def extract_identity_tokens(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    candidates: set[str] = set()

    for pat in _IDENTITY_MAPPING_PATTERNS:
        for m in pat.findall(raw):
            token = m.strip() if isinstance(m, str) else str(m).strip()
            if token and not is_low_risk_identity_label(token):
                candidates.add(token)

    if looks_like_identity_rule(raw):
        for pat in (r"「([^」]{1,40})」", r"'([^']{1,40})'", r"\"([^\"]{1,40})\""):
            for m in re.findall(pat, raw):
                token = m.strip()
                if token and not is_low_risk_identity_label(token):
                    candidates.add(token)

    return sorted(candidates)
