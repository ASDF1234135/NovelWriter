from __future__ import annotations

import asyncio
import json
from urllib.parse import quote
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.dependencies import get_graph_store, get_workflow_service, get_workflow_repository
from app.domain.schema import (
    GraphQueryRequest,
    HitlDecisionRequest,
    HitlOutlineEditRequest,
    HitlStateInjectionRequest,
    StoryInput,
)
from app.services.graph_store import GraphStore
from app.services.llm import LLMProviderError
from app.services.workflow.service import WorkflowService
from app.repositories.sqlite.workflow_repository import WorkflowRepository

router = APIRouter()


@router.post("/stories")
def create_story(
    story_input: StoryInput,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    return workflow_service.create_story(story_input)


@router.post("/stories/{story_id}/macro-compile")
def macro_compile(
    story_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.macro_compile(story_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stories/{story_id}/chapters/{chapter_id}/run")
def run_chapter(
    story_id: str,
    chapter_id: int,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.run_chapter(story_id, chapter_id)
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

        if run_state.get("workflow_status") in {"COMPLETED", "FAILED"} or run_state.get("requires_hitl"):
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
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.handle_hitl_decision(run_id, request)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/outline")
def hitl_outline(
    run_id: str,
    request: HitlOutlineEditRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.handle_hitl_outline_edit(run_id, request)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/workflows/{run_id}/hitl/state-injection")
def hitl_state_injection(
    run_id: str,
    request: HitlStateInjectionRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.handle_hitl_state_injection(run_id, request)
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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


@router.post("/state-transactions/{transaction_id}/replay")
def replay_state_transaction(
    transaction_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    try:
        return workflow_service.replay_state_transaction(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
