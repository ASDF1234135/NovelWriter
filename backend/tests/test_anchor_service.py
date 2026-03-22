import json

from app.domain.schema import (
    MacroCastMember,
    MacroNestedAnchorDraft,
    MacroPlanOutput,
    MacroVolumePlanDraft,
    StoryInput,
)
from app.services.anchor_service import AnchorService
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


def test_anchor_service_can_use_structured_llm_output() -> None:
    service = AnchorService()
    volumes, anchors, cast = service.compile_macro_plan(
        "story_test",
        StoryInput(
            title="王都疑雲",
            premise="被流放的騎士回到王都追查皇室命案。",
            bible={"rules": ["冰系秘術有代價"]},
            target_total_words=45000,
        ),
        FakeStructuredLLMClient(),
    )

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
    assert cast[1].node_id == "story_test_mc_02"


def test_anchor_service_clamps_llm_plan_to_formula_total_chapters() -> None:
    service = AnchorService()
    volumes, anchors, cast = service.compile_macro_plan(
        "story_formula",
        StoryInput(
            title="短篇測試",
            premise="主角在冬夜返城。",
            bible={"rules": ["代價必須支付"]},
            target_total_words=30000,
        ),
        FakeStructuredLLMClient(),
    )

    assert volumes[-1].chapter_end == 12
    assert max(anchor.chapter_target for anchor in anchors) <= 12
    assert sum(volume.target_volume_words for volume in volumes) == 30000
    assert len(anchors) == 9
    assert len(cast) >= 1
    assert any(m.role == "protagonist" for m in cast)
