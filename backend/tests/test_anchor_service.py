import json
import pytest

from app.domain.schema import (
    MacroCastMember,
    MacroNestedAnchorDraft,
    MacroPlanOutput,
    MacroVolumePlanDraft,
    StoryCastSeedEntry,
    StoryInput,
)
from app.services.anchor_service import AnchorService, MACRO_AUTHOR_NOTES_MAX, clamp_macro_author_notes
from app.services.workflow.profiles import AgentPromptProfile


class FakeStructuredLLMClient:
    def invoke(self, prompt: str):
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile):
        raise NotImplementedError()

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = json.loads(prompt)
        total = int(data["fixed_total_chapters"])
        third = max(1, total // 3)
        split_one = max(1, third)
        split_two = max(split_one + 1, (total * 2) // 3)
        v1 = (1, split_one)
        v2 = (split_one + 1, split_two)
        v3 = (split_two + 1, total)

        def anchors_for(start: int, end: int, tag: str) -> list[MacroNestedAnchorDraft]:
            span = end - start + 1
            if span >= 3:
                c1 = min(max(start + span // 4, start), end)
                c2 = min(max(start + span // 2, start), end)
                c3 = end
            else:
                c1 = c2 = c3 = end
            return [
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點甲",
                    description=f"卷內推進（{start}-{end}）。",
                    target_state={"phase": tag, "n": 1},
                    chapter_target=c1,
                    priority=1,
                ),
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點乙",
                    description=f"卷內壓力（{start}-{end}）。",
                    target_state={"phase": tag, "n": 2},
                    chapter_target=c2,
                    priority=2,
                ),
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點丙",
                    description=f"卷內收束（{start}-{end}）。",
                    target_state={"phase": tag, "n": 3},
                    chapter_target=c3,
                    priority=3,
                ),
            ]

        output = MacroPlanOutput(
            total_chapters=total,
            bible={
                "story_genre": "奇幻",
                "writing_style": "冷硬敘事",
                "narrative_pov": "第三人稱",
                "tone": "壓抑",
                "world_rules": ["代價律"],
                "factions": ["王室", "邊境"],
            },
            cast=[
                MacroCastMember(canonical_name="Kaelen", role="protagonist", short_bio="被流放的騎士。"),
                MacroCastMember(canonical_name="灰鴉", role="supporting", short_bio="線人。"),
            ],
            volumes=[
                MacroVolumePlanDraft(
                    title="卷一：流放歸來",
                    summary="主角重返王都。",
                    chapter_start=v1[0],
                    chapter_end=v1[1],
                    target_volume_words=12000,
                    anchors=anchors_for(v1[0], v1[1], "v1"),
                ),
                MacroVolumePlanDraft(
                    title="卷二：冰縛真相",
                    summary="命案線索逐步拼合。",
                    chapter_start=v2[0],
                    chapter_end=v2[1],
                    target_volume_words=15000,
                    anchors=anchors_for(v2[0], v2[1], "v2"),
                ),
                MacroVolumePlanDraft(
                    title="卷三：王庭審判",
                    summary="最終攤牌與清算。",
                    chapter_start=v3[0],
                    chapter_end=v3[1],
                    target_volume_words=18000,
                    anchors=anchors_for(v3[0], v3[1], "v3"),
                ),
            ],
        )
        return response_model.model_validate(output.model_dump(mode="json")), type(
            "LLMResultStub",
            (),
            {"content": "", "token_usage": 42, "latency_ms": 15},
        )()


class FakeStructuredLLMClientWithNotesLinks(FakeStructuredLLMClient):
    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = json.loads(prompt)
        total = int(data["fixed_total_chapters"])
        third = max(1, total // 3)
        split_one = max(1, third)
        split_two = max(split_one + 1, (total * 2) // 3)
        v1 = (1, split_one)
        v2 = (split_one + 1, split_two)
        v3 = (split_two + 1, total)

        def anchors_for(start: int, end: int, tag: str) -> list[MacroNestedAnchorDraft]:
            span = end - start + 1
            if span >= 3:
                c1 = min(max(start + span // 4, start), end)
                c2 = min(max(start + span // 2, start), end)
                c3 = end
            else:
                c1 = c2 = c3 = end
            # Always reference KP1 in tests (validation checks id existence, not textual similarity).
            notes_links = ["KP1"]
            return [
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點甲",
                    description=f"卷內推進（{start}-{end}）。",
                    target_state={"phase": tag, "n": 1},
                    chapter_target=c1,
                    priority=1,
                    notes_links=notes_links,
                ),
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點乙",
                    description=f"卷內壓力（{start}-{end}）。",
                    target_state={"phase": tag, "n": 2},
                    chapter_target=c2,
                    priority=2,
                    notes_links=notes_links,
                ),
                MacroNestedAnchorDraft(
                    title=f"{tag} 節點丙",
                    description=f"卷內收束（{start}-{end}）。",
                    target_state={"phase": tag, "n": 3},
                    chapter_target=c3,
                    priority=3,
                    notes_links=notes_links,
                ),
            ]

        output = MacroPlanOutput(
            total_chapters=total,
            bible={
                "story_genre": "奇幻",
                "writing_style": "冷硬敘事",
                "narrative_pov": "第三人稱",
                "tone": "壓抑",
                "world_rules": ["代價律"],
                "factions": ["王室", "邊境"],
            },
            cast=[
                MacroCastMember(
                    canonical_name="Kaelen",
                    role="protagonist",
                    short_bio="被流放的騎士。",
                    notes_links=["KP1"],
                ),
                MacroCastMember(
                    canonical_name="灰鴉",
                    role="supporting",
                    short_bio="線人。",
                    notes_links=["KP1"],
                ),
            ],
            volumes=[
                MacroVolumePlanDraft(
                    title="卷一：流放歸來",
                    summary="主角重返王都。",
                    chapter_start=v1[0],
                    chapter_end=v1[1],
                    target_volume_words=12000,
                    anchors=anchors_for(v1[0], v1[1], "v1"),
                ),
                MacroVolumePlanDraft(
                    title="卷二：冰縛真相",
                    summary="命案線索逐步拼合。",
                    chapter_start=v2[0],
                    chapter_end=v2[1],
                    target_volume_words=15000,
                    anchors=anchors_for(v2[0], v2[1], "v2"),
                ),
                MacroVolumePlanDraft(
                    title="卷三：王庭審判",
                    summary="最終攤牌與清算。",
                    chapter_start=v3[0],
                    chapter_end=v3[1],
                    target_volume_words=18000,
                    anchors=anchors_for(v3[0], v3[1], "v3"),
                ),
            ],
        )
        return response_model.model_validate(output.model_dump(mode="json")), type(
            "LLMResultStub",
            (),
            {"content": "", "token_usage": 42, "latency_ms": 15},
        )()


def test_clamp_macro_author_notes_truncates() -> None:
    long = "x" * (MACRO_AUTHOR_NOTES_MAX + 50)
    out = clamp_macro_author_notes(long)
    assert len(out) == MACRO_AUTHOR_NOTES_MAX


def test_anchor_service_can_use_structured_llm_output() -> None:
    service = AnchorService()
    volumes, anchors, cast, b_seed, bible_out = service.compile_macro_plan(
        "story_test",
        StoryInput(
            title="王都疑雲",
            premise="被流放的騎士回到王都追查皇室命案。",
            target_total_words=45000,
        ),
        FakeStructuredLLMClient(),
    )

    assert bible_out.get("story_genre") == "奇幻"
    assert b_seed == []
    assert len(volumes) == 3
    assert volumes[0].title == "卷一：流放歸來"
    assert volumes[-1].chapter_end == 18
    assert sum(volume.target_volume_words for volume in volumes) == 45000
    assert len(anchors) == 9
    assert anchors[0].volume_id == volumes[0].volume_id
    assert anchors[-1].target_state.get("n") == 3
    assert len(cast) == 2
    assert cast[0].role == "protagonist"
    assert cast[0].node_id == "story_test_mc_01"
    assert cast[0].canonical_name == "Kaelen"
    assert cast[0].core_value is not None
    assert isinstance(cast[0].core_value, str)
    assert cast[1].node_id == "story_test_mc_02"
    assert cast[1].canonical_name == "灰鴉"


def test_normalize_cast_merge_seed_keeps_missing_name() -> None:
    service = AnchorService()
    _, _, cast, _, _ = service.compile_macro_plan(
        "story_seed_merge",
        StoryInput(
            title="種子測試",
            premise="主角與同伴。",
            target_total_words=45000,
            cast_seed=[StoryCastSeedEntry(canonical_name="獨角獸", short_hint="必須出現在 cast")],
        ),
        FakeStructuredLLMClient(),
    )
    names = [c.canonical_name for c in cast]
    assert "獨角獸" in names
    assert "Kaelen" in names


def test_normalize_cast_seven_members_not_truncated() -> None:
    service = AnchorService()
    raw = [
        MacroCastMember(
            canonical_name=f"角色{i}",
            role="supporting",
            short_bio="",
            core_motivation="推進主線",
        )
        for i in range(7)
    ]
    raw[0] = raw[0].model_copy(update={"role": "protagonist"})
    out = service._normalize_cast_output(
        "story_big",
        raw,
        StoryInput(title="大陣容", premise="多核心人物。", target_total_words=45000),
    )
    assert len(out) == 7
    assert out[0].node_id == "story_big_mc_01"


def test_macro_prompt_includes_cast_seed_when_set() -> None:
    service = AnchorService()
    si = StoryInput(
        title="T",
        premise="p",
        target_total_words=45000,
        cast_seed=[StoryCastSeedEntry(canonical_name="甲", role="protagonist")],
    )
    prompt = service._build_macro_prompt(si, fixed_total_chapters=18, fixed_total_volumes=3)
    assert "cast_seed" in prompt
    assert "甲" in prompt
    assert "恰好" not in prompt
    assert "人數不限" in prompt


def test_anchor_service_clamps_llm_plan_to_formula_total_chapters() -> None:
    service = AnchorService()
    volumes, anchors, cast, b_seed, _bible = service.compile_macro_plan(
        "story_formula",
        StoryInput(
            title="短篇測試",
            premise="主角在冬夜返城。",
            target_total_words=30000,
        ),
        FakeStructuredLLMClient(),
    )

    assert b_seed == []
    assert volumes[-1].chapter_end == 12
    assert max(anchor.chapter_target for anchor in anchors) <= 12
    assert sum(volume.target_volume_words for volume in volumes) == 30000
    assert len(anchors) == 9
    assert len(cast) >= 1
    assert any(m.role == "protagonist" for m in cast)


def test_macro_compile_fixed_volumes_scales_with_total_words() -> None:
    service = AnchorService()
    volumes, anchors, _cast, _b_seed, _bible = service.compile_macro_plan(
        "story_100k",
        StoryInput(
            title="測試 10萬字",
            premise="主角回歸並揭開背後真相。",
            target_total_words=100000,
        ),
        FakeStructuredLLMClient(),
    )
    # 100k / 25k => ceil => 4 volumes (no upper bound).
    assert len(volumes) == 4
    assert len(anchors) == 4 * 3
    assert sum(volume.target_volume_words for volume in volumes) == 100000


def test_macro_compile_notes_links_missing_raises() -> None:
    service = AnchorService()
    with pytest.raises(ValueError):
        service.compile_macro_plan(
            "story_notes_fail",
            StoryInput(
                title="測試 notes_links enforcement",
                premise="角色設定請被嚴格參考。",
                macro_author_notes="角色：Kaelen 的核心動機與致命缺陷；小習慣；關鍵禁忌。",
                target_total_words=45000,
            ),
            FakeStructuredLLMClient(),  # notes_links omitted
        )


def test_macro_compile_notes_links_present_succeeds() -> None:
    service = AnchorService()
    volumes, anchors, cast, b_seed, bible = service.compile_macro_plan(
        "story_notes_ok",
        StoryInput(
            title="測試 notes_links enforcement",
            premise="角色設定請被嚴格參考。",
            macro_author_notes="角色：Kaelen 的核心動機與致命缺陷；小習慣；關鍵禁忌。",
            target_total_words=45000,
        ),
        FakeStructuredLLMClientWithNotesLinks(),
    )
    assert len(volumes) == 3
    assert len(anchors) == 9
    assert len(cast) >= 1
    assert bible.get("story_genre") == "奇幻"
    assert b_seed == []
