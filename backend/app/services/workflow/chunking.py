from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from app.services.workflow.output_language import normalize_output_language, strip_leading_chapter_heading_line


ChunkRole = Literal["prev_tail", "current_body"]


@dataclass(frozen=True)
class ChapterChunk:
    chunk_id: str
    chunk_index: int
    chapter_id: int
    source_chapter_id: int
    source_role: ChunkRole
    text_chunk: str


_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")


def extract_prev_tail(text: str, *, output_language: str, zh_chars: int = 300, en_words: int = 150) -> str:
    """Extract trailing tail snippet for cross-chapter continuity (language-sensitive)."""
    cleaned = strip_leading_chapter_heading_line(text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if normalize_output_language(output_language) == "en":
        words = [w for w in re.split(r"\s+", cleaned) if w]
        if len(words) <= en_words:
            return " ".join(words)
        return " ".join(words[-en_words:])
    # Default: CJK by chars (roughly aligns with your spec)
    if len(cleaned) <= zh_chars:
        return cleaned
    return cleaned[-zh_chars:]


def _chunk_by_paragraphs(text: str, *, target_chars: int) -> list[str]:
    cleaned = strip_leading_chapter_heading_line(text or "")
    paras = [p.strip() for p in _PARA_SPLIT_RE.split(cleaned) if p.strip()]
    if not paras:
        cleaned = cleaned.strip()
        return [cleaned] if cleaned else []
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for p in paras:
        p_size = len(p) + (2 if buf else 0)
        if buf and size + p_size > target_chars:
            out.append("\n\n".join(buf).strip())
            buf = [p]
            size = len(p)
            continue
        buf.append(p)
        size += p_size
    if buf:
        out.append("\n\n".join(buf).strip())
    return [x for x in out if x]


def _fallback_stride_chunks(text: str, *, target_chars: int, overlap_chars: int) -> list[str]:
    cleaned = strip_leading_chapter_heading_line(text or "").strip()
    if not cleaned:
        return []
    if target_chars <= 0:
        return [cleaned]
    step = max(1, target_chars - max(0, overlap_chars))
    out: list[str] = []
    i = 0
    while i < len(cleaned):
        out.append(cleaned[i : i + target_chars].strip())
        i += step
    return [x for x in out if x]


def chunk_text_hybrid(
    text: str,
    *,
    target_chars: int,
    overlap_chars: int,
) -> list[str]:
    """
    Hybrid chunking:
    - Prefer paragraph boundaries
    - Fall back to fixed stride for oversized paragraphs / empty paragraph structure
    """
    if not text or not text.strip():
        return []
    para_chunks = _chunk_by_paragraphs(text, target_chars=target_chars)
    out: list[str] = []
    for ch in para_chunks:
        if len(ch) <= max(50, target_chars * 2):
            out.append(ch)
            continue
        # Single huge chunk: split further by stride.
        out.extend(_fallback_stride_chunks(ch, target_chars=target_chars, overlap_chars=overlap_chars))
    return [x for x in out if x]


def build_chapter_chunks(
    *,
    story_id: str,
    chapter_id: int,
    current_body: str,
    prev_tail: str,
    target_chars: int = 1200,
    overlap_chars: int = 120,
) -> list[ChapterChunk]:
    """
    Build chunks for extraction alignment.
    - prev_tail is chunked first (role=prev_tail, source_chapter_id=chapter_id-1)
    - current_body next (role=current_body, source_chapter_id=chapter_id)
    chunk_id is stable by chunk_index: uuid5(story_id:chapter_id:chunk_index)
    """
    chunks: list[tuple[ChunkRole, int, str]] = []
    if prev_tail.strip():
        for t in chunk_text_hybrid(prev_tail, target_chars=target_chars, overlap_chars=overlap_chars):
            chunks.append(("prev_tail", chapter_id - 1, t))
    for t in chunk_text_hybrid(current_body, target_chars=target_chars, overlap_chars=overlap_chars):
        chunks.append(("current_body", chapter_id, t))

    out: list[ChapterChunk] = []
    for idx, (role, source_cid, text_chunk) in enumerate(chunks):
        chunk_id = str(uuid5(NAMESPACE_URL, f"{story_id}:{chapter_id}:{idx}"))
        out.append(
            ChapterChunk(
                chunk_id=chunk_id,
                chunk_index=idx,
                chapter_id=chapter_id,
                source_chapter_id=source_cid,
                source_role=role,
                text_chunk=text_chunk,
            )
        )
    return out

