from app.domain.schema import BeatOutline, EventLink, EventLinkType, EventOutline
from app.services.workflow.event_normalization import (
    coalesce_over_fragmented_events,
    normalize_beats,
    normalize_event_ai_flags,
    normalize_event_ids,
)


def test_normalize_event_ids_rewrites_legacy_ids_and_causal_links() -> None:
    events = [
        EventOutline(event_id="event_ai_invention_04", description="A", caused_by_event_id=None),
        EventOutline(
            event_id="evt_custom",
            description="B",
            caused_by_event_id="event_ai_invention_04",
            links=[EventLink(target_event_id="event_ai_invention_04", link_type=EventLinkType.CAUSAL)],
        ),
    ]
    result = normalize_event_ids(12, events)
    assert [event.event_id for event in result.events] == ["event_ch12_01", "event_ch12_02"]
    assert result.events[1].caused_by_event_id == "event_ch12_01"
    assert result.events[1].links[0].target_event_id == "event_ch12_01"
    assert result.events[1].links[0].link_type == EventLinkType.CAUSAL
    assert set(result.malformed_ids) == {"event_ai_invention_04", "evt_custom"}


def test_normalize_event_ai_flags_reads_legacy_tag() -> None:
    event = EventOutline(event_id="event_x", description="[AI_INVENTION] hero improvises")
    normalized = normalize_event_ai_flags([event])[0]
    assert normalized.description == "hero improvises"
    assert normalized.is_ai_invention is True
    assert normalized.invention_scope == "legacy_tag"


def test_normalize_beats_prefers_schema_field_and_cleans_legacy_tag() -> None:
    beats, outlines = normalize_beats(
        [],
        [
            BeatOutline(text="[AI_INVENTION] add hidden clue", is_ai_invention=False),
            BeatOutline(text="keep this human-authored beat", is_ai_invention=False),
        ],
    )
    assert beats == ["add hidden clue", "keep this human-authored beat"]
    assert outlines[0].is_ai_invention is True
    assert outlines[1].is_ai_invention is False


def test_coalesce_over_fragmented_events_respects_max_events() -> None:
    events = [
        EventOutline(event_id=f"event_raw_{idx:02d}", description=f"event {idx}", caused_by_event_id=None)
        for idx in range(1, 13)
    ]
    merged = coalesce_over_fragmented_events(events, max_events=6)
    assert len(merged) <= 6
