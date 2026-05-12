from __future__ import annotations

import json
from concurrent.futures import as_completed
from datetime import UTC, datetime
from typing import Any

from app.core.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from app.core.config import get_settings

from pydantic import BaseModel, Field

from app.domain.schema import (
    CharacterArcMilestone,
    CharacterEvolutionRequest,
    GraphQueryRequest,
    NodeType,
    StoryCastMemberStored,
)
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


class _ExpandedProfile(BaseModel):
    personality: str = Field(default="", max_length=600)
    core_motivation: str = Field(default="", max_length=600)
    short_bio: str = Field(default="", max_length=500)
    speech_style: str = Field(default="", max_length=240)
    fatal_flaw: str = Field(default="", max_length=400)
    quirks_and_habits: str = Field(default="", max_length=400)
    age: str = Field(default="", max_length=48)
    core_value: str = Field(default="", max_length=600)


def _compile_from_planner_profile(row: dict[str, Any]) -> StoryCastMemberStored | None:
    if str(row.get("node_type") or "") != "CHARACTER":
        return None
    node_id = str(row.get("node_id") or "").strip()
    if not node_id:
        return None
    profile = row.get("character_profile")
    if not isinstance(profile, dict):
        return None
    name = str(row.get("canonical_name") or "").strip() or node_id
    core = str(profile.get("core_motivation") or "")[:600]
    return StoryCastMemberStored(
        node_id=node_id,
        canonical_name=name,
        role="supporting",
        short_bio=str(profile.get("short_bio") or "")[:500],
        aliases=[],
        age=str(profile.get("age") or "")[:48],
        personality=str(profile.get("personality") or "")[:600],
        core_motivation=core,
        core_value=str(profile.get("core_value") or "")[:600] or core,
        speech_style=str(profile.get("speech_style") or "")[:240],
        fatal_flaw=str(profile.get("fatal_flaw") or "")[:400],
        quirks_and_habits=str(profile.get("quirks_and_habits") or "")[:400],
    )


def _build_evolution_prompt(
    state: dict,
    current_member: StoryCastMemberStored,
    req: CharacterEvolutionRequest,
    chapter_content: str,
) -> str:
    return json.dumps(
        {
            "story_id": state["story_id"],
            "chapter_id": state["chapter_id"],
            "trigger": {
                "event_id": req.trigger_event_id,
                "event_summary": req.trigger_event_summary,
                "reason": req.reason,
            },
            "current_profile": {
                "canonical_name": current_member.canonical_name,
                "personality": current_member.personality,
                "speech_style": current_member.speech_style,
                "core_motivation": current_member.core_motivation,
            },
            "target_delta": {
                "new_personality": req.new_personality,
                "new_speech_style": req.new_speech_style,
            },
            "requirements": [
                "Output only updated personality and speech_style; keep other fields stable.",
                "If new_personality/new_speech_style are provided, honor their intent first.",
            ],
            "chapter_excerpt": chapter_content[:3000],
        },
        ensure_ascii=False,
    )


def _build_enrich_prompt(state: dict, entity: dict[str, Any], chapter_content: str) -> str:
    return json.dumps(
        {
            "story_id": state["story_id"],
            "chapter_id": state["chapter_id"],
            "character": {
                "node_id": entity.get("node_id"),
                "canonical_name": entity.get("canonical_name"),
                "aliases": entity.get("aliases") or [],
                "summary": entity.get("summary") or "",
            },
            "requirements": [
                "Emit a full character card; do not leave empty strings—use conservative but playable defaults when data is thin.",
                "personality should reflect behavioral temperament, not goals; core_motivation is long-arc drive.",
                "Follow the response schema exactly—no undeclared top-level keys.",
            ],
            "chapter_excerpt": (chapter_content or "")[:3000],
        },
        ensure_ascii=False,
    )


def _compile_from_extraction(
    state: dict,
    context: WorkflowContext,
    entity: dict[str, Any],
    chapter_content: str,
) -> StoryCastMemberStored | None:
    node_id = str(entity.get("node_id") or "").strip()
    if not node_id:
        return None
    name = str(entity.get("canonical_name") or "").strip() or node_id
    aliases = [str(x).strip() for x in (entity.get("aliases") or []) if str(x).strip()][:8]
    summary = str(entity.get("summary") or "").strip()
    base = StoryCastMemberStored(
        node_id=node_id,
        canonical_name=name,
        role="supporting",
        short_bio=summary[:500],
        aliases=aliases,
        personality="",
        core_motivation="",
        speech_style="",
        fatal_flaw="",
        quirks_and_habits="",
        core_value="",
    )
    if isinstance(context.llm_client, MockLLMClient):
        return base
    prompt = _build_enrich_prompt(state, entity, chapter_content)
    profile = augment_profile_system_prompt(get_profile("profile_expander"), context.output_language)
    for _ in range(2):
        try:
            enriched, _ = context.llm_client.invoke_json(prompt, _ExpandedProfile, profile)
            return base.model_copy(
                update={
                    "personality": enriched.personality,
                    "core_motivation": enriched.core_motivation,
                    "short_bio": enriched.short_bio or base.short_bio,
                    "speech_style": enriched.speech_style,
                    "fatal_flaw": enriched.fatal_flaw,
                    "quirks_and_habits": enriched.quirks_and_habits,
                    "age": enriched.age,
                    "core_value": enriched.core_value or enriched.core_motivation,
                }
            )
        except Exception:
            continue
    return base


def run_profile_expander(state: dict, context: WorkflowContext) -> dict:
    snapshot = context.graph_store.query_context(
        GraphQueryRequest(
            story_id=state["story_id"],
            active_epoch_id=state["active_epoch_id"],
            pov_character_id=state["pov_character_id"],
            narrative_directive=state["narrative_directive"],
        )
    )
    existing_ids = {node.node_id for node in snapshot.nodes}
    updates_by_node: dict[str, dict[str, Any]] = {}

    for row in list(state.get("planned_graph_nodes") or []):
        if not isinstance(row, dict):
            continue
        member = _compile_from_planner_profile(row)
        if member is None:
            continue
        updates_by_node[member.node_id] = {
            "update_mode": "fill_empty",
            "member": member.model_dump(mode="json"),
        }

    pending = state.get("pending_chapter_extraction") or {}
    entities = pending.get("entities") or []
    chapter_content = str(state.get("best_draft_content") or state.get("current_draft") or "")
    extraction_entities: list[dict[str, Any]] = []
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("node_id") or "").strip()
        if not node_id or node_id in existing_ids:
            continue
        if str(raw.get("node_type") or "") != NodeType.CHARACTER.value:
            continue
        extraction_entities.append(raw)

    def _extraction_update(raw_ent: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        member = _compile_from_extraction(state, context, raw_ent, chapter_content)
        if member is None:
            return None
        return member.node_id, {
            "update_mode": "fill_empty",
            "member": member.model_dump(mode="json"),
        }

    _pe_workers = max(1, min(len(extraction_entities), get_settings().side_slot_fill_max_workers))
    if extraction_entities:
        with ThreadPoolExecutor(max_workers=_pe_workers) as pool:
            futs = [pool.submit(_extraction_update, raw_ent) for raw_ent in extraction_entities]
            for fut in as_completed(futs):
                out = fut.result()
                if out:
                    updates_by_node[out[0]] = out[1]

    story = context.story_repository.get_story(state["story_id"]) or {}
    cast_rows = story.get("cast_json") or []
    cast_index: dict[str, StoryCastMemberStored] = {}
    for raw in cast_rows:
        if not isinstance(raw, dict):
            continue
        try:
            member = StoryCastMemberStored.model_validate(raw)
        except Exception:
            continue
        cast_index[member.node_id] = member

    now_iso = datetime.now(UTC).isoformat()
    evolution_jobs: list[tuple[CharacterEvolutionRequest, StoryCastMemberStored]] = []
    for raw_req in list(state.get("pending_cast_evolutions") or []):
        if not isinstance(raw_req, dict):
            continue
        try:
            req = CharacterEvolutionRequest.model_validate(raw_req)
        except Exception:
            continue
        current_member = cast_index.get(req.node_id)
        if current_member is None:
            continue
        evolution_jobs.append((req, current_member))

    def _evolution_update(job: tuple[CharacterEvolutionRequest, StoryCastMemberStored]) -> tuple[str, dict[str, Any]]:
        req, current_member = job
        new_personality = (req.new_personality or "").strip()
        new_speech_style = (req.new_speech_style or "").strip()
        if (not new_personality or not new_speech_style) and not isinstance(context.llm_client, MockLLMClient):
            prompt = _build_evolution_prompt(state, current_member, req, chapter_content)
            profile = augment_profile_system_prompt(
                get_profile("profile_expander"), context.output_language
            )
            for _ in range(2):
                try:
                    enriched, _ = context.llm_client.invoke_json(prompt, _ExpandedProfile, profile)
                    if not new_personality:
                        new_personality = (enriched.personality or "").strip()
                    if not new_speech_style:
                        new_speech_style = (enriched.speech_style or "").strip()
                    break
                except Exception:
                    continue
        if not new_personality:
            new_personality = current_member.personality
        if not new_speech_style:
            new_speech_style = current_member.speech_style
        milestone = CharacterArcMilestone(
            trigger_event_id=(req.trigger_event_id or "").strip(),
            trigger_event_summary=(req.trigger_event_summary or req.reason or "").strip(),
            chapter_id=int(state.get("chapter_id") or 0),
            old_personality=current_member.personality,
            new_personality=new_personality,
            old_speech_style=current_member.speech_style,
            new_speech_style=new_speech_style,
            source=req.source,
            reason=req.reason,
            updated_at=now_iso,
        )
        member_payload = current_member.model_copy(
            update={
                "personality": new_personality,
                "speech_style": new_speech_style,
                "arc_history": [*current_member.arc_history, milestone],
            }
        ).model_dump(mode="json")
        return req.node_id, {
            "update_mode": "evolution",
            "member": member_payload,
            "milestone": milestone.model_dump(mode="json"),
        }

    _evo_workers = max(1, min(len(evolution_jobs), get_settings().side_slot_fill_max_workers))
    if evolution_jobs:
        with ThreadPoolExecutor(max_workers=_evo_workers) as pool:
            futs = [pool.submit(_evolution_update, job) for job in evolution_jobs]
            for fut in as_completed(futs):
                nid, payload = fut.result()
                updates_by_node[nid] = payload

    return {
        "pending_cast_updates": list(updates_by_node.values()),
        "pending_cast_evolutions": [],
        "last_agent": "profile_expander",
        "resume_from": "profile_expander",
    }
