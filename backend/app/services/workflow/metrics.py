"""Aggregate workflow_runs / workflow_steps / hitl_actions into metrics payloads."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


def _parse_iso_dt(s: str) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def wall_clock_ms_between(created_at: str, updated_at: str) -> int | None:
    a = _parse_iso_dt(created_at)
    b = _parse_iso_dt(updated_at)
    if not a or not b:
        return None
    return max(0, int((b - a).total_seconds() * 1000))


def _percentile(sorted_vals: list[int], p: float) -> int | None:
    if not sorted_vals:
        return None
    if p <= 0:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return int(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


def aggregate_agent_step_stats(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_agent: dict[str, list[int]] = {}
    tokens_by: dict[str, int] = {}

    for s in steps:
        agent = str(s.get("agent_name") or "")
        if not agent:
            continue
        lat = int(s.get("latency_ms") or 0)
        tok = int(s.get("token_usage") or 0)
        by_agent.setdefault(agent, []).append(lat)
        tokens_by[agent] = tokens_by.get(agent, 0) + tok

    out: dict[str, dict[str, Any]] = {}
    for agent, lats in by_agent.items():
        sl = sorted(lats)
        out[agent] = {
            "step_count": len(sl),
            "total_latency_ms": sum(sl),
            "total_tokens": tokens_by.get(agent, 0),
            "p50_latency_ms": _percentile(sl, 50),
            "p95_latency_ms": _percentile(sl, 95),
        }
    return out


def count_agent_steps(steps: list[dict[str, Any]], agent_name: str) -> int:
    return sum(1 for s in steps if str(s.get("agent_name") or "") == agent_name)


def count_route_steps(steps: list[dict[str, Any]], agent_name: str, route_decision: str) -> int:
    return sum(
        1
        for s in steps
        if str(s.get("agent_name") or "") == agent_name and str(s.get("route_decision") or "") == route_decision
    )


def extraction_metrics_from_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Reads last_chapter_extraction_metrics persisted on extraction_gate step output payloads."""
    total_align_retries = 0
    extractions = 0
    for s in steps:
        if str(s.get("agent_name") or "") != "extraction_gate":
            continue
        extractions += 1
        out = s.get("output_payload_json")
        if not isinstance(out, dict):
            continue
        lm = out.get("last_chapter_extraction_metrics")
        if isinstance(lm, dict):
            vg = lm.get("validation_gate")
            if isinstance(vg, dict):
                total_align_retries += int(vg.get("align_retry_attempts") or 0)
    return {
        "extraction_gate_invocations": extractions,
        "sum_align_retry_attempts": total_align_retries,
    }


def summarize_hitl_actions(actions: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    by_type: dict[str, int] = {}
    abort_restart = 0
    for a in actions:
        t = str(a.get("action_type") or "")
        by_type[t] = by_type.get(t, 0) + 1
        if t == "decision":
            payload = a.get("payload")
            if isinstance(payload, dict) and str(payload.get("option_id") or "") == "ABORT_AND_RESTART":
                abort_restart += 1
    return by_type, abort_restart


def extraction_kept_ratios(last_metrics: dict[str, Any]) -> dict[str, float | None]:
    """Post-validation vs pre-validation entity/relation counts (single extraction snapshot)."""
    pre = last_metrics.get("counts_pre_validation_gate")
    post = last_metrics.get("counts_post_validation_gate")
    entity_ratio: float | None = None
    relation_ratio: float | None = None
    if isinstance(pre, dict) and isinstance(post, dict):
        pe = int(pre.get("entities") or 0)
        po = int(post.get("entities") or 0)
        pr_pre = int(pre.get("relations") or 0)
        pr_post = int(post.get("relations") or 0)
        if pe > 0:
            entity_ratio = po / pe
        if pr_pre > 0:
            relation_ratio = pr_post / pr_pre
    return {"entity_kept_ratio": entity_ratio, "relation_kept_ratio": relation_ratio}


class SingleRunMetrics(BaseModel):
    run_id: str
    story_id: str
    chapter_id: int
    status: str
    created_at: str
    updated_at: str
    wall_clock_ms: int | None = None
    steps_sum_latency_ms: int = 0
    plan_retry_count: int = 0
    draft_retry_count: int = 0
    reader_retry_count: int = 0
    draft_loop_retry_count: int = 0
    plan_supervisor_reroute_planner_steps: int = 0
    author_step_count: int = 0
    extraction_gate_author_routes: int = 0
    extraction_gate_hitl_routes: int = 0
    failure_type: str = ""
    timeout_bucket: str = ""
    workflow_status: str = ""
    hitl_actions_total: int = 0
    hitl_abort_restart_count: int = 0
    hitl_action_counts_by_type: dict[str, int] = Field(default_factory=dict)
    last_chapter_extraction_metrics: dict[str, Any] = Field(default_factory=dict)
    extraction_kept_ratios: dict[str, float | None] = Field(default_factory=dict)
    extraction_from_steps: dict[str, Any] = Field(default_factory=dict)
    agent_step_stats: dict[str, dict[str, Any]] = Field(default_factory=dict)


def build_single_run_metrics(
    run_summary: dict[str, Any],
    state: dict[str, Any],
    steps: list[dict[str, Any]],
    hitl_actions: list[dict[str, Any]],
) -> SingleRunMetrics:
    wc = wall_clock_ms_between(str(run_summary.get("created_at") or ""), str(run_summary.get("updated_at") or ""))
    steps_sum = sum(int(s.get("latency_ms") or 0) for s in steps)
    by_type, abort_n = summarize_hitl_actions(hitl_actions)
    ext_steps = extraction_metrics_from_steps(steps)
    last_ext = state.get("last_chapter_extraction_metrics")
    if not isinstance(last_ext, dict):
        last_ext = {}
    ratios = extraction_kept_ratios(last_ext) if last_ext else {"entity_kept_ratio": None, "relation_kept_ratio": None}

    return SingleRunMetrics(
        run_id=str(run_summary["run_id"]),
        story_id=str(run_summary["story_id"]),
        chapter_id=int(run_summary["chapter_id"]),
        status=str(run_summary.get("status") or ""),
        created_at=str(run_summary.get("created_at") or ""),
        updated_at=str(run_summary.get("updated_at") or ""),
        wall_clock_ms=wc,
        steps_sum_latency_ms=steps_sum,
        plan_retry_count=int(state.get("plan_retry_count") or 0),
        draft_retry_count=int(state.get("draft_retry_count") or 0),
        reader_retry_count=int(state.get("reader_retry_count") or 0),
        draft_loop_retry_count=int(state.get("draft_loop_retry_count") or 0),
        plan_supervisor_reroute_planner_steps=count_route_steps(steps, "plan_supervisor", "planner"),
        author_step_count=count_agent_steps(steps, "author"),
        extraction_gate_author_routes=count_route_steps(steps, "extraction_gate", "author"),
        extraction_gate_hitl_routes=count_route_steps(steps, "extraction_gate", "hitl"),
        failure_type=str(state.get("failure_type") or ""),
        timeout_bucket=str(state.get("timeout_bucket") or ""),
        workflow_status=str(state.get("workflow_status") or ""),
        hitl_actions_total=len(hitl_actions),
        hitl_abort_restart_count=abort_n,
        hitl_action_counts_by_type=dict(by_type),
        last_chapter_extraction_metrics=dict(last_ext),
        extraction_kept_ratios=dict(ratios),
        extraction_from_steps=dict(ext_steps),
        agent_step_stats=aggregate_agent_step_stats(steps),
    )


class MetricsRollup(BaseModel):
    runs_included: int
    timeouts_count: int
    failed_count: int
    completed_count: int
    waiting_hitl_count: int
    running_count: int
    sum_wall_clock_ms: int = 0
    sum_steps_latency_ms: int = 0
    sum_plan_retry_count: int = 0
    sum_draft_retry_count: int = 0
    sum_reader_retry_count: int = 0
    sum_hitl_actions: int = 0
    sum_align_retry_attempts: int = 0
    sum_extraction_gate_invocations: int = 0
    avg_entity_kept_ratio: float | None = None
    avg_relation_kept_ratio: float | None = None


def rollup_metrics(runs: list[SingleRunMetrics]) -> MetricsRollup:
    if not runs:
        return MetricsRollup(
            runs_included=0,
            timeouts_count=0,
            failed_count=0,
            completed_count=0,
            waiting_hitl_count=0,
            running_count=0,
        )

    timeouts = sum(1 for r in runs if r.failure_type == "TIMEOUT")
    failed = sum(1 for r in runs if r.status == "FAILED")
    completed = sum(1 for r in runs if r.status == "COMPLETED")
    wh = sum(1 for r in runs if r.status == "WAITING_HITL")
    running = sum(1 for r in runs if r.status == "RUNNING")
    swc = sum(r.wall_clock_ms or 0 for r in runs if r.wall_clock_ms is not None)
    ssl = sum(r.steps_sum_latency_ms for r in runs)
    spr = sum(r.plan_retry_count for r in runs)
    sdr = sum(r.draft_retry_count for r in runs)
    srr = sum(r.reader_retry_count for r in runs)
    sha = sum(r.hitl_actions_total for r in runs)
    sar = sum(int(r.extraction_from_steps.get("sum_align_retry_attempts") or 0) for r in runs)
    sgi = sum(int(r.extraction_from_steps.get("extraction_gate_invocations") or 0) for r in runs)

    er_vals = [r.extraction_kept_ratios.get("entity_kept_ratio") for r in runs]
    er_vals_f = [float(x) for x in er_vals if x is not None]
    rr_vals = [r.extraction_kept_ratios.get("relation_kept_ratio") for r in runs]
    rr_vals_f = [float(x) for x in rr_vals if x is not None]

    return MetricsRollup(
        runs_included=len(runs),
        timeouts_count=timeouts,
        failed_count=failed,
        completed_count=completed,
        waiting_hitl_count=wh,
        running_count=running,
        sum_wall_clock_ms=swc,
        sum_steps_latency_ms=ssl,
        sum_plan_retry_count=spr,
        sum_draft_retry_count=sdr,
        sum_reader_retry_count=srr,
        sum_hitl_actions=sha,
        sum_align_retry_attempts=sar,
        sum_extraction_gate_invocations=sgi,
        avg_entity_kept_ratio=(sum(er_vals_f) / len(er_vals_f)) if er_vals_f else None,
        avg_relation_kept_ratio=(sum(rr_vals_f) / len(rr_vals_f)) if rr_vals_f else None,
    )


class WorkflowMetricsResponse(BaseModel):
    story_id: str
    scope: str  # "story" | "chapter"
    chapter_id: int | None = None
    rollup: MetricsRollup
    runs: list[SingleRunMetrics]
