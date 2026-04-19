from app.domain.schema import NodeMutation, NodeType, StoryCastMemberStored, StoryInput
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.graph_rag import run_graph_rag


def test_graph_rag_includes_slim_cast_view_from_cast_json(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "graph_rag.sqlite3"))
    story_repo = StoryRepository(db)
    story = story_repo.create_story(
        "story_cast",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    story_repo.update_story_cast(
        story["story_id"],
        [
            StoryCastMemberStored(
                node_id="char_hero",
                canonical_name="英雄",
                role="protagonist",
                personality="冷靜克制",
                speech_style="短句",
                fatal_flaw="過度自信",
                quirks_and_habits="遇壓力會敲桌面",
            )
        ],
        "char_hero",
    )
    graph_store = InMemoryGraphStore()
    graph_store.seed_story(story["story_id"])
    graph_store.apply_mutations(
        story["story_id"],
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="char_hero",
                node_type=NodeType.CHARACTER,
                properties={"canonical_name": "英雄", "aliases": [], "description": "主角"},
            )
        ],
    )
    context = WorkflowContext(
        story_repository=story_repo,
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=graph_store,
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run_cast_view",
    )
    state = {
        "story_id": story["story_id"],
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_hero",
        "narrative_directive": "推進",
    }

    out = run_graph_rag(state, context)
    slim = out.get("cast_slim_view") or []
    assert slim
    first = slim[0]
    assert first["node_id"] == "char_hero"
    assert first["personality"] == "冷靜克制"
    assert set(first.keys()) == {"node_id", "name", "personality", "speech_style", "fatal_flaw", "habit"}
