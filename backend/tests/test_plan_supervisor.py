from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.domain.state import SafeSupervisorPayload
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.plan_supervisor import _build_plan_supervisor_prompt, run_plan_supervisor
from app.services.workflow.profiles import get_profile


def build_context(db_path: str) -> WorkflowContext:
    db = SQLiteDatabase(db_path)
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="plan-supervisor-test",
    )


def test_plan_supervisor_allows_partial_convergence_before_anchor_chapter(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor.sqlite3"))
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_06",
                "chapter_target": 6,
            }
        ],
        "ground_truth_events": [
            {
                "event_id": "e001",
                "description": "主角在穩定日常中發現異常，為遠期錨點鋪墊。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章建立穩定日常與微小異常，章末以召喚令迫使主角離開熟悉環境。",
        "chapter_start_location": "舊城區住處",
        "chapter_end_location_hint": "王都西門",
        "must_include_beats": ["發現異常", "離開住處"],
        "previous_chapter_summary": "主角暫時維持日常生活。",
        "recent_chapter_context": "第0章：主角暫時維持日常生活。",
        "last_known_location": "舊城區住處",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 2500,
    }

    output, payload = run_plan_supervisor(state, context)

    assert payload["partial_convergence_allowed"] is True
    assert output["is_approved"] is True
    assert output["anchor_achieved"] is False


def test_plan_supervisor_requires_anchor_completion_on_target_chapter(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_target.sqlite3"))
    state = {
        "chapter_id": 6,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_06",
                "chapter_target": 6,
            }
        ],
        "ground_truth_events": [
            {
                "event_id": "e006",
                "description": "主角已被迫踏上旅程。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "主角在城門前回望王都，正式離開原本的生活。",
        "chapter_start_location": "王都內城",
        "chapter_end_location_hint": "王都城門外驛道",
        "must_include_beats": ["正式離開王都"],
        "previous_chapter_summary": "主角在城門前猶豫。",
        "recent_chapter_context": "第5章：主角在城門前猶豫。",
        "last_known_location": "王都內城",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 2500,
    }

    output, payload = run_plan_supervisor(state, context)

    assert payload["partial_convergence_allowed"] is False
    assert output["is_approved"] is False
    assert "ANCHOR_DIVERGENCE" in output["violation_type"]


def test_plan_supervisor_timeline_rollback_heuristic_is_soft_warning_only(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_rollback.sqlite3"))
    state = {
        "chapter_id": 2,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {
                "event_id": "e002",
                "description": "主角收到密信，決定回城調查。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章再次讓主角收到密信，並決定回城調查。",
        "chapter_start_location": "城外驛站",
        "chapter_end_location_hint": "城外驛站",
        "must_include_beats": ["收到密信", "決定回城"],
        "previous_chapter_summary": "主角收到密信，決定回城調查。",
        "recent_chapter_context": "第1章：主角收到密信，決定回城調查。",
        "last_known_location": "城外驛站",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 2500,
    }

    output, _ = run_plan_supervisor(state, context)

    assert output["is_approved"] is True
    assert "INCONSISTENCY" not in output["violation_type"]
    assert any("時序重演" in w for w in (output.get("soft_warnings") or []))


def test_plan_supervisor_rejects_word_count_below_beat_floor(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_words.sqlite3"))
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {"event_id": "e1", "description": "新事件。", "caused_by_event_id": None},
        ],
        "narrative_script": "本章推進調查。",
        "chapter_start_location": "A",
        "chapter_end_location_hint": "A",
        "must_include_beats": ["a", "b", "c", "d", "e"],
        "previous_chapter_summary": "",
        "recent_chapter_context": "",
        "last_known_location": "A",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 400,
    }

    output, _ = run_plan_supervisor(state, context)

    assert output["is_approved"] is False
    assert "WORD_COUNT_UNMATCH" in output["violation_type"]


def _base_state_for_genesis() -> dict:
    return {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {
                "event_id": "e001",
                "description": "主角與情報掮客接觸，取得地下線索。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "雨中，一聲微弱的喵叫吸引了他的注意，那是一隻後腿流血的黑貓，他為牠包紮。",
        "chapter_start_location": "巷弄",
        "chapter_end_location_hint": "巷弄",
        "must_include_beats": ["救助黑貓"],
        "previous_chapter_summary": "主角在市集閒逛。",
        "recent_chapter_context": "第0章：主角在市集閒逛。",
        "last_known_location": "巷弄",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 2500,
        "b_story_directive": "請描寫主角在路上遇到一隻受傷的黑貓並幫牠包紮。",
        "new_elements_to_introduce": ["一個專門提供地下情報的記憶掮客或組織"],
        "planned_graph_nodes": [{"role": "情報掮客", "canonical_name": ""}],
    }


def test_plan_supervisor_genesis_allows_semantic_mismatch_no_substring_match(tmp_path) -> None:
    """Long Director phrase + short Planner role: no Python substring gate; structural rule satisfied."""
    context = build_context(str(tmp_path / "plan_supervisor_genesis_semantic.sqlite3"))
    state = _base_state_for_genesis()
    output, _ = run_plan_supervisor(state, context)
    assert output["is_approved"] is True
    assert "MISSING_DIRECTIVE" not in output["violation_type"]


def test_plan_supervisor_genesis_requires_non_empty_proposed_nodes(tmp_path) -> None:
    context = build_context(str(tmp_path / "plan_supervisor_genesis_empty.sqlite3"))
    state = _base_state_for_genesis()
    state["planned_graph_nodes"] = []
    output, _ = run_plan_supervisor(state, context)
    assert output["is_approved"] is False
    assert "MISSING_DIRECTIVE" in output["violation_type"]


def test_plan_supervisor_teleportation_is_llm_only_mock_does_not_block(tmp_path) -> None:
    """Location paradox is judged by the real plan_supervisor LLM; MockLLM has no teleport check."""
    context = build_context(str(tmp_path / "plan_supervisor_teleport.sqlite3"))
    state = {
        "chapter_id": 2,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [{"anchor_id": "anchor_06", "chapter_target": 6}],
        "ground_truth_events": [
            {
                "event_id": "e002",
                "description": "主角在黑塔密室開始搜查新文件。",
                "caused_by_event_id": None,
            }
        ],
        "narrative_script": "本章開場就在黑塔密室搜查，直接切入新線索。",
        "chapter_start_location": "黑塔密室",
        "chapter_end_location_hint": "黑塔密室",
        "must_include_beats": ["搜查文件"],
        "previous_chapter_summary": "主角留在港口旅店休息。",
        "recent_chapter_context": "第1章：主角留在港口旅店休息。",
        "last_known_location": "港口旅店",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "target_word_count": 2500,
    }

    output, _ = run_plan_supervisor(state, context)

    assert output["is_approved"] is True
    assert "PHYSICAL_CONFLICT" not in output["violation_type"]


def test_plan_supervisor_prompt_includes_boundary_entity_conflict_rule() -> None:
    payload = SafeSupervisorPayload(chapter_id=1, current_chapter_id=1, active_epoch_id="epoch_present")
    prompt = _build_plan_supervisor_prompt(payload)
    assert "13." in prompt
    assert "邊界與實體衝突檢查" in prompt
    assert "ending_boundary_rule" in prompt
    assert "proposed_new_nodes" in prompt


def test_plan_supervisor_profile_mentions_boundary_and_mandatory_entities() -> None:
    text = get_profile("plan_supervisor").system_prompt
    assert "章末邊界" in text
    assert "必選圖節點" in text
