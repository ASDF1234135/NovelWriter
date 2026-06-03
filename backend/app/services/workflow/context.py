from __future__ import annotations

from dataclasses import dataclass

from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_rag_service import GraphRAGService
from app.services.graph_store import GraphStore
from app.services.llm import LLMClient
from app.services.vector_store import VectorStore


@dataclass
class WorkflowContext:
    story_repository: StoryRepository
    workflow_repository: WorkflowRepository
    bible_service: BibleService
    anchor_service: AnchorService
    graph_store: GraphStore
    vector_store: VectorStore
    llm_client: LLMClient
    run_id: str
    """BCP-47 style story setting: en | zh-Hant | zh-Hans."""
    output_language: str = "zh-Hant"
    graph_rag_service: GraphRAGService | None = None
