from types import SimpleNamespace

from app.domain.schema import GraphRAGEvaluateOutput, VectorDocument
from app.services.graph_store import InMemoryGraphStore
from app.services.vector_store import DeterministicEmbeddingClient, InMemoryVectorStore
from app.services.workflow.nodes.anchor_resolve import run_anchor_resolve


class _StubLLM:
    def __init__(self, output: GraphRAGEvaluateOutput) -> None:
        self.output = output

    def invoke_json(self, prompt: str, response_model, profile):  # noqa: ANN001
        del prompt, response_model, profile
        return self.output, SimpleNamespace(content="{}", token_usage=0, latency_ms=0)


def _base_state() -> dict:
    return {
        "story_id": "story_1",
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
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
    llm_out = GraphRAGEvaluateOutput(
        resolved=False,
        confidence=0.9,
        reasoning="Evidence does not prove completion.",
    )
    vector_store = InMemoryVectorStore(DeterministicEmbeddingClient(64))
    vector_store.add_documents(
        "story_1",
        [VectorDocument(text_chunk="會議上只是提線索，尚未揭露真相。", metadata={"chunk_id": "c1"})],
    )
    context = SimpleNamespace(
        llm_client=_StubLLM(llm_out),
        graph_store=InMemoryGraphStore(),
        vector_store=vector_store,
        output_language="zh-Hant",
    )
    out = run_anchor_resolve(state, context)
    assert out["anchor_hitl_required"] is False
    assert out["anchor_resolution"]["unresolved_anchor_ids"] == ["a1"]
    assert out["anchor_resolution_hitl_candidate"] == {}


def test_anchor_resolve_uncertain_routes_to_hitl() -> None:
    state = _base_state()
    llm_out = GraphRAGEvaluateOutput(
        resolved=False,
        confidence=0.3,
        reasoning="Evidence is ambiguous.",
    )
    context = SimpleNamespace(
        llm_client=_StubLLM(llm_out),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(DeterministicEmbeddingClient(64)),
        output_language="zh-Hant",
    )
    out = run_anchor_resolve(state, context)
    assert out["anchor_hitl_required"] is True
    assert "human" in str(out["anchor_resolution_hitl_candidate"]["decision_reason"]).lower()
