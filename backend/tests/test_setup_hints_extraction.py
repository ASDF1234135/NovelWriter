"""Round-trip tests for the wizard's macro_author_notes section markers.

The frontend wizard (`frontend/src/features/story-setup/setupPhases.ts`) writes
structured Stage 2/3 fields into `macro_author_notes` under stable markers.
These tests pin down the inverse extraction used by `_build_weave_prompt`.
"""
from __future__ import annotations

from app.services.anchor_service import (
    _count_subplot_hints_by_tier,
    extract_user_subplot_hints,
    extract_user_volume_goals,
)


def test_extract_user_subplot_hints_round_trips_wizard_format() -> None:
    notes = (
        "[[WORLD]]\nA fictional kingdom under siege.\n\n"
        "[[CHARACTERS]]\nKnight; rival chancellor.\n\n"
        "[[SUBPLOTS]]\n"
        "[S]｜羈絆守護者｜揭露童年友人的真實身份\n"
        "[A]｜王城密謀｜宰相秘密的部署\n"
        "[B]｜市井傳聞｜流言扩散影響王城士氣\n"
        "[A]｜邊境告急｜北方部族暗中集結"
    )
    hints = extract_user_subplot_hints(notes)
    assert hints == [
        {"tier": "S", "title": "羈絆守護者", "goal": "揭露童年友人的真實身份"},
        {"tier": "A", "title": "王城密謀", "goal": "宰相秘密的部署"},
        {"tier": "B", "title": "市井傳聞", "goal": "流言扩散影響王城士氣"},
        {"tier": "A", "title": "邊境告急", "goal": "北方部族暗中集結"},
    ]


def test_extract_user_subplot_hints_tolerates_ascii_pipes() -> None:
    notes = "[[SUBPLOTS]]\n[S] | spine | hold the line\n[B] | tiny | quick beat"
    hints = extract_user_subplot_hints(notes)
    assert hints == [
        {"tier": "S", "title": "spine", "goal": "hold the line"},
        {"tier": "B", "title": "tiny", "goal": "quick beat"},
    ]


def test_extract_user_subplot_hints_returns_empty_when_no_markers() -> None:
    assert extract_user_subplot_hints("") == []
    assert extract_user_subplot_hints("just some legacy notes without markers") == []


def test_extract_user_subplot_hints_skips_empty_rows() -> None:
    notes = "[[SUBPLOTS]]\n[A]｜｜\n[B]｜title｜goal"
    assert extract_user_subplot_hints(notes) == [
        {"tier": "B", "title": "title", "goal": "goal"},
    ]


def test_extract_user_volume_goals_supports_zh_and_en_prefixes() -> None:
    notes = (
        "[[VOLUME_GOALS]]\n"
        "第 1 卷｜揭露案發現場\n"
        "第 2 卷｜突破皇室封鎖\n"
        "V3 | Forge new alliance\n"
        "Volume 4 | Confront the chancellor"
    )
    goals = extract_user_volume_goals(notes)
    assert goals == [
        {"volume": 1, "goal": "揭露案發現場"},
        {"volume": 2, "goal": "突破皇室封鎖"},
        {"volume": 3, "goal": "Forge new alliance"},
        {"volume": 4, "goal": "Confront the chancellor"},
    ]


def test_extract_user_volume_goals_dedupes_and_sorts() -> None:
    notes = (
        "[[VOLUME_GOALS]]\n"
        "第 3 卷｜third\n"
        "第 1 卷｜first\n"
        "第 1 卷｜duplicate first\n"
        "Volume 0 | invalid\n"
        "Volume -1 | negative"
    )
    goals = extract_user_volume_goals(notes)
    assert goals == [
        {"volume": 1, "goal": "first"},
        {"volume": 3, "goal": "third"},
    ]


def test_count_subplot_hints_by_tier() -> None:
    hints = [
        {"tier": "S", "title": "a", "goal": "x"},
        {"tier": "A", "title": "b", "goal": "y"},
        {"tier": "A", "title": "c", "goal": "z"},
        {"tier": "B", "title": "d", "goal": "w"},
        {"tier": "B", "title": "e", "goal": "v"},
        {"tier": "B", "title": "f", "goal": "u"},
    ]
    assert _count_subplot_hints_by_tier(hints) == {"S": 1, "A": 2, "B": 3}


def test_extract_user_subplot_hints_parses_volume_tag_for_a_and_b() -> None:
    notes = (
        "[[SUBPLOTS]]\n"
        "[S]｜羈絆守護者｜揭露童年友人真實身份\n"
        "[A:2]｜王城密謀｜宰相秘密的部署\n"
        "[A:3]｜邊境告急｜北方部族暗中集結\n"
        "[B:1]｜市井傳聞一｜流言扩散\n"
        "[B]｜浮動小節｜沒有綁卷\n"
    )
    hints = extract_user_subplot_hints(notes)
    assert hints == [
        {"tier": "S", "title": "羈絆守護者", "goal": "揭露童年友人真實身份"},
        {"tier": "A", "title": "王城密謀", "goal": "宰相秘密的部署", "volume": 2},
        {"tier": "A", "title": "邊境告急", "goal": "北方部族暗中集結", "volume": 3},
        {"tier": "B", "title": "市井傳聞一", "goal": "流言扩散", "volume": 1},
        {"tier": "B", "title": "浮動小節", "goal": "沒有綁卷"},
    ]


def test_extract_user_subplot_hints_ignores_stray_volume_tag_on_s() -> None:
    """S spans the whole book — even if a frontend bug emits `[S:2]`, we drop the tag."""
    notes = "[[SUBPLOTS]]\n[S:2]｜羈絆｜跨卷守護"
    hints = extract_user_subplot_hints(notes)
    assert hints == [{"tier": "S", "title": "羈絆", "goal": "跨卷守護"}]
    assert "volume" not in hints[0]


def test_extract_user_subplot_hints_tolerates_ascii_pipe_with_volume_tag() -> None:
    notes = "[[SUBPLOTS]]\n[A:1] | side | turn the tide\n[B:4] | quiet | sharpen silence"
    hints = extract_user_subplot_hints(notes)
    assert hints == [
        {"tier": "A", "title": "side", "goal": "turn the tide", "volume": 1},
        {"tier": "B", "title": "quiet", "goal": "sharpen silence", "volume": 4},
    ]


def test_extract_section_with_other_markers_does_not_bleed() -> None:
    notes = (
        "[[WORLD]]\nWorld content with [SAB] brackets that look like subplot lines.\n"
        "[A]｜should be ignored｜here\n\n"
        "[[SUBPLOTS]]\n"
        "[A]｜real one｜real goal"
    )
    hints = extract_user_subplot_hints(notes)
    assert hints == [{"tier": "A", "title": "real one", "goal": "real goal"}]
