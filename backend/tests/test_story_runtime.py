"""Unit tests for bible/runtime split and anchor skeleton hydration."""

from app.domain.story_runtime import (
    anchor_nodes_to_skeleton_rows,
    extract_runtime_from_bible,
    hydrate_anchor_nodes,
    strip_runtime_keys_from_bible,
)
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository


def test_strip_runtime_keys_from_bible() -> None:
    bible = {
        "general_world_lore": "## Lore\n\nHello.",
        "resolved_anchors": ["a1"],
        "anchor_candidates": ["a2"],
        "lore_mysteries_progression": [{"mystery_id": "m1"}],
    }
    out = strip_runtime_keys_from_bible(bible)
    assert out == {"general_world_lore": "## Lore\n\nHello."}
    assert "resolved_anchors" in bible


def test_extract_runtime_roundtrip_create_story(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "story_runtime.sqlite3"))
    repo = StoryRepository(db)
    story_id = "s-runtime-1"
    bible_in = {
        "general_world_lore": "X",
        "resolved_anchors": ["n1"],
        "lore_mysteries_progression": [{"mystery_id": "mem", "pending_stages": [{"stage": 1}]}],
        "anchor_nodes": [
            {
                "id": "n1",
                "storyline_ids": [],
                "volume_id": "v1",
                "node_kind": "NORMAL",
                "title": "T",
                "description": "D",
                "depends_on": [],
                "status": "RESOLVED",
            }
        ],
    }
    from app.domain.schema import StoryInput

    repo.create_story(
        story_id,
        StoryInput(title="T", premise="p", bible=bible_in, target_total_words=1000),
    )
    row = repo.get_story(story_id)
    assert row
    assert "resolved_anchors" not in row["bible_json"]
    rt = row["story_runtime_json"]
    assert "n1" in rt["resolved_anchors"]
    assert rt["lore_mysteries_progression"]
    nodes = row["anchor_nodes_json"]
    assert any(str(n.get("id")) == "n1" and str(n.get("status")).upper() == "RESOLVED" for n in nodes)


def test_skeleton_strip_preserves_hitl_deferred_in_runtime() -> None:
    nodes = [
        {
            "id": "a1",
            "volume_id": "v",
            "node_kind": "NORMAL",
            "title": "",
            "description": "",
            "depends_on": [],
            "status": "UNLOCKED",
            "properties": {"hitl_deferred": True},
        }
    ]
    skel, props = anchor_nodes_to_skeleton_rows(nodes)
    assert "status" not in skel[0]
    assert props == {"a1": {"hitl_deferred": True}}
    hydrated = hydrate_anchor_nodes(
        skel,
        resolved_anchors=[],
        anchor_properties={"a1": {"hitl_deferred": True}},
    )
    assert hydrated[0].get("properties", {}).get("hitl_deferred") is True
