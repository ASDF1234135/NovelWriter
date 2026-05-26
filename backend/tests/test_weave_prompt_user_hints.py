"""Targeted prompt-shape tests for `_build_weave_prompt`.

We don't drive the LLM here; we just confirm that user-supplied wizard hints
(from `macro_author_notes` section markers) flow through into the JSON prompt
and that the B-tier overgen quota is lifted to honour user-provided counts.
"""
from __future__ import annotations

import json
import math

from app.domain.schema import StoryInput, StorylineTier, VolumePlan
from app.services.anchor_service import AnchorService


def _build_story_input(notes: str = "") -> StoryInput:
    return StoryInput(
        title="王都疑雲",
        premise="A returning knight investigates royal murders.",
        target_total_words=100_000,
        macro_author_notes=notes,
    )


def _build_volumes(n: int = 4) -> list[VolumePlan]:
    return [
        VolumePlan(
            volume_id=f"vol_{i:02d}",
            title=f"卷{i}",
            summary=f"summary {i}",
            chapter_start=(i - 1) * 10 + 1,
            chapter_end=i * 10,
            target_volume_words=25_000,
        )
        for i in range(1, n + 1)
    ]


def _decode_prompt(prompt_text: str) -> dict:
    return json.loads(prompt_text)


def test_weave_prompt_threads_user_subplot_hints_and_volume_goals() -> None:
    service = AnchorService()
    notes = (
        "[[VOLUME_GOALS]]\n"
        "第 1 卷｜揭露案發現場\n"
        "第 2 卷｜突破皇室封鎖\n\n"
        "[[SUBPLOTS]]\n"
        "[S]｜羈絆守護者｜揭露童年友人真實身份\n"
        "[A]｜王城密謀｜宰相秘密的部署\n"
        "[A]｜邊境告急｜北方部族暗中集結\n"
        "[B]｜市井傳聞一｜流言扩散\n"
        "[B]｜市井傳聞二｜情報網甦醒\n"
        "[B]｜市井傳聞三｜雙重間諜現形\n"
    )
    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes),
        volumes=_build_volumes(),
        anchors=[],
        cast=[],
        branch_count=4,
        target_tier=StorylineTier.A_TIER,
        target_volume_id="vol_01",
    )
    payload = _decode_prompt(prompt)

    # Hints are surfaced as structured fields.
    assert payload["user_subplot_hints"] == [
        {"tier": "S", "title": "羈絆守護者", "goal": "揭露童年友人真實身份"},
        {"tier": "A", "title": "王城密謀", "goal": "宰相秘密的部署"},
        {"tier": "A", "title": "邊境告急", "goal": "北方部族暗中集結"},
        {"tier": "B", "title": "市井傳聞一", "goal": "流言扩散"},
        {"tier": "B", "title": "市井傳聞二", "goal": "情報網甦醒"},
        {"tier": "B", "title": "市井傳聞三", "goal": "雙重間諜現形"},
    ]
    assert payload["user_volume_goals"] == [
        {"volume": 1, "goal": "揭露案發現場"},
        {"volume": 2, "goal": "突破皇室封鎖"},
    ]

    # The global "prefer user hints" requirement is present.
    joined_reqs = "\n".join(payload["requirements"])
    assert "user_subplot_hints" in joined_reqs
    assert "prefer reusing the provided titles/goals" in joined_reqs
    assert "user_volume_goals" in joined_reqs

    # A_TIER-specific reinforcement when [A] hints exist.
    assert "user_subplot_hints contains entries tagged [A]" in joined_reqs


def test_weave_prompt_b_tier_quota_respects_user_count() -> None:
    """When the user provides more B hints than the formula's overgen ceiling,
    the prompt must ask for at least the user-provided count of B_TIER lines."""
    service = AnchorService()
    branch_count = 2  # ceil(2 * 1.5) = 3 — formula ceiling = 3
    user_b_count = 6  # explicit override above the formula
    b_lines = "\n".join(f"[B]｜beat-{i}｜goal-{i}" for i in range(1, user_b_count + 1))
    notes = f"[[SUBPLOTS]]\n{b_lines}\n"

    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes),
        volumes=_build_volumes(branch_count),
        anchors=[],
        cast=[],
        branch_count=branch_count,
        target_tier=StorylineTier.B_TIER,
    )
    payload = _decode_prompt(prompt)
    joined_reqs = "\n".join(payload["requirements"])

    # Backend formula would have asked for 3; user pushed it to 6.
    expected_quota = max(
        max(1, int(math.ceil(branch_count * 1.3))),
        int(math.ceil(branch_count * 1.5)),
        user_b_count,
    )
    assert expected_quota == user_b_count
    assert f"Generate exactly {user_b_count} independent B_TIER storylines" in joined_reqs
    # Backend never drops below quota: cover-every-hint instruction is present.
    assert "cover every [B] hint first" in joined_reqs


def test_weave_prompt_b_tier_quota_keeps_formula_when_user_count_is_smaller() -> None:
    """User cannot lower the backend's B-tier quota by supplying fewer hints."""
    service = AnchorService()
    branch_count = 6  # ceil(6 * 1.5) = 9 — formula ceiling = 9
    user_b_count = 2
    b_lines = "\n".join(f"[B]｜beat-{i}｜goal-{i}" for i in range(1, user_b_count + 1))
    notes = f"[[SUBPLOTS]]\n{b_lines}\n"

    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes),
        volumes=_build_volumes(branch_count),
        anchors=[],
        cast=[],
        branch_count=branch_count,
        target_tier=StorylineTier.B_TIER,
    )
    payload = _decode_prompt(prompt)
    joined_reqs = "\n".join(payload["requirements"])

    expected_quota = int(math.ceil(branch_count * 1.5))  # = 9
    assert expected_quota == 9
    assert f"Generate exactly {expected_quota} independent B_TIER storylines" in joined_reqs


def test_weave_prompt_no_hints_falls_back_to_baseline() -> None:
    """When the wizard didn't write any markers, the prompt should not include
    the user-hint requirements and should keep the original quota."""
    service = AnchorService()
    branch_count = 4

    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes="legacy free-form notes only"),
        volumes=_build_volumes(branch_count),
        anchors=[],
        cast=[],
        branch_count=branch_count,
        target_tier=StorylineTier.B_TIER,
    )
    payload = _decode_prompt(prompt)
    joined_reqs = "\n".join(payload["requirements"])

    assert payload["user_subplot_hints"] == []
    assert payload["user_volume_goals"] == []
    assert "prefer reusing the provided titles/goals" not in joined_reqs
    assert "cover every [B] hint first" not in joined_reqs
    # Formula quota for branch_count=4 is ceil(4 * 1.5) = 6
    assert "Generate exactly 6 independent B_TIER storylines" in joined_reqs


def test_weave_prompt_falls_back_to_parsing_notes_if_callers_omit_hints() -> None:
    """`_build_weave_prompt` parses notes itself when callers don't pass hints —
    keeps backward compatibility with existing call sites."""
    service = AnchorService()
    notes = "[[SUBPLOTS]]\n[A]｜密謀｜部署"

    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes),
        volumes=_build_volumes(),
        anchors=[],
        cast=[],
        branch_count=4,
        target_tier=StorylineTier.A_TIER,
        target_volume_id="vol_01",
        # Note: user_subplot_hints/user_volume_goals deliberately omitted.
    )
    payload = _decode_prompt(prompt)
    assert payload["user_subplot_hints"] == [
        {"tier": "A", "title": "密謀", "goal": "部署"},
    ]


def test_weave_prompt_s_tier_emphasis_only_when_s_hints_exist() -> None:
    service = AnchorService()

    notes_with_s = "[[SUBPLOTS]]\n[S]｜守護｜揭露真相"
    prompt = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes_with_s),
        volumes=_build_volumes(),
        anchors=[],
        cast=[],
        branch_count=4,
        target_tier=StorylineTier.S_TIER,
        target_volume_id="vol_01",
    )
    reqs = "\n".join(_decode_prompt(prompt)["requirements"])
    assert "user_subplot_hints contains entries tagged [S]" in reqs

    notes_no_s = "[[SUBPLOTS]]\n[A]｜密謀｜部署"
    prompt_no_s = service._build_weave_prompt(
        story_id="story_test",
        story_input=_build_story_input(notes_no_s),
        volumes=_build_volumes(),
        anchors=[],
        cast=[],
        branch_count=4,
        target_tier=StorylineTier.S_TIER,
        target_volume_id="vol_01",
    )
    reqs_no_s = "\n".join(_decode_prompt(prompt_no_s)["requirements"])
    assert "user_subplot_hints contains entries tagged [S]" not in reqs_no_s
