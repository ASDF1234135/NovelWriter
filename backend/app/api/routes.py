from __future__ import annotations

import asyncio
import json
from urllib.parse import quote
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from app.dependencies import (
    get_graph_rag_service,
    get_graph_store,
    get_story_repository,
    get_workflow_repository,
    get_workflow_service,
)
from app.domain.schema import (
    ChapterRunRequest,
    GraphRAGAskRequest,
    GraphRAGEvaluateOutput,
    GraphRAGEvaluateRequest,
    GraphRAGStoryBackgroundRequest,
    GraphQueryRequest,
    HitlAnchorDelayRequest,
    HitlAnchorResolutionRequest,
    HitlBStoryJudgementRequest,
    HitlContextPruneRequest,
    HitlDecisionRequest,
    HitlDirectorPatchRequest,
    HitlDraftEditRequest,
    HitlExtractionRemapRequest,
    HitlOutlineEditRequest,
    HitlStateInjectionRequest,
    MacroPlanPut,
    StoryInput,
    StoryPatch,
)
from app.services.graph_store import GraphStore
from app.services.graph_rag_service import GraphRAGService
from app.services.llm import LLMProviderError
from app.services.workflow.service import (
    ChapterAlreadyCompletedError,
    ChapterSummaryRegenerateFailed,
    HitlNotWaitingError,
    MacroCompileAlreadyRunningError,
    MacroPlanCompletedChapterLockError,
    MacroPlanValidationError,
    StoryConfigurationLockedError,
    WorkflowService,
)
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.workflow.output_language import normalize_output_language
from app.services.writing_preamble import build_writing_preamble

router = APIRouter()


@router.post("/stories")
def create_story(
    story_input: StoryInput,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    return workflow_service.create_story(story_input)


@router.get("/stories")
def list_stories(story_repository: StoryRepository = Depends(get_story_repository)) -> JSONResponse:
    payload = story_repository.list_stories()
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": "private, max-age=5",
        },
    )


@router.get("/stories/{story_id}")
def get_story_detail(
    story_id: str,
    story_repository: StoryRepository = Depends(get_story_repository),
) -> dict:
    row = story_repository.get_story(story_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    # Workflow runs no longer imply configuration lock (macro/story edits allowed after runs).
    locked = False
    has_completed = story_repository.has_completed_chapter(story_id)
    rt = row.get("story_runtime_json") if isinstance(row.get("story_runtime_json"), dict) else {}
    return {
        "story_id": row["story_id"],
        "title": row["title"],
        "premise": row["premise"],
        "bible": row["bible_json"],
        "story_runtime": rt,
        "storylines": list(row.get("storylines_json") or []),
        "anchor_nodes": list(row.get("anchor_nodes_json") or []),
        "target_total_words": row["target_total_words"],
        "branch_count_override": row.get("branch_count_override"),
        "plan_retry_limit": row["plan_retry_limit"],
        "draft_loop_retry_limit": row["draft_loop_retry_limit"],
        "output_language": normalize_output_language(str(row.get("output_language") or "")),
        "macro_author_notes": str(row.get("macro_author_notes") or ""),
        "cast_seed": [s.model_dump(mode="json") for s in (row.get("cast_seed") or [])],
        "macro_compile_status": str(row.get("macro_compile_status") or "IDLE"),
        "macro_compile_updated_at": str(row.get("macro_compile_updated_at") or ""),
        "macro_compile_error": str(row.get("macro_compile_error") or ""),
        "configuration_locked": locked,
        "macro_topology_mode": "fixed_fishbone",
        "topology_locked": True,
        "has_completed_chapter": has_completed,
        "macro_edit_locked": has_completed,
    }


@router.get("/stories/{story_id}/workflow-metrics")
def get_story_workflow_metrics(
    story_id: str,
    limit: int = 200,
    offset: int = 0,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.get_story_workflow_metrics(story_id, limit=limit, offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stories/{story_id}/workflows/latest-active")
def get_latest_active_workflow(
    story_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict | None:
    try:
        return workflow_service.get_latest_active_workflow_run(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/stories/{story_id}")
def patch_story(
    story_id: str,
    patch: StoryPatch,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    story_repository: StoryRepository = Depends(get_story_repository),
) -> dict:
    try:
        row = workflow_service.patch_story(story_id, patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoryConfigurationLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    locked = False
    has_completed = story_repository.has_completed_chapter(story_id)
    rt = row.get("story_runtime_json") if isinstance(row.get("story_runtime_json"), dict) else {}
    return {
        "story_id": row["story_id"],
        "title": row["title"],
        "premise": row["premise"],
        "bible": row["bible_json"],
        "story_runtime": rt,
        "storylines": list(row.get("storylines_json") or []),
        "anchor_nodes": list(row.get("anchor_nodes_json") or []),
        "target_total_words": row["target_total_words"],
        "branch_count_override": row.get("branch_count_override"),
        "plan_retry_limit": row["plan_retry_limit"],
        "draft_loop_retry_limit": row["draft_loop_retry_limit"],
        "output_language": normalize_output_language(str(row.get("output_language") or "")),
        "macro_author_notes": str(row.get("macro_author_notes") or ""),
        "cast_seed": [s.model_dump(mode="json") for s in (row.get("cast_seed") or [])],
        "macro_compile_status": str(row.get("macro_compile_status") or "IDLE"),
        "macro_compile_updated_at": str(row.get("macro_compile_updated_at") or ""),
        "macro_compile_error": str(row.get("macro_compile_error") or ""),
        "configuration_locked": locked,
        "macro_topology_mode": "fixed_fishbone",
        "topology_locked": True,
        "has_completed_chapter": has_completed,
        "macro_edit_locked": has_completed,
    }


@router.delete("/stories/{story_id}")
def delete_story(
    story_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.delete_story(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "story_id": story_id}


@router.get("/stories/{story_id}/macro-snapshot")
def macro_snapshot(
    story_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.get_macro_snapshot(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/stories/{story_id}/macro-plan")
def put_macro_plan(
    story_id: str,
    body: MacroPlanPut,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.put_macro_plan(story_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoryConfigurationLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MacroPlanCompletedChapterLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MacroPlanValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stories/{story_id}/macro-compile")
def macro_compile(
    story_id: str,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> JSONResponse:
    try:
        workflow_service.begin_macro_compile_async(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MacroCompileAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MacroPlanCompletedChapterLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(workflow_service.execute_macro_compile_background, story_id)
    return JSONResponse(
        status_code=202,
        content={"accepted": True, "story_id": story_id},
    )


@router.post("/stories/{story_id}/chapters/{chapter_id}/run")
def run_chapter(
    story_id: str,
    chapter_id: int,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    run_body: ChapterRunRequest = Body(default_factory=ChapterRunRequest),
) -> JSONResponse:
    try:
        payload = workflow_service.start_run_chapter(
            story_id,
            chapter_id,
            author_chapter_plan=run_body.author_chapter_plan,
            chapter_outline=run_body.chapter_outline,
            chapter_hard_rules=run_body.chapter_hard_rules,
            ai_freedom_level=run_body.ai_freedom_level,
            extraction_surface_hints=run_body.extraction_surface_hints,
            waive_mandatory_node_ids=run_body.waive_mandatory_node_ids,
            selected_anchor_ids=run_body.selected_anchor_ids,
            next_anchor_ids=run_body.next_anchor_ids,
            require_chapter_review=run_body.require_chapter_review,
        )
        run_id = payload["run"]["run_id"]
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return JSONResponse(status_code=202, content=payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChapterAlreadyCompletedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stories/{story_id}/chapters")
def list_chapters(
    story_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> list[dict]:
    try:
        return workflow_service.list_chapters(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stories/{story_id}/chapters/{chapter_id}")
def get_chapter(
    story_id: str,
    chapter_id: int,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.get_chapter(story_id, chapter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stories/{story_id}/chapters/{chapter_id}/workflow-metrics")
def get_chapter_workflow_metrics(
    story_id: str,
    chapter_id: int,
    limit: int = 200,
    offset: int = 0,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    if chapter_id < 1:
        raise HTTPException(status_code=400, detail="chapter_id must be >= 1")
    try:
        return workflow_service.get_chapter_workflow_metrics(story_id, chapter_id, limit=limit, offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stories/{story_id}/chapters/{chapter_id}/writing-preamble")
def get_writing_preamble(
    story_id: str,
    chapter_id: int,
    story_repository: StoryRepository = Depends(get_story_repository),
) -> dict:
    if chapter_id < 1:
        raise HTTPException(status_code=400, detail="chapter_id must be >= 1")
    try:
        return build_writing_preamble(story_repository, story_id, chapter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stories/{story_id}/chapters/{chapter_id}/regenerate-summary")
def regenerate_chapter_plot_summary(
    story_id: str,
    chapter_id: int,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    if chapter_id < 1:
        raise HTTPException(status_code=400, detail="chapter_id must be >= 1")
    try:
        return workflow_service.regenerate_chapter_plot_summary(story_id, chapter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChapterSummaryRegenerateFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stories/{story_id}/chapters/{chapter_id}/download.txt")
def download_chapter_txt(
    story_id: str,
    chapter_id: int,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> PlainTextResponse:
    try:
        chapter = workflow_service.get_chapter(story_id, chapter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filename = quote(f"{story_id}-chapter-{chapter_id}.txt")
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
    }
    return PlainTextResponse(chapter["content"], headers=headers)


@router.get("/workflows/{run_id}")
def get_workflow(
    run_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.get_workflow(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{run_id}/hitl-actions")
def list_workflow_hitl_actions(
    run_id: str,
    limit: int = 100,
    offset: int = 0,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> list[dict]:
    try:
        return workflow_service.list_hitl_actions(run_id, limit=limit, offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def workflow_event_stream(run_id: str, repo: WorkflowRepository) -> AsyncIterator[str]:
    seen = 0
    while True:
        try:
            run_state = repo.get_run_state(run_id)
            steps = repo.list_steps(run_id)
        except KeyError:
            yield "event: error\ndata: {}\n\n"
            return

        if len(steps) > seen:
            for step in steps[seen:]:
                yield f"data: {json.dumps(step, ensure_ascii=False)}\n\n"
            seen = len(steps)

        ws = str(run_state.get("workflow_status") or "")
        req_hitl = bool(run_state.get("requires_hitl"))
        if ws in {"COMPLETED", "FAILED"} or ws == "WAITING_HITL" or req_hitl:
            yield f"event: end\ndata: {json.dumps({'status': run_state.get('workflow_status')}, ensure_ascii=False)}\n\n"
            return

        await asyncio.sleep(1)


@router.get("/workflows/{run_id}/events")
def workflow_events(
    run_id: str,
    repo: WorkflowRepository = Depends(get_workflow_repository),
) -> StreamingResponse:
    return StreamingResponse(workflow_event_stream(run_id, repo), media_type="text/event-stream")


@router.post("/workflows/{run_id}/hitl/decision")
def hitl_decision(
    run_id: str,
    request: HitlDecisionRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_decision(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/outline")
def hitl_outline(
    run_id: str,
    request: HitlOutlineEditRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_outline_edit(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/state-injection")
def hitl_state_injection(
    run_id: str,
    request: HitlStateInjectionRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_state_injection(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/draft-edit")
def hitl_draft_edit(
    run_id: str,
    request: HitlDraftEditRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_draft_edit(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/director-patch")
def hitl_director_patch(
    run_id: str,
    request: HitlDirectorPatchRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_director_patch(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/extraction-remap")
def hitl_extraction_remap(
    run_id: str,
    request: HitlExtractionRemapRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_extraction_remap(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/anchor-resolution")
def hitl_anchor_resolution(
    run_id: str,
    request: HitlAnchorResolutionRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_anchor_resolution(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/b-story-judgement")
def hitl_b_story_judgement(
    run_id: str,
    request: HitlBStoryJudgementRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    """Backward-compatible endpoint kept for older frontend clients."""
    try:
        workflow_service.apply_hitl_b_story_judgement(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/anchor-delay")
def hitl_anchor_delay(
    run_id: str,
    request: HitlAnchorDelayRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_anchor_delay(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/context-prune")
def hitl_context_prune(
    run_id: str,
    request: HitlContextPruneRequest,
    background_tasks: BackgroundTasks,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        workflow_service.apply_hitl_context_prune(run_id, request)
        background_tasks.add_task(workflow_service.execute_stored_run, run_id)
        return workflow_service.get_workflow(run_id)
    except HitlNotWaitingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stories/{story_id}/graph")
def story_graph(
    story_id: str,
    active_epoch_id: str = "epoch_present",
    pov_character_id: str = "char_public_observer",
    narrative_directive: str = "觀測故事狀態",
    graph_store: GraphStore = Depends(get_graph_store),
) -> dict:
    return graph_store.query_context(
        GraphQueryRequest(
            story_id=story_id,
            active_epoch_id=active_epoch_id,
            pov_character_id=pov_character_id,
            narrative_directive=narrative_directive,
        )
    ).model_dump(mode="json")


@router.get("/stories/{story_id}/graph/full")
def story_graph_full(
    story_id: str,
    graph_store: GraphStore = Depends(get_graph_store),
    story_repository: StoryRepository = Depends(get_story_repository),
) -> dict:
    """All StoryNode nodes and relationships for this story (no POV/epoch epistemic filter)."""
    if not story_repository.get_story(story_id):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    return graph_store.dump_story_graph(story_id).model_dump(mode="json")


@router.post("/stories/{story_id}/graph-rag/ask")
def graph_rag_ask(
    story_id: str,
    request: GraphRAGAskRequest,
    graph_rag: GraphRAGService = Depends(get_graph_rag_service),
    story_repository: StoryRepository = Depends(get_story_repository),
) -> PlainTextResponse:
    if not story_repository.get_story(story_id):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    try:
        text = graph_rag.ask_question(
            request.question,
            story_id=story_id,
            active_epoch_id=request.active_epoch_id,
            pov_character_id=request.pov_character_id,
            top_k=request.top_k,
            context_hop_tier=request.context_hop_tier,
        )
        return PlainTextResponse(text)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stories/{story_id}/graph-rag/evaluate")
def graph_rag_evaluate(
    story_id: str,
    request: GraphRAGEvaluateRequest,
    graph_rag: GraphRAGService = Depends(get_graph_rag_service),
    story_repository: StoryRepository = Depends(get_story_repository),
) -> JSONResponse:
    if not story_repository.get_story(story_id):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    try:
        parsed = graph_rag.evaluate_condition(
            request.condition_desc,
            story_id=story_id,
            active_epoch_id=request.active_epoch_id,
            pov_character_id=request.pov_character_id,
            top_k=request.top_k,
            context_hop_tier=request.context_hop_tier,
            response_model=GraphRAGEvaluateOutput,
        )
        return JSONResponse(content=parsed.model_dump(mode="json"))
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stories/{story_id}/graph-rag/story-background")
def graph_rag_story_background(
    story_id: str,
    request: GraphRAGStoryBackgroundRequest,
    graph_rag: GraphRAGService = Depends(get_graph_rag_service),
    story_repository: StoryRepository = Depends(get_story_repository),
) -> PlainTextResponse:
    if not story_repository.get_story(story_id):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    try:
        text = graph_rag.summarize_story_background(
            narrative_directive=request.narrative_directive,
            chapter_goal=request.chapter_goal,
            story_id=story_id,
            active_epoch_id=request.active_epoch_id,
            pov_character_id=request.pov_character_id,
            output_language=request.output_language,
            top_k=request.top_k,
            context_hop_tier=request.context_hop_tier,
        )
        return PlainTextResponse(text)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/state-transactions/{transaction_id}/replay")
def replay_state_transaction(
    transaction_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.replay_state_transaction(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
