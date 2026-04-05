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


def test_append_story_cast_member_if_absent_dedupes(tmp_path) -> None:
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
        motivation="x",
    )
    repo.append_story_cast_member_if_absent(sid, m)
    repo.append_story_cast_member_if_absent(sid, m)
    row = repo.get_story(sid)
    cast = row["cast_json"]
    assert len(cast) == 1
    assert cast[0]["node_id"] == "char_1"
    assert "core_value" in cast[0]
