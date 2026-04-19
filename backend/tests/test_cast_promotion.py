"""cast_json promotion and bible active_b_stories fields."""

from app.domain.schema import StoryCastMemberStored, StoryInput
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository


def test_merge_active_b_stories_seed_stores_resolution_condition(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "b.sqlite3"))
    repo = StoryRepository(db)
    story = repo.create_story(
        "story_x",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    repo.merge_active_b_stories_seed(
        story["story_id"],
        [{"id": "b1", "desc": "d", "type": "LORE_DISCOVERY", "resolution_condition": "取得關鍵名單"}],
    )
    row = repo.get_story(story["story_id"])
    bible = row["bible_json"]
    active = bible.get("active_b_stories") or []
    assert len(active) == 1
    assert active[0]["resolution_condition"] == "取得關鍵名單"


def test_soft_upsert_story_cast_member_fill_empty_only_and_strip_legacy_key(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "c.sqlite3"))
    repo = StoryRepository(db)
    story = repo.create_story(
        "story_y",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    sid = story["story_id"]
    m = StoryCastMemberStored(
        node_id="char_1",
        canonical_name="A",
        role="supporting",
        core_motivation="x",
        personality="冷靜",
    )
    repo.soft_upsert_story_cast_member(sid, m)
    # Existing non-empty fields should not be overwritten.
    repo.soft_upsert_story_cast_member(
        sid,
        StoryCastMemberStored(
            node_id="char_1",
            canonical_name="A2",
            role="supporting",
            personality="衝動",
            core_motivation="y",
            speech_style="短句",
        ),
    )
    row = repo.get_story(sid)
    cast = row["cast_json"]
    assert len(cast) == 1
    assert cast[0]["node_id"] == "char_1"
    assert cast[0]["personality"] == "冷靜"
    assert cast[0]["core_motivation"] == "x"
    assert cast[0]["speech_style"] == "短句"
    assert "motivation" not in cast[0]
    assert "core_value" in cast[0]


def test_apply_cast_update_evolution_overwrites_profile_and_appends_arc_history(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "evo.sqlite3"))
    repo = StoryRepository(db)
    story = repo.create_story(
        "story_evo",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    sid = story["story_id"]
    repo.soft_upsert_story_cast_member(
        sid,
        StoryCastMemberStored(
            node_id="char_1",
            canonical_name="A",
            role="supporting",
            personality="傲慢",
            speech_style="鋒利短句",
        ),
    )
    update_payload = {
        "update_mode": "evolution",
        "member": {
            "node_id": "char_1",
            "canonical_name": "A",
            "role": "supporting",
            "personality": "內斂",
            "speech_style": "低聲慢語",
        },
        "milestone": {
            "trigger_event_id": "",
            "trigger_event_summary": "摯友陣亡",
            "chapter_id": 5,
            "old_personality": "傲慢",
            "new_personality": "內斂",
            "old_speech_style": "鋒利短句",
            "new_speech_style": "低聲慢語",
            "source": "PLANNER",
            "reason": "重大失敗",
            "updated_at": "2026-04-18T00:00:00+00:00",
        },
    }
    repo.apply_cast_update(sid, update_payload)
    # Duplicate same chapter/event should dedupe arc append.
    repo.apply_cast_update(sid, update_payload)

    row = repo.get_story(sid)
    cast = row["cast_json"]
    assert cast[0]["personality"] == "內斂"
    assert cast[0]["speech_style"] == "低聲慢語"
    assert len(cast[0]["arc_history"]) == 1
    assert cast[0]["arc_history"][0]["trigger_event_summary"] == "摯友陣亡"
