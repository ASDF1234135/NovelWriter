from app.domain.schema import NodeMutation, NodeType, StoryInput
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.profile_expander import run_profile_expander


class _FailingLLM:
    def invoke_json(self, prompt, schema, profile):  # noqa: ANN001
        raise RuntimeError("llm timeout")


def _build_context(tmp_path):
    db = SQLiteDatabase(str(tmp_path / "profile_expander.sqlite3"))
    story_repository = StoryRepository(db)
    workflow_repository = WorkflowRepository(db)
    graph_store = InMemoryGraphStore()
    return WorkflowContext(
        story_repository=story_repository,
        workflow_repository=workflow_repository,
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=graph_store,
        vector_store=InMemoryVectorStore(),
        llm_client=_FailingLLM(),
        run_id="run_test",
    )


def test_profile_expander_fallback_does_not_block_on_llm_failure(tmp_path) -> None:
    context = _build_context(tmp_path)
    story = context.story_repository.create_story(
        "story_x",
        StoryInput(title="T", premise="p", bible={}, target_total_words=5000),
    )
    context.graph_store.seed_story(story["story_id"])
    context.graph_store.apply_mutations(
        story["story_id"],
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id="char_existing",
                node_type=NodeType.CHARACTER,
                properties={"canonical_name": "Old", "aliases": [], "description": "old"},
            )
        ],
    )
    state = {
        "story_id": story["story_id"],
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "推進",
        "current_draft": "新角色凱在橋上出現。",
        "pending_chapter_extraction": {
            "entities": [
                {
                    "node_id": "char_kai",
                    "node_type": "CHARACTER",
                    "canonical_name": "凱",
                    "aliases": ["黑衣人"],
                    "summary": "沉默寡言的槍手。",
                }
            ]
        },
    }

    out = run_profile_expander(state, context)
    updates = out.get("pending_cast_updates") or []
    assert len(updates) == 1
    assert updates[0]["update_mode"] == "fill_empty"
    assert updates[0]["member"]["node_id"] == "char_kai"
    assert updates[0]["member"]["personality"] == ""
