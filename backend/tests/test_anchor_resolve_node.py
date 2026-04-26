from types import SimpleNamespace

from app.domain.schema import AnchorResolutionOutput
from app.services.workflow.nodes.anchor_resolve import run_anchor_resolve


class _StubLLM:
    def __init__(self, output: AnchorResolutionOutput) -> None:
        self.output = output

    def invoke_json(self, prompt: str, response_model, profile):  # noqa: ANN001
        del prompt, response_model, profile
        return self.output, SimpleNamespace(content="{}", token_usage=0, latency_ms=0)


def _base_state() -> dict:
    return {
        "current_draft": "主角在會議上只提了前置線索，沒有真正達成錨點事件。",
        "anchor_nodes": [
            {
                "id": "a1",
                "title": "公開揭露",
                "description": "主角必須在本章公開揭露真相",
                "depends_on": [],
                "node_kind": "NORMAL",
                "status": "UNLOCKED",
            }
        ],
        "selected_anchor_ids": ["a1"],
        "resolved_anchors": [],
    }


def test_anchor_resolve_confident_mismatch_does_not_trigger_hitl() -> None:
    state = _base_state()
    llm_out = AnchorResolutionOutput(
        resolution_analysis="The draft does not complete this anchor, and the textual evidence is unambiguous.",
        resolved_anchor_ids=[],
        unresolved_anchor_ids=["a1"],
        chapter_matches_plan=False,
        evidence_summary=[{"anchor_id": "a1", "decision": "UNRESOLVED"}],
        decision_reason="Anchor is clearly unresolved and does not require human adjudication.",
        resolver_confidence=0.9,
        requires_human_review=False,
    )
    context = SimpleNamespace(llm_client=_StubLLM(llm_out), output_language="zh-Hant")
    out = run_anchor_resolve(state, context)
    assert out["anchor_hitl_required"] is False
    assert out["anchor_resolution"]["unresolved_anchor_ids"] == ["a1"]
    assert out["anchor_resolution_hitl_candidate"] == {}


def test_anchor_resolve_uncertain_routes_to_hitl() -> None:
    state = _base_state()
    llm_out = AnchorResolutionOutput(
        resolution_analysis="Signals in the chapter are contradictory, so the resolver cannot confidently judge completion.",
        resolved_anchor_ids=[],
        unresolved_anchor_ids=["a1"],
        chapter_matches_plan=False,
        evidence_summary=[{"anchor_id": "a1", "decision": "UNRESOLVED"}],
        decision_reason="Evidence remains ambiguous and requires a human decision.",
        resolver_confidence=0.3,
        requires_human_review=True,
    )
    context = SimpleNamespace(llm_client=_StubLLM(llm_out), output_language="zh-Hant")
    out = run_anchor_resolve(state, context)
    assert out["anchor_hitl_required"] is True
    assert out["anchor_resolution_hitl_candidate"]["decision_reason"] == "Evidence remains ambiguous and requires a human decision."
