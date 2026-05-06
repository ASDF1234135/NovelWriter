from __future__ import annotations

from dataclasses import dataclass

from app.domain.schema import GraphRAGEvaluateOutput, VectorDocument
from app.services.graph_rag_service import GraphRAGService
from app.services.graph_store import InMemoryGraphStore
from app.services.vector_store import DeterministicEmbeddingClient, InMemoryVectorStore
from app.services.workflow.profiles import AgentPromptProfile


@dataclass
class LLMResultStub:
    content: str
    token_usage: int = 42
    latency_ms: int = 10


class FakeGraphRAGLLM:
    def invoke(self, prompt: str) -> LLMResultStub:  # pragma: no cover
        raise NotImplementedError()

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResultStub:
        return LLMResultStub(content=f"[text:{profile.agent_name}]")

    def invoke_json(self, prompt: str, response_model, profile: AgentPromptProfile):
        payload = {
            "resolved": True,
            "confidence": 0.75,
            "reasoning": "Based on evidence pack facts only.",
        }
        return response_model.model_validate(payload), LLMResultStub(content="")


def test_retrieve_evidence_pack_prunes_empty_fields() -> None:
    graph_store = InMemoryGraphStore()
    vector_store = InMemoryVectorStore(DeterministicEmbeddingClient(64))
    vector_store.add_documents(
        "story_1",
        [
            VectorDocument(
                text_chunk="A witness saw the red scarf.",
                metadata={"chunk_id": "c1", "chapter_id": 1},
            )
        ],
    )
    service = GraphRAGService(graph_store=graph_store, vector_store=vector_store, llm=FakeGraphRAGLLM())

    pack = service._retrieve_evidence_pack(
        "red scarf",
        story_id="story_1",
        active_epoch_id="epoch_present",
        pov_character_id="char_public_observer",
        top_k=5,
        context_hop_tier=2,
    )

    assert "graph" in pack and isinstance(pack["graph"], dict)
    nodes = pack["graph"].get("nodes") or []
    assert nodes, "seed_story should provide at least one node"
    # Empty attributes should be pruned from nodes.
    assert "metadata" not in nodes[0] or nodes[0].get("metadata") != {}
    assert "tags" not in nodes[0] or nodes[0].get("tags") != []


def test_ask_question_returns_text() -> None:
    graph_store = InMemoryGraphStore()
    vector_store = InMemoryVectorStore(DeterministicEmbeddingClient(64))
    service = GraphRAGService(graph_store=graph_store, vector_store=vector_store, llm=FakeGraphRAGLLM())

    out = service.ask_question(
        "Who is the POV?",
        story_id="story_1",
        active_epoch_id="epoch_present",
        pov_character_id="char_public_observer",
    )
    assert out.startswith("[text:graph_rag_ask]")


def test_evaluate_condition_returns_structured_output() -> None:
    graph_store = InMemoryGraphStore()
    vector_store = InMemoryVectorStore(DeterministicEmbeddingClient(64))
    service = GraphRAGService(graph_store=graph_store, vector_store=vector_store, llm=FakeGraphRAGLLM())

    out = service.evaluate_condition(
        "Is the condition satisfied?",
        story_id="story_1",
        active_epoch_id="epoch_present",
        pov_character_id="char_public_observer",
        response_model=GraphRAGEvaluateOutput,
    )
    assert isinstance(out, GraphRAGEvaluateOutput)
    assert out.resolved is True
    assert 0.0 <= out.confidence <= 1.0

