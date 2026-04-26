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


def _load_json_prompt_first(prompt: str) -> dict:
    """Macro retry appends non-JSON text after the JSON blob; slot prompts are a single JSON object."""
    s = (prompt or "").strip()
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(s)
    if not isinstance(obj, dict):
        msg = "expected JSON object at start of LLM prompt"
        raise TypeError(msg)
    return obj


def _stub_slot_fill_json_responses(data: dict, response_model):
    """Handle fishbone storyline + anchor slot-fill prompts (not macro planner)."""
    task = str(data.get("task", ""))
    if "storyline content slots" in task:
        items = []
        for row in data.get("storylines", []):
            sid = row.get("storyline_id", "x")
            items.append(
                {
                    "storyline_id": sid,
                    "title": f"測試副線 {sid[-6:]}",
                    "overall_goal": "在結構上服務主線並依卷收斂。",
                    "involved_entities": list((data.get("allowed_cast_node_ids") or []))[:2],
                }
            )
        return response_model.model_validate({"items": items})
    if task.startswith("Fill content slots only"):
        items = []
        for row in data.get("nodes", []):
            items.append(
                {
                    "node_id": row["node_id"],
                    "title": f"填槽 {str(row['node_id'])[-10:]}",
                    "description": "測試填寫的節點描述，符合前置依賴與故事線目標。",
                }
            )
        return response_model.model_validate({"items": items})
    return None


class FakeStructuredLLMClient:
    def invoke(self, prompt: str):
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile):
        raise NotImplementedError()

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        stub = _stub_slot_fill_json_responses(data, response_model)
        if stub is not None:
            return stub, type(
                "LLMResultStub",
                (),
                {"content": "", "token_usage": 42, "latency_ms": 15},
            )()
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
        data = _load_json_prompt_first(prompt)
        stub = _stub_slot_fill_json_responses(data, response_model)
        if stub is not None:
            return stub, type(
                "LLMResultStub",
                (),
                {"content": "", "token_usage": 42, "latency_ms": 15},
            )()
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


class FakeStructuredLLMClientRetryLanguage:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, prompt: str):
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile):
        raise NotImplementedError()

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        stub = _stub_slot_fill_json_responses(data, response_model)
        if stub is not None:
            return stub, type(
                "LLMResultStub",
                (),
                {"content": "", "token_usage": 42, "latency_ms": 15},
            )()
        self.calls += 1
        if self.calls == 1:
            output = MacroPlanOutput(
                bible={"story_genre": "fantasy", "writing_style": "clean"},
                cast=[MacroCastMember(canonical_name="Kaelen", role="protagonist", short_bio="exiled knight")],
                volumes=[
                    MacroVolumePlanDraft(
                        title="Volume I",
                        summary="Investigate the royal murder in the capital.",
                        chapter_start=1,
                        chapter_end=4,
                        target_volume_words=10000,
                        anchors=[
                            MacroNestedAnchorDraft(
                                title="Clue appears",
                                description="The first clue points to the palace.",
                                target_state={"step": 1},
                                chapter_target=2,
                                priority=1,
                            ),
                            MacroNestedAnchorDraft(
                                title="Ally joins",
                                description="A court informant joins the investigation.",
                                target_state={"step": 2},
                                chapter_target=3,
                                priority=2,
                            ),
                            MacroNestedAnchorDraft(
                                title="Trap closes",
                                description="The protagonist is framed by the antagonist.",
                                target_state={"step": 3},
                                chapter_target=4,
                                priority=3,
                            ),
                        ],
                    ),
                    MacroVolumePlanDraft(
                        title="Volume II",
                        summary="Counterattack with hidden evidence.",
                        chapter_start=5,
                        chapter_end=8,
                        target_volume_words=10000,
                        anchors=[],
                    ),
                    MacroVolumePlanDraft(
                        title="Volume III",
                        summary="Expose the real mastermind.",
                        chapter_start=9,
                        chapter_end=12,
                        target_volume_words=10000,
                        anchors=[],
                    ),
                ],
            )
        else:
            output = MacroPlanOutput(
                bible={"story_genre": "奇幻", "writing_style": "简洁叙事"},
                cast=[MacroCastMember(canonical_name="凯伦", role="protagonist", short_bio="被流放的骑士。")],
                volumes=[
                    MacroVolumePlanDraft(
                        title="第一卷",
                        summary="主角回到王都追查命案。",
                        chapter_start=1,
                        chapter_end=4,
                        target_volume_words=10000,
                        anchors=[
                            MacroNestedAnchorDraft(
                                title="线索出现",
                                description="第一条线索指向王宫。",
                                target_state={"step": 1},
                                chapter_target=2,
                                priority=1,
                            ),
                            MacroNestedAnchorDraft(
                                title="盟友加入",
                                description="宫廷线人加入调查。",
                                target_state={"step": 2},
                                chapter_target=3,
                                priority=2,
                            ),
                            MacroNestedAnchorDraft(
                                title="陷阱收紧",
                                description="主角被反派栽赃。",
                                target_state={"step": 3},
                                chapter_target=4,
                                priority=3,
                            ),
                        ],
                    ),
                    MacroVolumePlanDraft(
                        title="第二卷",
                        summary="利用隐藏证据反击。",
                        chapter_start=5,
                        chapter_end=8,
                        target_volume_words=10000,
                        anchors=[],
                    ),
                    MacroVolumePlanDraft(
                        title="第三卷",
                        summary="揭露真正幕后黑手。",
                        chapter_start=9,
                        chapter_end=12,
                        target_volume_words=10000,
                        anchors=[],
                    ),
                ],
            )
        return response_model.model_validate(output.model_dump(mode="json")), type(
            "LLMResultStub",
            (),
            {"content": "", "token_usage": 42, "latency_ms": 15},
        )()


class FakeStructuredLLMClientWrongLanguageOnly(FakeStructuredLLMClientRetryLanguage):
    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        stub = _stub_slot_fill_json_responses(data, response_model)
        if stub is not None:
            return stub, type(
                "LLMResultStub",
                (),
                {"content": "", "token_usage": 42, "latency_ms": 15},
            )()
        self.calls += 1
        output = MacroPlanOutput(
            bible={"story_genre": "fantasy", "writing_style": "clean"},
            cast=[MacroCastMember(canonical_name="Kaelen", role="protagonist", short_bio="exiled knight")],
            volumes=[
                MacroVolumePlanDraft(
                    title="Volume I",
                    summary="Investigate the royal murder in the capital.",
                    chapter_start=1,
                    chapter_end=4,
                    target_volume_words=10000,
                    anchors=[],
                ),
                MacroVolumePlanDraft(
                    title="Volume II",
                    summary="Counterattack with hidden evidence.",
                    chapter_start=5,
                    chapter_end=8,
                    target_volume_words=10000,
                    anchors=[],
                ),
                MacroVolumePlanDraft(
                    title="Volume III",
                    summary="Expose the real mastermind.",
                    chapter_start=9,
                    chapter_end=12,
                    target_volume_words=10000,
                    anchors=[],
                ),
            ],
        )
        return response_model.model_validate(output.model_dump(mode="json")), type(
            "LLMResultStub",
            (),
            {"content": "", "token_usage": 42, "latency_ms": 15},
        )()


class FakeStructuredLLMClientRetryTradToSimp:
    """First response: Traditional-heavy macro output; second: Simplified (matches language retry path)."""

    def __init__(self) -> None:
        self.calls = 0
        self._trad = FakeStructuredLLMClient()

    def invoke(self, prompt: str):
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile):
        raise NotImplementedError()

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        stub = _stub_slot_fill_json_responses(data, response_model)
        if stub is not None:
            return stub, type(
                "LLMResultStub",
                (),
                {"content": "", "token_usage": 42, "latency_ms": 15},
            )()
        self.calls += 1
        if self.calls == 1:
            return self._trad.invoke_json(prompt, response_model, profile)
        output = MacroPlanOutput(
            bible={"story_genre": "奇幻", "writing_style": "简洁叙事"},
            cast=[MacroCastMember(canonical_name="凯伦", role="protagonist", short_bio="被流放的骑士。")],
            volumes=[
                MacroVolumePlanDraft(
                    title="第一卷",
                    summary="主角回到王都追查命案。",
                    chapter_start=1,
                    chapter_end=4,
                    target_volume_words=10000,
                    anchors=[
                        MacroNestedAnchorDraft(
                            title="线索出现",
                            description="第一条线索指向王宫。",
                            target_state={"step": 1},
                            chapter_target=2,
                            priority=1,
                        ),
                        MacroNestedAnchorDraft(
                            title="盟友加入",
                            description="宫廷线人加入调查。",
                            target_state={"step": 2},
                            chapter_target=3,
                            priority=2,
                        ),
                        MacroNestedAnchorDraft(
                            title="陷阱收紧",
                            description="主角被反派栽赃。",
                            target_state={"step": 3},
                            chapter_target=4,
                            priority=3,
                        ),
                    ],
                ),
                MacroVolumePlanDraft(
                    title="第二卷",
                    summary="利用隐藏证据反击。",
                    chapter_start=5,
                    chapter_end=8,
                    target_volume_words=10000,
                    anchors=[],
                ),
                MacroVolumePlanDraft(
                    title="第三卷",
                    summary="揭露真正幕后黑手。",
                    chapter_start=9,
                    chapter_end=12,
                    target_volume_words=10000,
                    anchors=[],
                ),
            ],
        )
        return response_model.model_validate(output.model_dump(mode="json")), type(
            "LLMResultStub",
            (),
            {"content": "", "token_usage": 42, "latency_ms": 15},
        )()


class FakeStructuredLLMClientTraditionalOnly:
    def __init__(self) -> None:
        self.calls = 0
        self._trad = FakeStructuredLLMClient()

    def invoke(self, prompt: str):
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile):
        raise NotImplementedError()

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        self.calls += 1
        head = prompt.split("\n\nPrevious output violated", 1)[0].strip()
        return self._trad.invoke_json(head, response_model, profile)


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


def test_normalize_generated_bible_moves_themes_and_dedupes_extra_primary_fields() -> None:
    service = AnchorService()
    story_input = StoryInput(title="t", premise="p", target_total_words=12000)
    output = MacroPlanOutput(
        bible={
            "themes": ["命運", "背叛"],
            "extra": {
                "theme": "should_remove",
                "narrative_pov": "should_remove",
                "writing_style": "should_remove",
                "magic": "low",
            },
        }
    )
    out = service._normalize_generated_bible(story_input, output)
    assert out.get("theme") == ["命運", "背叛"]
    assert "themes" not in out
    assert isinstance(out.get("extra"), dict)
    assert out["extra"] == {"magic": "low"}


def test_macro_prompt_requires_primary_fields_not_in_extra() -> None:
    service = AnchorService()
    prompt = service._build_macro_prompt(
        StoryInput(title="王都疑雲", premise="測試 premise", target_total_words=45000),
        fixed_total_chapters=18,
        fixed_total_volumes=3,
    )
    data = json.loads(prompt)
    requirements = data.get("requirements") or []
    merged = "\n".join(str(x) for x in requirements)
    assert "theme / narrative_pov / writing_style" in merged
    assert "not inside extra" in merged


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
    assert "headcount" in prompt.casefold()


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


def test_macro_compile_english_uses_smaller_chapter_unit_and_volume_scale() -> None:
    """100k words, en: chapter_unit=1800, words_per_volume=18000 -> ceil(100k/18k)=6 volumes."""
    service = AnchorService()
    # Mock path (no structured LLM): validates AnchorService volume/chapter scaling only.
    volumes, anchors, _cast, _b_seed, _bible = service.compile_macro_plan(
        "story_100k_en",
        StoryInput(
            title="Epic",
            premise="Hero returns.",
            target_total_words=100000,
            output_language="en",
        ),
        None,
    )
    assert len(volumes) == 6
    assert len(anchors) == 6 * 3
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


def test_macro_compile_retries_when_output_language_mismatch() -> None:
    service = AnchorService()
    fake_llm = FakeStructuredLLMClientRetryLanguage()
    volumes, anchors, cast, _, _ = service.compile_macro_plan(
        "story_lang_retry",
        StoryInput(
            title="语言重试",
            premise="主角返回王都调查命案。",
            target_total_words=30000,
            output_language="zh-Hans",
        ),
        fake_llm,
    )
    # 2 calls for macro-plan language retry + 1 weave call (when weave succeeds).
    assert fake_llm.calls >= 2
    assert len(volumes) == 3
    assert len(anchors) >= 3
    assert len(cast) >= 1


def test_macro_compile_raises_when_language_mismatch_persists() -> None:
    service = AnchorService()
    fake_llm = FakeStructuredLLMClientWrongLanguageOnly()
    with pytest.raises(ValueError, match="output language mismatch"):
        service.compile_macro_plan(
            "story_lang_fail",
            StoryInput(
                title="语言失败",
                premise="主角返回王都调查命案。",
                target_total_words=30000,
                output_language="zh-Hans",
            ),
            fake_llm,
        )


def test_macro_prompt_includes_zh_script_shape_requirements() -> None:
    service = AnchorService()
    prompt_hans = service._build_macro_prompt(
        StoryInput(title="t", premise="p", target_total_words=45000, output_language="zh-Hans"),
        fixed_total_chapters=18,
        fixed_total_volumes=3,
    )
    assert "大陆规范简体" in prompt_hans
    prompt_hant = service._build_macro_prompt(
        StoryInput(title="t", premise="p", target_total_words=45000, output_language="zh-Hant"),
        fixed_total_chapters=18,
        fixed_total_volumes=3,
    )
    assert "繁體中文" in prompt_hant


def test_zh_hans_traditional_heuristic() -> None:
    svc = AnchorService()
    tc_blob = "這與國時會說對從種經長門卷內章節點敘述稱線索邊境壓力與審判" * 8
    cjk_tc, _ = svc._script_letter_counts(tc_blob)
    assert cjk_tc >= 28
    assert svc._zh_hans_traditional_script_mismatch(tc_blob, cjk_tc) is not None
    sc_blob = "这与国时说对从种经长门卷内章节点叙述称线索边境压力与审判" * 8
    cjk_sc, _ = svc._script_letter_counts(sc_blob)
    assert svc._zh_hans_traditional_script_mismatch(sc_blob, cjk_sc) is None


def test_macro_compile_retries_when_zh_hans_macro_output_is_traditional() -> None:
    service = AnchorService()
    fake_llm = FakeStructuredLLMClientRetryTradToSimp()
    volumes, anchors, _, _, bible = service.compile_macro_plan(
        "story_trad_retry",
        StoryInput(
            title="王都疑云",
            premise="主角返回王都调查命案。",
            target_total_words=30000,
            output_language="zh-Hans",
        ),
        fake_llm,
    )
    # 2 calls for macro-plan language retry + optional weave call.
    assert fake_llm.calls >= 2
    assert len(volumes) == 3
    assert bible.get("story_genre") == "奇幻"


def test_macro_compile_raises_when_zh_hans_macro_stays_traditional() -> None:
    service = AnchorService()
    fake_llm = FakeStructuredLLMClientTraditionalOnly()
    with pytest.raises(ValueError, match="output language mismatch"):
        service.compile_macro_plan(
            "story_trad_fail",
            StoryInput(
                title="王都疑云",
                premise="主角返回王都调查命案。",
                target_total_words=30000,
                output_language="zh-Hans",
            ),
            fake_llm,
        )
    assert fake_llm.calls == 2


def test_fishbone_topology_is_deterministic_and_acyclic() -> None:
    service = AnchorService()
    _, _, _, _, bible_a = service.compile_macro_plan(
        "story_fishbone_det",
        StoryInput(
            title="Deterministic Test",
            premise="Test deterministic fishbone topology.",
            target_total_words=60000,
        ),
        FakeStructuredLLMClient(),
    )
    _, _, _, _, bible_b = service.compile_macro_plan(
        "story_fishbone_det",
        StoryInput(
            title="Deterministic Test",
            premise="Test deterministic fishbone topology.",
            target_total_words=60000,
        ),
        FakeStructuredLLMClient(),
    )
    assert bible_a.get("anchor_nodes") == bible_b.get("anchor_nodes")


def test_fishbone_mainline_links_first_node_to_previous_volume_last_main() -> None:
    """Each volume's first MAIN spine node must depend on the previous volume's last MAIN node."""
    service = AnchorService()
    volumes, _, _, _, bible = service.compile_macro_plan(
        "story_cross_vol_spine",
        StoryInput(
            title="Cross-volume spine",
            premise="Ensure fishbone main spine is continuous across volumes.",
            target_total_words=60000,
        ),
        FakeStructuredLLMClient(),
    )
    storylines = bible.get("storylines") or []
    main_sid = next((str(s["id"]) for s in storylines if str(s.get("type")) == "MAIN"), "")
    assert main_sid
    vol_ids = [v.volume_id for v in volumes]
    assert len(vol_ids) >= 2

    anchor_nodes = bible.get("anchor_nodes") or []
    by_volume: dict[str, list[dict]] = {vid: [] for vid in vol_ids}
    for n in anchor_nodes:
        if str(n.get("node_kind")) != "NORMAL":
            continue
        sids = [str(x) for x in (n.get("storyline_ids") or [])]
        if main_sid not in sids:
            continue
        vid = str(n.get("volume_id") or "")
        if vid in by_volume:
            by_volume[vid].append(n)

    for i in range(1, len(vol_ids)):
        prev_vid, cur_vid = vol_ids[i - 1], vol_ids[i]
        prev_mains = by_volume.get(prev_vid, [])
        cur_mains = by_volume.get(cur_vid, [])
        if not prev_mains or not cur_mains:
            continue
        last_prev_id = str(prev_mains[-1].get("id"))
        first_cur = cur_mains[0]
        deps = [str(x) for x in (first_cur.get("depends_on") or [])]
        assert last_prev_id in deps, f"{cur_vid} first main should depend on {last_prev_id}, got {deps}"


def test_fishbone_no_cross_subline_dependencies() -> None:
    service = AnchorService()
    _, _, _, _, bible = service.compile_macro_plan(
        "story_fishbone_guard",
        StoryInput(
            title="Fishbone Guard",
            premise="Sub-lines should not cross depend each other.",
            target_total_words=50000,
        ),
        FakeStructuredLLMClient(),
    )
    storylines = bible.get("storylines") or []
    anchor_nodes = bible.get("anchor_nodes") or []
    type_by_sid = {str(s.get("id")): str(s.get("type")) for s in storylines}
    by_id = {str(n.get("id")): n for n in anchor_nodes}
    side_types = {"S_TIER", "A_TIER", "B_TIER"}
    for node in anchor_nodes:
        own_ids = [str(x) for x in (node.get("storyline_ids") or [])]
        own_side = any(type_by_sid.get(sid) in side_types for sid in own_ids)
        if not own_side:
            continue
        for dep in node.get("depends_on") or []:
            dep_node = by_id.get(str(dep))
            if not dep_node:
                continue
            dep_ids = [str(x) for x in (dep_node.get("storyline_ids") or [])]
            dep_side = any(type_by_sid.get(sid) in side_types for sid in dep_ids)
            if dep_side:
                assert set(own_ids).intersection(set(dep_ids))


def test_stage3_slot_fill_retry_metric_present() -> None:
    service = AnchorService()
    _, _, _, _, bible = service.compile_macro_plan(
        "story_slot_metric",
        StoryInput(
            title="Slot Metrics",
            premise="Ensure slot fill metrics are visible for observability.",
            target_total_words=30000,
        ),
        FakeStructuredLLMClient(),
    )
    debug = bible.get("llm_weave_debug") or {}
    assert debug.get("topology_mode") == "fixed_fishbone"
    assert "slot_fill_retries" in debug


def test_storyline_slot_fill_runs_before_anchor_slot_fill() -> None:
    service = AnchorService()
    _, _, _, _, bible = service.compile_macro_plan(
        "storyline_first",
        StoryInput(
            title="Order",
            premise="副線先、節點後。",
            target_total_words=30000,
        ),
        FakeStructuredLLMClient(),
    )
    debug = bible.get("llm_weave_debug") or {}
    assert debug.get("storyline_slot_fill_skipped") is False
    storylines = bible.get("storylines") or []
    assert any("測試副線" in str(s.get("title", "")) for s in storylines)
    assert "narrative_context" in service._slot_fill_prompt(
        story_input=StoryInput(title="t", premise="p", target_total_words=12000),
        stage_label="stage3.1_mainline",
        node_rows=[{"node_id": "n1", "title": "a", "description": "b"}],
        narrative_context={"storylines": [], "bible_excerpt": "{}", "volumes": [], "cast": []},
    )


def test_stage3_slot_fill_prompt_contains_fishbone_hard_rules() -> None:
    service = AnchorService()
    prompt = service._slot_fill_prompt(
        story_input=StoryInput(
            title="Rule Prompt",
            premise="check rules",
            target_total_words=30000,
        ),
        stage_label="stage3.3_side_arcs",
        node_rows=[{"node_id": "n1", "title": "", "description": ""}],
        context_summary="ctx",
    )
    assert "No spoilers and no repetition" in prompt
    assert "must strictly match the spatiotemporal context" in prompt
    assert "No deterministic breakthrough ahead of mainline schedule" in prompt
