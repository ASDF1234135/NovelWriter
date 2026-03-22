from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from app.domain.schema import (
    HitlDecisionRequest,
    HitlDraftEditRequest,
    HitlOutlineEditRequest,
    HitlStateInjectionRequest,
    NodeMutation,
    NodeType,
    StateTransactionStatus,
    StateUpdaterOutput,
    StoryInput,
)
from app.domain.state import build_initial_state
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import GraphStore
from app.services.llm import LLMClient
from app.services.vector_store import VectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.graph import build_chapter_graph


class HitlNotWaitingError(ValueError):
    """Raised when a HITL action is submitted but the run is not paused for HITL."""


def _assert_hitl_waiting(state: dict) -> None:
    if state.get("workflow_status") != "WAITING_HITL" or not state.get("requires_hitl"):
        raise HitlNotWaitingError("This run is not waiting for human review (expected WAITING_HITL + requires_hitl).")


class WorkflowService:
    def __init__(
        self,
        story_repository: StoryRepository,
        workflow_repository: WorkflowRepository,
        bible_service: BibleService,
        anchor_service: AnchorService,
        graph_store: GraphStore,
        vector_store: VectorStore,
        llm_client: LLMClient,
    ) -> None:
        self.story_repository = story_repository
        self.workflow_repository = workflow_repository
        self.bible_service = bible_service
        self.anchor_service = anchor_service
        self.graph_store = graph_store
        self.vector_store = vector_store
        self.llm_client = llm_client

    def _build_context(self, run_id: str) -> WorkflowContext:
        return WorkflowContext(
            story_repository=self.story_repository,
            workflow_repository=self.workflow_repository,
            bible_service=self.bible_service,
            anchor_service=self.anchor_service,
            graph_store=self.graph_store,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
            run_id=run_id,
        )

    def _execute_workflow(self, run_id: str, state: dict) -> dict:
        context = self._build_context(run_id)
        graph = build_chapter_graph(context)
        final_state = graph.invoke(state)
        self.workflow_repository.update_run(run_id, final_state)
        return final_state

    def create_story(self, story_input: StoryInput) -> dict:
        story_id = f"story_{uuid4().hex[:10]}"
        story = self.story_repository.create_story(story_id, story_input)
        self.graph_store.seed_story(story_id)
        return story

    def macro_compile(self, story_id: str) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        story_input = StoryInput(
            title=story["title"],
            premise=story["premise"],
            bible=story["bible_json"],
            target_total_words=story["target_total_words"],
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
        )
        volumes, anchors, cast = self.anchor_service.compile_macro_plan(story_id, story_input, self.llm_client)
        self.story_repository.store_volumes(story_id, volumes)
        self.story_repository.store_anchors(story_id, anchors)
        protagonist_id = next((c.node_id for c in cast if c.role == "protagonist"), "")
        self.story_repository.update_story_cast(story_id, cast, protagonist_id)
        self.graph_store.clear_macro_cast_characters(story_id)
        cast_mutations = [
            NodeMutation(
                action="CREATE_NODE",
                node_id=member.node_id,
                node_type=NodeType.CHARACTER,
                properties={
                    "canonical_name": member.canonical_name,
                    "description": member.short_bio or member.canonical_name,
                    "aliases": member.aliases,
                    "is_alive": True,
                },
            )
            for member in cast
        ]
        self.graph_store.apply_mutations(story_id, cast_mutations)
        return {
            "story_id": story_id,
            "volumes": [volume.model_dump(mode="json") for volume in volumes],
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
            "cast": [member.model_dump(mode="json") for member in cast],
            "protagonist_character_id": protagonist_id,
        }

    def run_chapter(self, story_id: str, chapter_id: int) -> dict:
        unachieved_anchors = [
            anchor
            for anchor in self.story_repository.list_anchors(story_id)
            if anchor["chapter_target"] >= chapter_id
        ]
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        pov_raw = (story.get("protagonist_character_id") or "").strip()
        pov_character_id = pov_raw if pov_raw else "char_public_observer"
        initial_state = build_initial_state(
            story_id=story_id,
            chapter_id=chapter_id,
            unachieved_anchors=unachieved_anchors,
            trace_id=str(uuid4()),
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
            pov_character_id=pov_character_id,
        )
        run = self.workflow_repository.create_run(story_id, chapter_id, initial_state)
        final_state = self._execute_workflow(run.run_id, initial_state)
        return {
            "run": self.workflow_repository.get_run(run.run_id).model_dump(mode="json"),
            "state": final_state,
            "steps": self.workflow_repository.list_steps(run.run_id),
        }

    def get_workflow(self, run_id: str) -> dict:
        run = self.workflow_repository.get_run(run_id)
        return {
            "run": run.model_dump(mode="json"),
            "state": self.workflow_repository.get_run_state(run_id),
            "steps": self.workflow_repository.list_steps(run_id),
        }

    def list_chapters(self, story_id: str) -> list[dict]:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        return self.story_repository.list_chapters(story_id)

    def get_chapter(self, story_id: str, chapter_id: int) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        return chapter

    def handle_hitl_decision(self, run_id: str, request: HitlDecisionRequest) -> dict:
        state = self.workflow_repository.get_run_state(run_id)
        self.workflow_repository.append_hitl_action(run_id, "decision", request.model_dump(mode="json"))
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["workflow_status"] = "RUNNING"
        state["pending_hitl_options"] = []
        if request.option_id == "relax_word_count":
            state["target_word_count"] = max(800, int(state["target_word_count"] * 0.6))
        if request.option_id == "force_rewrite_plan":
            state["plan_retry_count"] = 0
            state["plan_feedback"] = []
        if state.get("hitl_reason") == "Draft_Loop_Exceeded":
            state["draft_loop_retry_count"] = 0
            state["draft_retry_count"] = 0
            state["reader_retry_count"] = 0
        state["resume_from"] = state.get("resume_from", "director")
        self.workflow_repository.update_run(run_id, state)
        self._execute_workflow(run_id, state)
        return self.get_workflow(run_id)

    def handle_hitl_outline_edit(self, run_id: str, request: HitlOutlineEditRequest) -> dict:
        state = self.workflow_repository.get_run_state(run_id)
        state["ground_truth_events"] = [event.model_dump(mode="json") for event in request.ground_truth_events]
        if request.narrative_script:
            state["narrative_script"] = request.narrative_script
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["resume_from"] = "author"
        self.workflow_repository.append_hitl_action(run_id, "outline_edit", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)
        self._execute_workflow(run_id, state)
        return self.get_workflow(run_id)

    def handle_hitl_state_injection(self, run_id: str, request: HitlStateInjectionRequest) -> dict:
        state = self.workflow_repository.get_run_state(run_id)
        self.graph_store.apply_mutations(state["story_id"], request.mutations)
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["resume_from"] = state.get("resume_from", "author")
        self.workflow_repository.append_hitl_action(run_id, "state_injection", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)
        self._execute_workflow(run_id, state)
        return self.get_workflow(run_id)

    def replay_state_transaction(self, transaction_id: str) -> dict:
        transaction = self.workflow_repository.get_state_transaction(transaction_id)
        payload = deepcopy(transaction.payload)
        parsed_output = StateUpdaterOutput.model_validate(payload["state_updater_output"])

        if not transaction.graph_applied:
            self.graph_store.apply_mutations(transaction.story_id, parsed_output.mutations)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.GRAPH_APPLIED,
                graph_applied=True,
                error_text="",
            )

        if not transaction.vector_applied:
            self.vector_store.add_documents(transaction.story_id, parsed_output.vector_documents)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.VECTOR_APPLIED,
                vector_applied=True,
                error_text="",
            )

        if not transaction.sqlite_applied:
            self.story_repository.upsert_chapter_content(
                story_id=transaction.story_id,
                chapter_id=transaction.chapter_id,
                title=payload["chapter_title"],
                content=payload["chapter_content"],
                status="completed",
            )
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.SQLITE_APPLIED,
                sqlite_applied=True,
                error_text="",
            )

        final_record = self.workflow_repository.update_state_transaction(
            transaction_id,
            status=StateTransactionStatus.COMMITTED,
            error_text="",
        )
        return final_record.model_dump(mode="json")
