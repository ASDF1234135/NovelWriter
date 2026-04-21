from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.schema import BeatOutline, EventLink, EventLinkOrigin, EventLinkType, EventOutline

AI_INVENTION_TAG = "[AI_INVENTION]"
EVENT_ID_PATTERN = re.compile(r"^event_ch(?P<chapter>\d+)_(?P<seq>\d{2})$")
DEFAULT_MAX_EVENTS_PER_CHAPTER = 8


@dataclass(frozen=True)
class EventNormalizationResult:
    events: list[EventOutline]
    id_map: dict[str, str]
    malformed_ids: list[str]


@dataclass(frozen=True)
class NormalizedEventLink:
    source_event_id: str
    target_event_id: str
    link_type: EventLinkType
    origin: EventLinkOrigin


def is_standard_event_id(event_id: str, *, chapter_id: int | None = None) -> bool:
    match = EVENT_ID_PATTERN.match((event_id or "").strip())
    if not match:
        return False
    if chapter_id is None:
        return True
    return int(match.group("chapter")) == chapter_id


def normalize_ai_invention_text(raw: str, *, default_scope: str = "") -> tuple[str, bool, str]:
    text = (raw or "").strip()
    if not text:
        return "", False, ""
    if AI_INVENTION_TAG not in text:
        return text, False, default_scope.strip()
    cleaned = text.replace(AI_INVENTION_TAG, "").strip()
    scope = default_scope.strip() or "legacy_tag"
    return cleaned, True, scope


def normalize_event_ai_flags(events: list[EventOutline]) -> list[EventOutline]:
    normalized: list[EventOutline] = []
    for event in events:
        clean_desc, inferred_flag, inferred_scope = normalize_ai_invention_text(event.description)
        normalized.append(
            EventOutline(
                event_id=event.event_id,
                description=clean_desc,
                caused_by_event_id=event.caused_by_event_id,
                links=list(event.links),
                is_ai_invention=bool(event.is_ai_invention or inferred_flag),
                invention_scope=(event.invention_scope or inferred_scope).strip(),
            )
        )
    return normalized


def normalize_beats(beats: list[str], beat_outlines: list[BeatOutline]) -> tuple[list[str], list[BeatOutline]]:
    outlines = list(beat_outlines or [])
    if not outlines:
        outlines = [BeatOutline(text=(beat or "").strip()) for beat in beats if (beat or "").strip()]
    normalized_outlines: list[BeatOutline] = []
    for beat in outlines:
        clean_text, inferred_flag, inferred_scope = normalize_ai_invention_text(beat.text)
        if not clean_text:
            continue
        normalized_outlines.append(
            BeatOutline(
                text=clean_text,
                is_ai_invention=bool(beat.is_ai_invention or inferred_flag),
                invention_scope=(beat.invention_scope or inferred_scope).strip(),
            )
        )
    return [beat.text for beat in normalized_outlines], normalized_outlines


def coalesce_over_fragmented_events(
    events: list[EventOutline],
    *,
    max_events: int = DEFAULT_MAX_EVENTS_PER_CHAPTER,
) -> list[EventOutline]:
    if len(events) <= max_events:
        return events
    merged: list[EventOutline] = []
    group: list[EventOutline] = []
    target_size = max(1, round(len(events) / max_events))
    for event in events:
        group.append(event)
        if len(group) >= target_size:
            merged.append(_merge_event_group(group))
            group = []
    if group:
        merged.append(_merge_event_group(group))
    return merged


def _merge_event_group(group: list[EventOutline]) -> EventOutline:
    first = group[0]
    last = group[-1]
    merged_description = "; ".join((row.description or "").strip() for row in group if (row.description or "").strip())
    return EventOutline(
        event_id=last.event_id,
        description=merged_description[:300],
        caused_by_event_id=first.caused_by_event_id,
        links=list(first.links),
        is_ai_invention=any(row.is_ai_invention for row in group),
        invention_scope=last.invention_scope or first.invention_scope,
    )


def normalize_event_ids(chapter_id: int, events: list[EventOutline]) -> EventNormalizationResult:
    normalized_events: list[EventOutline] = []
    id_map: dict[str, str] = {}
    malformed_ids: list[str] = []
    for idx, event in enumerate(events, start=1):
        normalized_id = f"event_ch{chapter_id}_{idx:02d}"
        prior_id = (event.event_id or "").strip()
        if prior_id:
            id_map[prior_id] = normalized_id
            if not is_standard_event_id(prior_id, chapter_id=chapter_id):
                malformed_ids.append(prior_id)
        normalized_events.append(
            EventOutline(
                event_id=normalized_id,
                description=event.description,
                caused_by_event_id=event.caused_by_event_id,
                links=list(event.links),
                is_ai_invention=event.is_ai_invention,
                invention_scope=event.invention_scope,
            )
        )
    rewritten: list[EventOutline] = []
    normalized_ids = {row.event_id for row in normalized_events}
    for event in normalized_events:
        caused_by = (event.caused_by_event_id or "").strip()
        rewritten_links: list[EventLink] = []
        for link in event.links:
            target = (id_map.get(link.target_event_id, link.target_event_id) or "").strip()
            if not target:
                continue
            if target not in normalized_ids:
                continue
            rewritten_links.append(EventLink(target_event_id=target, link_type=link.link_type, origin=link.origin))
        rewritten.append(
            EventOutline(
                event_id=event.event_id,
                description=event.description,
                caused_by_event_id=id_map.get(caused_by, caused_by) or None,
                links=rewritten_links,
                is_ai_invention=event.is_ai_invention,
                invention_scope=event.invention_scope,
            )
        )
    return EventNormalizationResult(events=rewritten, id_map=id_map, malformed_ids=malformed_ids)


def flatten_event_links(events: list[EventOutline]) -> list[NormalizedEventLink]:
    by_id = {event.event_id: event for event in events}
    out: list[NormalizedEventLink] = []
    for event in events:
        source_origin = (
            EventLinkOrigin.AI_INVENTION
            if event.is_ai_invention
            else EventLinkOrigin.HUMAN_GROUND_TRUTH
        )
        for link in event.links:
            target_event = by_id.get(link.target_event_id)
            if target_event is None:
                continue
            out.append(
                NormalizedEventLink(
                    source_event_id=event.event_id,
                    target_event_id=link.target_event_id,
                    link_type=link.link_type,
                    origin=link.origin or source_origin,
                )
            )
    return out
