import json
import pytest

from app.domain.schema import (
    AnchorNode,
    MacroCastMember,
    MacroNestedAnchorDraft,
    MacroPlanOutput,
    MacroVolumePlanDraft,
    StoryCastSeedEntry,
    StoryInput,
    VolumePlan,
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
        out = {"items": items, "batch_summary": "stub batch recap for tests"}
        return response_model.model_validate(out)
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


class RecordingFakeStructuredLLMClient(FakeStructuredLLMClient):
    def __init__(self) -> None:
        self.json_prompts: list[dict] = []

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        self.json_prompts.append(data)
        return super().invoke_json(prompt, response_model, profile)


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
    lore = str(out.get("general_world_lore") or "")
    assert "命運" in lore or "背叛" in lore
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
    assert "general_world_lore" in merged
    assert "not duplicate general_world_lore" in merged


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


def test_fishbone_s_tier_cross_volume_start_depends_on_previous_s_tail_and_checkpoint() -> None:
    service = AnchorService()
    volumes, _, _, _, bible = service.compile_macro_plan(
        "story_cross_vol_s_tier",
        StoryInput(
            title="Cross-volume S tier",
            premise="S-tier lines should bridge through volume checkpoints.",
            target_total_words=60000,
        ),
        FakeStructuredLLMClient(),
    )
    storylines = bible.get("storylines") or []
    anchor_nodes = bible.get("anchor_nodes") or []
    s_ids = [str(s.get("id")) for s in storylines if str(s.get("type")) == "S_TIER"]
    vol_ids = [v.volume_id for v in volumes]
    assert s_ids
    assert len(vol_ids) >= 2

    for sid in s_ids:
        by_volume: dict[str, list[dict]] = {vid: [] for vid in vol_ids}
        for node in anchor_nodes:
            if sid not in [str(x) for x in (node.get("storyline_ids") or [])]:
                continue
            if str(node.get("node_kind") or "").upper() != "NORMAL":
                continue
            vid = str(node.get("volume_id") or "")
            if vid in by_volume:
                by_volume[vid].append(node)

        for i in range(1, len(vol_ids)):
            prev_vid, cur_vid = vol_ids[i - 1], vol_ids[i]
            prev_nodes = by_volume.get(prev_vid, [])
            cur_nodes = by_volume.get(cur_vid, [])
            if not prev_nodes or not cur_nodes:
                continue
            deps = {str(x) for x in (cur_nodes[0].get("depends_on") or [])}
            prev_s_tail = str(prev_nodes[-1].get("id"))
            prev_checkpoint = f"{prev_vid}_checkpoint"
            assert prev_s_tail in deps, f"{cur_nodes[0].get('id')} should depend on {prev_s_tail}, got {deps}"
            assert prev_checkpoint in deps, f"{cur_nodes[0].get('id')} should depend on {prev_checkpoint}, got {deps}"


def test_fishbone_checkpoint_depends_on_storyline_tails_only() -> None:
    service = AnchorService()
    _, volumes, _, _, bible = service.compile_macro_plan(
        "story_fishbone_checkpoint_tail",
        StoryInput(
            title="Fishbone checkpoint tails",
            premise="Checkpoint should depend on nearest tail per storyline.",
            target_total_words=60000,
        ),
        FakeStructuredLLMClient(),
    )
    storylines = bible.get("storylines") or []
    anchor_nodes = bible.get("anchor_nodes") or []
    assert anchor_nodes
    type_by_sid = {str(s.get("id")): str(s.get("type")) for s in storylines}
    main_sid = next((sid for sid, stype in type_by_sid.items() if stype == "MAIN"), "")
    by_id = {str(n.get("id")): n for n in anchor_nodes}
    children: dict[str, list[str]] = {nid: [] for nid in by_id}
    for node in anchor_nodes:
        nid = str(node.get("id") or "")
        for dep in node.get("depends_on") or []:
            dep_id = str(dep)
            if dep_id in children:
                children[dep_id].append(nid)

    def _tail_for_storyline(volume_id: str, storyline_id: str) -> str | None:
        scoped = [
            n
            for n in anchor_nodes
            if str(n.get("volume_id") or "") == volume_id
            and storyline_id in [str(x) for x in (n.get("storyline_ids") or [])]
            and str(n.get("node_kind") or "").upper() not in {"CHECKPOINT", "ENDING"}
        ]
        if not scoped:
            return None
        scoped_ids = {str(n.get("id")) for n in scoped}
        tails = []
        for row in scoped:
            rid = str(row.get("id") or "")
            downstream_same_storyline = False
            for child_id in children.get(rid, []):
                child = by_id.get(child_id) or {}
                child_storyline_ids = [str(x) for x in (child.get("storyline_ids") or [])]
                if child_id in scoped_ids and storyline_id in child_storyline_ids:
                    downstream_same_storyline = True
                    break
            if not downstream_same_storyline:
                tails.append(rid)
        return sorted(tails or [str(n.get("id")) for n in scoped])[-1]

    volume_ids = {v.volume_id for v in volumes}
    checkpoints = [
        n
        for n in anchor_nodes
        if str(n.get("node_kind") or "").upper() == "CHECKPOINT" and str(n.get("volume_id") or "") in volume_ids
    ]
    assert checkpoints
    for cp in checkpoints:
        cp_deps = {str(x) for x in (cp.get("depends_on") or [])}
        volume_id = str(cp.get("volume_id") or "")
        if main_sid:
            main_tail = _tail_for_storyline(volume_id, main_sid)
            assert main_tail and main_tail in cp_deps
        for sid, stype in type_by_sid.items():
            if stype not in {"S_TIER", "A_TIER"}:
                continue
            tail = _tail_for_storyline(volume_id, sid)
            if not tail:
                continue
            assert tail in cp_deps
            same_storyline_nodes = [
                str(n.get("id"))
                for n in anchor_nodes
                if str(n.get("volume_id") or "") == volume_id
                and sid in [str(x) for x in (n.get("storyline_ids") or [])]
                and str(n.get("node_kind") or "").upper() not in {"CHECKPOINT", "ENDING"}
            ]
            non_tails = [nid for nid in same_storyline_nodes if nid != tail]
            for nid in non_tails:
                assert nid not in cp_deps


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


class RecordingFakeStructuredLLMClientWithNotesLinks(FakeStructuredLLMClientWithNotesLinks):
    """Records prompts like `RecordingFakeStructuredLLMClient` but echoes back
    cast/anchor `notes_links`, which the macro pipeline enforces when
    `macro_author_notes` carries any extracted keypoints (e.g. our `[[SUBPLOTS]]`
    test inputs)."""

    def __init__(self) -> None:
        super().__init__()
        self.json_prompts: list[dict] = []

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        data = _load_json_prompt_first(prompt)
        self.json_prompts.append(data)
        return super().invoke_json(prompt, response_model, profile)


def test_storyline_slot_fill_threads_user_hints_to_matching_rows() -> None:
    """When `[[SUBPLOTS]]` pins A/B rows to a volume, the slot-fill prompt must
    attach the user's title/goal to the storyline targeting that volume and
    flip in the refine-vs-fresh rule. Storylines without a hint must NOT carry
    `user_hint`, so they keep the original auto-generation path."""
    rec = RecordingFakeStructuredLLMClientWithNotesLinks()
    service = AnchorService()
    notes = (
        "[[SUBPLOTS]]\n"
        "[S]｜羈絆守護者｜揭露童年友人真實身份\n"
        "[A:2]｜王城密謀｜宰相秘密的部署\n"
        "[B:1]｜市井傳聞｜流言扩散\n"
    )
    service.compile_macro_plan(
        "story_storyline_hint",
        StoryInput(
            title="王都疑雲",
            premise="副線綁卷測試。",
            target_total_words=45000,
            macro_author_notes=notes,
        ),
        rec,
    )

    storyline_prompts = [
        p
        for p in rec.json_prompts
        if "storyline content slots" in str(p.get("task", ""))
    ]
    assert storyline_prompts, "no storyline slot-fill prompt captured"
    payload = storyline_prompts[0]

    storyline_rows = payload.get("storylines") or []
    by_id = {row["storyline_id"]: row for row in storyline_rows}

    # S_TIER consumes the [S] hint in source order.
    s_row = next(
        (row for sid, row in by_id.items() if sid.endswith("_s_tier_01")),
        None,
    )
    assert s_row and s_row.get("user_hint", {}).get("title") == "羈絆守護者"

    # A_TIER for volume 2 picks up the [A:2] hint.
    a_v02 = next(
        (row for sid, row in by_id.items() if "_a_tier_v02_01" in sid),
        None,
    )
    assert a_v02 and a_v02.get("user_hint", {}).get("title") == "王城密謀"
    assert a_v02.get("user_hint", {}).get("volume") == 2
    assert a_v02.get("volume_id"), "A_TIER row must surface its volume_id"

    # A_TIER for volume 1 (no [A:1] hint) must NOT carry a user_hint —
    # storylines without a hint keep the original auto-generation path.
    a_v01 = next(
        (row for sid, row in by_id.items() if "_a_tier_v01_01" in sid),
        None,
    )
    assert a_v01 is not None
    assert "user_hint" not in a_v01

    # B_TIER pinned to volume 1 surfaces the [B:1] hint AND a volume_id binding.
    b_hint_row = next(
        (
            row
            for row in storyline_rows
            if row.get("type") == "B_TIER" and row.get("user_hint", {}).get("title") == "市井傳聞"
        ),
        None,
    )
    assert b_hint_row is not None
    assert b_hint_row.get("user_hint", {}).get("volume") == 1
    assert b_hint_row.get("volume_id"), "pinned B_TIER row must carry a volume_id"

    # Refine-vs-fresh rule is present because at least one row has user_hint.
    joined_rules = "\n".join(str(x) for x in (payload.get("rules") or []))
    assert "user_hint" in joined_rules
    assert "Rows without `user_hint`" in joined_rules


def test_storyline_slot_fill_skips_refine_rule_when_no_user_hints() -> None:
    rec = RecordingFakeStructuredLLMClient()
    service = AnchorService()
    service.compile_macro_plan(
        "story_no_hints",
        StoryInput(
            title="No Hints",
            premise="legacy 沒有支線輸入。",
            target_total_words=30000,
        ),
        rec,
    )
    storyline_prompts = [
        p for p in rec.json_prompts if "storyline content slots" in str(p.get("task", ""))
    ]
    assert storyline_prompts
    payload = storyline_prompts[0]
    for row in payload.get("storylines") or []:
        assert "user_hint" not in row
    joined_rules = "\n".join(str(x) for x in (payload.get("rules") or []))
    assert "Rows without `user_hint`" not in joined_rules


def test_fishbone_bumps_a_tier_count_for_user_pinned_volume() -> None:
    """User pinning 3 [A:2] hints must force volume 2 to host >=3 A_TIER lines."""
    service = AnchorService()
    notes = (
        "[[SUBPLOTS]]\n"
        "[A:2]｜密謀一｜部署A\n"
        "[A:2]｜密謀二｜部署B\n"
        "[A:2]｜密謀三｜部署C\n"
    )
    _, _, _, _, bible = service.compile_macro_plan(
        "story_a_bump",
        StoryInput(
            title="A bump",
            premise="user demands many A lines in one volume.",
            target_total_words=45000,
            macro_author_notes=notes,
        ),
        FakeStructuredLLMClientWithNotesLinks(),
    )
    storylines = bible.get("storylines") or []
    a_vol2 = [
        s
        for s in storylines
        if s.get("type") == "A_TIER" and "_a_tier_v02_" in str(s.get("id", ""))
    ]
    assert len(a_vol2) >= 3


def test_fishbone_pins_b_tier_storyline_to_user_requested_volume() -> None:
    """`[B:3]` must produce at least one B_TIER storyline whose anchor nodes live in volume 3."""
    service = AnchorService()
    notes = "[[SUBPLOTS]]\n[B:3]｜市井傳聞｜流言扩散\n"
    _, _, _, _, bible = service.compile_macro_plan(
        "story_b_pin",
        StoryInput(
            title="B pin",
            premise="user pins a B_TIER subplot to volume 3.",
            target_total_words=45000,
            macro_author_notes=notes,
        ),
        FakeStructuredLLMClientWithNotesLinks(),
    )
    anchor_nodes = bible.get("anchor_nodes") or []
    # Volume layout in FakeStructuredLLMClient is "story_<id>_vol1/2/3".
    target_volume_id = "story_b_pin_vol3"
    pinned_b_nodes = [
        n
        for n in anchor_nodes
        if any("_b_tier_" in sid for sid in (n.get("storyline_ids") or []))
        and n.get("volume_id") == target_volume_id
    ]
    assert pinned_b_nodes, f"expected at least one B_TIER node mounted in {target_volume_id}"


def test_stage3_slot_fill_prompt_contains_fishbone_hard_rules() -> None:
    service = AnchorService()
    # Side-arc rules now live in `extra_rules`; the base_rules keep
    # topology/spatiotemporal/no-breakthrough invariants for every branch.
    prompt = service._slot_fill_prompt(
        story_input=StoryInput(
            title="Rule Prompt",
            premise="check rules",
            target_total_words=30000,
        ),
        stage_label="stage3.3_side_arcs",
        node_rows=[{"node_id": "n1", "title": "", "description": ""}],
        context_summary="ctx",
        extra_rules=[
            "S_TIER is a book-spanning important side arc (identity mystery, long-term growth) and must serve the mainline.",
            "A_TIER is a volume-scoped side arc (e.g., key item/ability acquisition) and must serve this volume mainline.",
            "B_TIER is a short side beat for texture and character charm, never a decisive plotline.",
            "No spoilers and no repetition: side-arc content must not duplicate mainline events.",
        ],
    )
    assert "No spoilers and no repetition" in prompt
    assert "must strictly match the spatiotemporal context" in prompt
    assert "No deterministic breakthrough ahead of mainline schedule" in prompt


def test_mainline_second_batch_prompt_has_prior_summaries() -> None:
    rec = RecordingFakeStructuredLLMClient()
    service = AnchorService()
    service.compile_macro_plan(
        "story_prior_sum_accum",
        StoryInput(title="BatchPrompt", premise="accumulate prior summaries.", target_total_words=30000),
        rec,
    )
    main_prompts = [p for p in rec.json_prompts if str(p.get("stage", "")).startswith("stage3.1_mainline.batch")]
    assert len(main_prompts) >= 2
    assert main_prompts[0]["prior_main_batch_summaries"] == []
    assert len(main_prompts[1]["prior_main_batch_summaries"]) == 1
    assert main_prompts[1]["prior_main_batch_summaries"][0].get("summary")


def test_side_prompt_has_main_batch_summaries_and_attachment_context() -> None:
    rec = RecordingFakeStructuredLLMClient()
    service = AnchorService()
    service.compile_macro_plan(
        "story_side_ctx_prompt",
        StoryInput(title="SideCtx", premise="side attachment context.", target_total_words=30000),
        rec,
    )
    side_prompts = [
        p
        for p in rec.json_prompts
        if str(p.get("stage") or "").startswith("stage3.3_side_arcs")
    ]
    assert side_prompts
    for sp in side_prompts:
        assert sp.get("main_batch_summaries")
        for row in sp.get("nodes") or []:
            ac = row.get("attachment_context")
            assert ac is not None
            assert "spine_windows" in ac
            assert "main_spine_mount_nodes" in ac


def test_side_attachment_spine_window_three_or_fallback_one() -> None:
    service = AnchorService()
    mains = [
        AnchorNode(id="m0", storyline_ids=["t_main"], volume_id="v1", title="M0", description="d0"),
        AnchorNode(id="m1", storyline_ids=["t_main"], volume_id="v1", title="M1", description="d1"),
        AnchorNode(id="m2", storyline_ids=["t_main"], volume_id="v1", title="M2", description="d2"),
    ]
    by_id = {n.id: n for n in mains}
    vol = VolumePlan(
        volume_id="v1",
        title="",
        summary="",
        chapter_start=1,
        chapter_end=5,
    )
    spine = AnchorService._main_spine_sequence(mains, [vol])
    side_hi = AnchorNode(
        id="s_hi",
        storyline_ids=["t_s"],
        volume_id="v1",
        title="",
        description="",
        depends_on=["m2"],
    )
    ctx_hi = service._build_side_attachment_context(
        side_hi,
        by_id=by_id,
        main_node_ids={"m0", "m1", "m2"},
        main_spine_sequence=spine,
    )
    assert ctx_hi["spine_windows"][0]["window_node_ids"] == ["m0", "m1", "m2"]

    side_lo = AnchorNode(
        id="s_lo",
        storyline_ids=["t_s"],
        volume_id="v1",
        title="",
        description="",
        depends_on=["m0"],
    )
    ctx_lo = service._build_side_attachment_context(
        side_lo,
        by_id=by_id,
        main_node_ids={"m0", "m1", "m2"},
        main_spine_sequence=spine,
    )
    assert ctx_lo["spine_windows"][0]["window_node_ids"] == ["m0"]


def test_mainline_slot_fill_prompt_isolates_storylines_from_side_arcs() -> None:
    """Mainline anchor slot-fill batches must:

    * see only `type == MAIN` rows inside `narrative_context.storylines`
    * include the mainline-only rule forbidding side-arc material
    * not surface any user-supplied side-arc title (e.g. `[A:2]｜王城密謀｜…`)

    Side batches (`stage3.3_side_arcs.*`) must keep the full storyline view
    and carry the side-tier descriptor rules.
    """
    rec = RecordingFakeStructuredLLMClientWithNotesLinks()
    service = AnchorService()
    notes = (
        "[[SUBPLOTS]]\n"
        "[S]｜羈絆守護者｜揭露童年友人真實身份\n"
        "[A:2]｜王城密謀｜宰相秘密的部署\n"
        "[B:1]｜市井傳聞｜流言扩散\n"
    )
    service.compile_macro_plan(
        "story_mainline_isolation",
        StoryInput(
            title="王都疑雲",
            premise="主線必須對副線內容保密。",
            target_total_words=45000,
            macro_author_notes=notes,
        ),
        rec,
    )

    mainline_prompts = [
        p
        for p in rec.json_prompts
        if str(p.get("stage", "")).startswith("stage3.1_mainline.batch")
    ]
    assert mainline_prompts, "no mainline anchor slot-fill prompts captured"

    for payload in mainline_prompts:
        storylines = (payload.get("narrative_context") or {}).get("storylines") or []
        assert storylines, "mainline prompt narrative_context must include MAIN storyline"
        for row in storylines:
            assert row.get("type") == "MAIN", (
                f"mainline narrative_context leaked non-MAIN storyline: {row}"
            )

        rules = [str(r) for r in (payload.get("rules") or [])]
        joined = "\n".join(rules)
        assert "MAIN spine anchors only" in joined
        assert "filtered to MAIN-tier only" in joined
        assert "out of scope" in joined or "out-of-scope" in joined
        # Side-tier descriptor rules must NOT appear in mainline prompts.
        assert "A_TIER is a volume-scoped side arc" not in joined
        assert "B_TIER is a short side beat" not in joined
        assert "S_TIER is a book-spanning important side arc" not in joined
        assert "side-arc content must not duplicate mainline events" not in joined

        # The wizard's side-arc title must not leak into the mainline prompt at all.
        raw = json.dumps(payload, ensure_ascii=False)
        assert "王城密謀" not in raw, (
            "mainline anchor slot-fill prompt leaked user-supplied side-arc title"
        )
        assert "羈絆守護者" not in raw
        assert "市井傳聞" not in raw

    side_prompts = [
        p
        for p in rec.json_prompts
        if str(p.get("stage", "")).startswith("stage3.3_side_arcs")
    ]
    assert side_prompts, "no side-arc anchor slot-fill prompts captured"

    for payload in side_prompts:
        storylines = (payload.get("narrative_context") or {}).get("storylines") or []
        types_present = {row.get("type") for row in storylines}
        # Side batches must keep the full storyline view (MAIN + side tiers).
        assert "MAIN" in types_present
        assert types_present & {"S_TIER", "A_TIER", "B_TIER"}, (
            "side prompt narrative_context missing side-tier storylines"
        )

        joined = "\n".join(str(r) for r in (payload.get("rules") or []))
        assert "A_TIER is a volume-scoped side arc" in joined
        assert "B_TIER is a short side beat" in joined
        assert "side-arc content must not duplicate mainline events" in joined
        # Side branch must not be told it's "MAIN spine anchors only".
        assert "MAIN spine anchors only" not in joined
