from app.domain.story_runtime import bible_user_view
from app.services.bible_service import BibleService


def test_compile_full_context_includes_lore_json_and_notes() -> None:
    bible = {
        "general_world_lore": "## Custom\n\nTone is cold.",
        "genre": "奇幻",
        "resolved_anchors": ["should_strip"],
        "anchor_nodes": [{"id": "a1"}],
    }
    svc = BibleService()
    out = svc.compile_full_context(bible, macro_author_notes="作者補充")
    assert "## World lore" in out
    assert "Tone is cold" in out
    assert "## Bible (user fields, JSON)" in out
    assert '"genre": "奇幻"' in out
    assert "resolved_anchors" not in out
    assert "anchor_nodes" not in out
    assert "general_world_lore" not in out.split("## Bible (user fields, JSON)")[-1]
    assert "【作者補充設定】" in out
    assert "作者補充" in out


def test_bible_user_view_omits_compile_keys() -> None:
    view = bible_user_view({"genre": "x", "llm_weave_debug": {}, "lore_mysteries_progression": []})
    assert view == {"genre": "x"}


def test_compile_full_context_not_truncated() -> None:
    long_lore = "A" * 5000
    svc = BibleService()
    out = svc.compile_full_context({"general_world_lore": long_lore})
    assert len(out) >= 5000
