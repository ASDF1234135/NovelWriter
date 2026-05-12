"""Tests for workflow metrics aggregation and repository listing."""

from __future__ import annotations

import pytest

from app.domain.state import build_initial_state
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.workflow.metrics import (
    build_single_run_metrics,
    extraction_kept_ratios,
    extraction_metrics_from_steps,
    rollup_metrics,
    summarize_hitl_actions,
    wall_clock_ms_between,
)
from app.services.workflow.nodes.extraction_gate import build_last_chapter_extraction_metrics


def test_wall_clock_ms_between_parseable() -> None:
    ms = wall_clock_ms_between("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:05+00:00")
    assert ms == 5000


def test_build_last_chapter_extraction_metrics_without_diag() -> None:
    m = build_last_chapter_extraction_metrics(None, entities_final=3, relations_final=2, mandatory_mapping_ok=True)
    assert m["diag_missing"] is True
    assert m["entities_final"] == 3
    assert m["mandatory_mapping_ok"] is True


def test_build_last_chapter_extraction_metrics_with_diag() -> None:
    diag = {
        "latency_ms": 1200,
        "model": "gpt-test",
        "quality_metrics": {"entity_candidates_raw": 10, "entity_candidates_kept": 8, "concept_candidates_dropped": 2},
        "counts_pre_validation_gate": {"entities": 8, "relations": 5},
        "counts_post_validation_gate": {"entities": 7, "relations": 4},
        "steps": {
            "entity_extractor": {"fallback": False},
            "chapter_memory_extractor": {"fallback": False},
            "relation_extractor": {"fallback": False, "batch_count": 2},
            "validation_gate": {
                "align_retry_attempts": 2,
                "dropped_non_align_count": 1,
                "align_failed_remaining_count": 0,
            },
        },
    }
    m = build_last_chapter_extraction_metrics(
        diag,
        entities_final=7,
        relations_final=4,
        mandatory_mapping_ok=True,
    )
    assert m["entity_extractor_fallback"] is False
    assert m["validation_gate"]["align_retry_attempts"] == 2
    assert m["counts_pre_validation_gate"]["relations"] == 5


def test_extraction_kept_ratios() -> None:
    lm = {
        "counts_pre_validation_gate": {"entities": 10, "relations": 8},
        "counts_post_validation_gate": {"entities": 9, "relations": 6},
    }
    r = extraction_kept_ratios(lm)
    assert r["entity_kept_ratio"] == pytest.approx(0.9)
    assert r["relation_kept_ratio"] == pytest.approx(0.75)


def test_extraction_metrics_from_steps_align_sum() -> None:
    steps = [
        {
            "agent_name": "extraction_gate",
            "output_payload_json": {
                "last_chapter_extraction_metrics": {
                    "validation_gate": {"align_retry_attempts": 2},
                }
            },
        },
        {
            "agent_name": "extraction_gate",
            "output_payload_json": {
                "last_chapter_extraction_metrics": {
                    "validation_gate": {"align_retry_attempts": 1},
                }
            },
        },
    ]
    ext = extraction_metrics_from_steps(steps)
    assert ext["extraction_gate_invocations"] == 2
    assert ext["sum_align_retry_attempts"] == 3


def test_summarize_hitl_actions_abort_restart() -> None:
    actions = [
        {"action_type": "decision", "payload": {"option_id": "keep_current_logic"}},
        {"action_type": "decision", "payload": {"option_id": "ABORT_AND_RESTART"}},
        {"action_type": "outline", "payload": {}},
    ]
    by_type, abort_n = summarize_hitl_actions(actions)
    assert by_type["decision"] == 2
    assert by_type["outline"] == 1
    assert abort_n == 1


def test_build_single_run_metrics_and_rollup() -> None:
    summary = {
        "run_id": "r1",
        "story_id": "s1",
        "chapter_id": 1,
        "status": "COMPLETED",
        "created_at": "2026-05-01T10:00:00+00:00",
        "updated_at": "2026-05-01T10:01:40+00:00",
    }
    state = {
        "plan_retry_count": 2,
        "draft_retry_count": 3,
        "reader_retry_count": 1,
        "draft_loop_retry_count": 4,
        "failure_type": "",
        "timeout_bucket": "",
        "workflow_status": "COMPLETED",
        "last_chapter_extraction_metrics": {
            "counts_pre_validation_gate": {"entities": 4, "relations": 3},
            "counts_post_validation_gate": {"entities": 4, "relations": 2},
        },
    }
    steps = [
        {"agent_name": "plan_supervisor", "route_decision": "planner", "latency_ms": 100, "token_usage": 10},
        {"agent_name": "author", "route_decision": "", "latency_ms": 500, "token_usage": 100},
        {"agent_name": "author", "route_decision": "", "latency_ms": 400, "token_usage": 80},
        {
            "agent_name": "extraction_gate",
            "route_decision": "copyeditor",
            "latency_ms": 200,
            "token_usage": 0,
            "output_payload_json": {
                "last_chapter_extraction_metrics": {"validation_gate": {"align_retry_attempts": 2}},
            },
        },
    ]
    hitl = [{"action_type": "decision", "payload": {"option_id": "x"}}]
    one = build_single_run_metrics(summary, state, steps, hitl)
    assert one.plan_supervisor_reroute_planner_steps == 1
    assert one.author_step_count == 2
    assert one.steps_sum_latency_ms == 1200
    assert one.extraction_from_steps["sum_align_retry_attempts"] == 2
    assert one.hitl_actions_total == 1

    summary2 = {**summary, "run_id": "r2", "status": "FAILED"}
    state2 = {
        **state,
        "failure_type": "TIMEOUT",
        "timeout_bucket": "llm",
        "workflow_status": "FAILED",
        "last_chapter_extraction_metrics": {},
    }
    two = build_single_run_metrics(summary2, state2, [], [])
    roll = rollup_metrics([one, two])
    assert roll.runs_included == 2
    assert roll.timeouts_count == 1
    assert roll.sum_plan_retry_count == 4


def test_list_run_summaries_for_story_filters_chapter(tmp_path) -> None:
    db_path = str(tmp_path / "wf_metrics.sqlite3")
    db = SQLiteDatabase(db_path)
    wf = WorkflowRepository(db)
    st = build_initial_state(
        story_id="story-a",
        chapter_id=1,
        trace_id="t1",
        plan_retry_limit=3,
        draft_loop_retry_limit=3,
        pov_character_id="pov",
    )
    wf.create_run("story-a", 1, st)
    wf.create_run("story-a", 2, st)

    all_rows = wf.list_run_summaries_for_story("story-a")
    assert len(all_rows) == 2

    ch1 = wf.list_run_summaries_for_story("story-a", chapter_id=1)
    assert len(ch1) == 1
    assert ch1[0]["chapter_id"] == 1
