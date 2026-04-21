from __future__ import annotations

import json

from app.core.config import get_settings
from app.domain.schema import (
    BStorySeed,
    BStoryType,
    EventLink,
    EventLinkOrigin,
    EventLinkType,
    EventOutline,
    NodeType,
    PlannerOutput,
    ProposedCharacterProfile,
    ProposedGraphNode,
)
from app.domain.state import SafePlannerPayload
from app.services.llm import MockLLMClient
from app.services.workflow.chapter_words import clamp_chapter_word_count
from app.services.workflow.context import WorkflowContext
from app.services.workflow.constants import (
    LOCAL_ENFORCED_RULES_CONTEXT_CAP,
    PLANNER_BIBLE_CONTEXT_CAP,
    PLANNER_CONTINUITY_NOTE_MAX_CHARS,
    PLANNER_CONTINUITY_NOTE_MAX_ITEMS,
    PLANNER_ENTITY_NAME_MAX_CHARS,
    PLANNER_ENTITY_NAME_MAX_ITEMS,
    PLANNER_GRAPH_CONTEXT_CAP,
    PLANNER_PREVIOUS_CHAPTER_SUMMARY_CAP,
    PLANNER_PREVIOUS_NARRATIVE_CAP,
    PLANNER_PRIOR_FEEDBACK_MAX_ITEMS,
    PLANNER_RECENT_CHAPTER_CONTEXT_CAP,
    PLANNER_UPCOMING_ANCHORS_JSON_CAP,
    PLANNER_VECTOR_CONTEXT_CAP,
    PLANNER_VOLUME_SUMMARY_CAP,
)
from app.services.workflow.event_normalization import (
    coalesce_over_fragmented_events,
    normalize_beats,
    normalize_event_ai_flags,
    normalize_event_ids,
)
from app.services.workflow.masking import build_planner_payload
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import freedom_adjusted_profile, get_profile


def _mock_author_safe_continuity_notes(raw: list[str]) -> list[str]:
    """Mock path: drop vector unresolved-thread lines; keep other continuity strings."""
    safe: list[str] = []
    for line in raw or []:
        text = (line or "").strip()
        if not text:
            continue
        if "未解線索" in text or "章未解" in text or "unresolved thread" in text.casefold():
            continue
        safe.append(text)
        if len(safe) >= 4:
            break
    return safe


def _clip(text: str, max_len: int) -> str:
    if not text:
        return text
    return text[:max_len] if len(text) > max_len else text


def _clip_note_lines(notes: list[str]) -> list[str]:
    out: list[str] = []
    for raw in (notes or [])[:PLANNER_CONTINUITY_NOTE_MAX_ITEMS]:
        line = (raw or "").strip()
        if not line:
            continue
        out.append(_clip(line, PLANNER_CONTINUITY_NOTE_MAX_CHARS))
    return out


def _clip_entity_names(names: list[str]) -> list[str]:
    out: list[str] = []
    for raw in (names or [])[:PLANNER_ENTITY_NAME_MAX_ITEMS]:
        n = (raw or "").strip()
        if not n:
            continue
        out.append(_clip(n, PLANNER_ENTITY_NAME_MAX_CHARS))
    return out


def run_planner(state: dict, context: WorkflowContext) -> tuple[dict, dict, int, int]:
    settings = get_settings()
    story = context.story_repository.get_story(state["story_id"]) or {}
    volumes = context.story_repository.list_volumes(state["story_id"])
    payload = build_planner_payload(state, story=story, volumes=volumes)
    prompt = _build_planner_prompt(payload)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(
            freedom_adjusted_profile(
                "planner",
                ai_freedom_level=str(state.get("ai_freedom_level") or "balanced"),
                outline_binding_mode=str(state.get("outline_binding_mode") or "ABSENT"),
            ),
            context.output_language,
        )
        structured_output, llm_result = context.llm_client.invoke_json(prompt, PlannerOutput, profile)
        normalized_events = normalize_event_ai_flags(list(structured_output.ground_truth_events))
        normalized_events = coalesce_over_fragmented_events(normalized_events)
        id_result = normalize_event_ids(int(state["chapter_id"]), normalized_events)
        normalized_beats, normalized_beat_outlines = normalize_beats(
            list(structured_output.must_include_beats),
            list(structured_output.must_include_beat_outlines),
        )
        structured_output.ground_truth_events = id_result.events
        structured_output.must_include_beats = normalized_beats
        structured_output.must_include_beat_outlines = normalized_beat_outlines
        clamped = clamp_chapter_word_count(
            structured_output.target_word_count,
            settings.chapter_word_min,
            settings.chapter_word_max,
        )
        nodes = list(structured_output.proposed_new_nodes)[:2]
        seeds = list(structured_output.new_active_b_stories)[:2]
        out = structured_output.model_dump(mode="json")
        out["proposed_new_nodes"] = [n.model_dump(mode="json") if isinstance(n, ProposedGraphNode) else n for n in nodes]
        out["new_active_b_stories"] = [
            s.model_dump(mode="json") if isinstance(s, BStorySeed) else s for s in seeds
        ]
        out["target_word_count"] = clamped
        out["ground_truth_events"] = [event.model_dump(mode="json") for event in id_result.events]
        out["must_include_beats"] = normalized_beats
        out["must_include_beat_outlines"] = [beat.model_dump(mode="json") for beat in normalized_beat_outlines]
        return out, payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms

    llm_result = context.llm_client.invoke(prompt)
    anchor_hint = payload.target_anchor_id or "no specific anchor"
    continuity_hint = f"Picking up from the prior chapter: {payload.previous_chapter_summary}." if payload.previous_chapter_summary else ""
    continuity_notes = " ".join(payload.continuity_notes[:2])
    start_location = payload.last_known_location or "continue prior scene"
    end_location = payload.last_known_location or "current action locus"
    boundary_rule = (
        f"This chapter may only resolve as far as {end_location}; any move into a new full scene, interior, or new mission beat must wait for the next chapter."
    )
    mock_target = clamp_chapter_word_count(
        payload.default_chapter_words,
        settings.chapter_word_min,
        settings.chapter_word_max,
    )
    mock_nodes: list[ProposedGraphNode] = []
    for raw in (payload.new_elements_to_introduce or [])[:2]:
        need, reason, label = "", "", ""
        if isinstance(raw, dict):
            need = str(raw.get("need") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            label = need or reason
        else:
            label = str(raw or "").strip()
        if not label:
            continue
        mock_nodes.append(
            ProposedGraphNode(
                node_id=f"char_gen_{state['chapter_id']}_{len(mock_nodes) + 1}",
                node_type=NodeType.CHARACTER,
                role=(need or label)[:80],
                canonical_name=(need or label)[:80],
                writing_brief=reason or "Render this character with recognizable on-page traits.",
                mandatory=False,
                character_profile=ProposedCharacterProfile(
                    core_motivation="Survive the current situation while advancing personal stakes.",
                    fatal_flaw="Under pressure, overreacts or says the wrong thing.",
                    core_value="Acts from personal conviction.",
                    speech_style="Short, spoken, low adjective load.",
                    quirks_and_habits="Avoids eye contact or slows speech when tense.",
                    short_bio=(need or label)[:500],
                ),
            )
        )
    mock_b_stories: list[BStorySeed] = []
    req = payload.request_new_b_story
    if isinstance(req, dict) and str(req.get("type") or "").strip():
        raw_t = str(req.get("type")).strip().upper().replace("BSTORYTYPE.", "")
        bt = BStoryType.UNKNOWN
        if raw_t in BStoryType.__members__:
            bt = BStoryType[raw_t]
        mock_b_stories.append(
            BStorySeed(
                id=f"b_req_{state['chapter_id']}_01",
                desc=str(req.get("purpose") or "New B-story opened per Director request.")[:800],
                type=bt,
                resolution_condition="Verifiable forward motion or irreversible consequence, with a trackable next-step hook by chapter end.",
            )
        )
    output = PlannerOutput(
        ground_truth_events=[
            EventOutline(
                event_id=f"event_ch{state['chapter_id']}_01",
                description=f"The protagonist at {start_location} receives a new clue pointing toward {anchor_hint} and takes new action.",
                caused_by_event_id=None,
                links=[],
            ),
            EventOutline(
                event_id=f"event_ch{state['chapter_id']}_02",
                description=f"Under pressure the protagonist makes a risky push that changes the situation; chapter ends at {end_location}.",
                links=[
                    EventLink(
                        target_event_id=f"event_ch{state['chapter_id']}_01",
                        link_type=EventLinkType.TEMPORAL,
                        origin=EventLinkOrigin.HUMAN_GROUND_TRUTH,
                    )
                ],
            ),
        ],
        narrative_script=(
            f"{continuity_hint}"
            f"Open by continuing the situation at {start_location}; let the protagonist engage a new clue or new friction, "
            f"then push the scene forward. Any scene change needs explicit movement or transition. "
            f"The chapter must advance toward {anchor_hint}, not merely retell the prior chapter. "
            f"{continuity_notes}"
        ),
        target_word_count=mock_target,
        chapter_start_location=start_location,
        author_goal="Deliver one clear plot advance this chapter and push the protagonist into the next move.",
        must_include_beats=[
            "The protagonist takes a concrete action—not only observation or reminiscence.",
            "At least one reader-perceptible discovery or piece of evidence appears this chapter.",
            "If the location changes, show movement or transition before the new place.",
            "By chapter end, situation, knowledge, or risk must clearly differ from the opening.",
        ],
        must_include_beat_outlines=[
            {"text": "The protagonist takes a concrete action—not only observation or reminiscence.", "is_ai_invention": False},
            {"text": "At least one reader-perceptible discovery or piece of evidence appears this chapter.", "is_ai_invention": False},
            {"text": "If the location changes, show movement or transition before the new place.", "is_ai_invention": False},
            {"text": "By chapter end, situation, knowledge, or risk must clearly differ from the opening.", "is_ai_invention": False},
        ],
        reader_visible_facts=[
            f"Readers should feel the chapter advancing toward {anchor_hint}.",
        ],
        reader_unresolved_questions=[
            "The full truth is still unrevealed; readers only see partial clues and surface contradictions.",
        ],
        private_facts_or_secret_actions=[
            "If there are secret actions or private observations, keep them non-public—do not write them as common knowledge.",
        ],
        ending_state_shift="By chapter end the protagonist is closer to the truth and closer to new danger than at the opening.",
        chapter_end_location_hint=end_location,
        ending_boundary_rule=boundary_rule,
        forbidden_next_scene_actions=[
            "Do not move into a new scene or new location after the chapter's effective end position.",
            "Do not resolve a hanging thread early, or complete meetings, entries, or hard scene changes meant for the next chapter.",
        ],
        forbidden_reveals=[
            "Do not directly reveal underlying truths before their reveal window.",
            "Do not add unrelated new contraptions, mysteries, or world rules beyond this chapter's mission.",
        ],
        author_safe_continuity_notes=_mock_author_safe_continuity_notes(payload.continuity_notes),
        proposed_new_nodes=mock_nodes,
        new_active_b_stories=mock_b_stories,
    )
    dumped = output.model_dump(mode="json")
    dumped["proposed_new_nodes"] = [n.model_dump(mode="json") for n in mock_nodes[:2]]
    dumped["new_active_b_stories"] = [s.model_dump(mode="json") for s in mock_b_stories[:2]]
    return dumped, payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms


def _build_planner_prompt(payload: SafePlannerPayload) -> str:
    upcoming_json = json.dumps(payload.upcoming_unachieved_anchors, ensure_ascii=False)
    upcoming_json = _clip(upcoming_json, PLANNER_UPCOMING_ANCHORS_JSON_CAP)
    prior_fb = (payload.prior_feedback or [])[-PLANNER_PRIOR_FEEDBACK_MAX_ITEMS:]
    prev_events = [event.model_dump(mode="json") for event in payload.previous_attempt_ground_truth_events]
    tail_line = (
        f"- previous_chapter_tail_excerpt: {_clip(payload.previous_chapter_tail_excerpt, PLANNER_PREVIOUS_CHAPTER_SUMMARY_CAP)}\n"
        if payload.previous_chapter_tail_excerpt
        else ""
    )
    ap = (payload.author_chapter_plan or "").strip()
    bind = (payload.outline_binding_mode or "ABSENT").strip().upper()
    freedom = (payload.ai_freedom_level or "balanced").strip().lower()
    author_plan_block = ""
    if ap:
        if bind == "FULL":
            author_plan_block = (
                "## Human chapter outline (outline_binding_mode=FULL)\n"
                "- When ai_freedom_level=strict: explicit human text is **binding**—do not rewrite it; only structure into ground_truth_events / must_include_beats.\n"
                "- In wild/balanced: still do not delete human-written beats; invent only in blanks and set is_ai_invention=true on the related event/beat schema row.\n"
                f"{_clip(ap, 1600)}\n\n"
            )
        elif bind == "PARTIAL":
            author_plan_block = (
                "## Human chapter outline (outline_binding_mode=PARTIAL)\n"
                "- The author supplied fragments; preserve what is written and complete an executable plan; mark non-explicit inventions with is_ai_invention=true on beats/events.\n"
                f"{_clip(ap, 1600)}\n\n"
            )
        else:
            author_plan_block = f"## Human chapter outline\n{_clip(ap, 1600)}\n\n"
    brief = (payload.director_state_brief or "").strip()
    brief_block = ""
    if brief:
        brief_block = f"## Director state brief (state_operational_brief)\n{_clip(brief, 1200)}\n\n"
    mode_block = (
        "## Planning mode\n"
        f"- ai_freedom_level: {freedom}\n"
        f"- outline_binding_mode: {bind}\n"
        "- If the human outline clearly contradicts bible/graph evidence, obey canon in planning and mentally flag for Logic_Alignment (do not silently contradict canon).\n\n"
    )
    pace = (payload.this_chapter_pacing_limit or "").strip()
    pacing_block = ""
    if pace:
        pacing_block = (
            "## [HARD] Chapter pacing brake (human-specified)\n"
            f"{_clip(pace, 800)}\n"
            "- When pacing limits are listed: **do not** write the series/main-arc finale or one-shot resolution of the core mystery inside this chapter's "
            "narrative_script, ground_truth_events, or must_include_beats; stay at suspense, probe, partial pivot, or escalating crisis. Violating this fails the task.\n\n"
        )
    loc_rules = (payload.local_enforced_rules_context or "").strip()
    local_rules_block = ""
    if loc_rules:
        local_rules_block = (
            "## Local absolute laws (hard; override generic world description)\n"
            f"{_clip(loc_rules, LOCAL_ENFORCED_RULES_CONTEXT_CAP)}\n\n"
        )
    return (
        "Using the safe payload below, produce ground-truth outline plus surface narrative_script for the chapter.\n\n"
        f"{mode_block}"
        f"{pacing_block}"
        f"{brief_block}"
        f"{author_plan_block}"
        f"{local_rules_block}"
        "## Word budget and chapter scope (required)\n"
        f"- default_chapter_words: {payload.default_chapter_words} (reference starting point only—not a volume quota or hard allocation)\n"
        f"- Hard bounds for target_word_count: {payload.chapter_word_min} ~ {payload.chapter_word_max} (backend clamps out-of-range values)\n"
        "- You MUST output integer `target_word_count` sized to this chapter's **ground_truth_events complexity, scene changes, dialogue/action load, and count of must_include_beats**;\n"
        "  the budget must give beats room in prose without obvious padding.\n"
        "- Avoid extreme mismatch (tiny outline + huge words, or many beats + tiny words)—downstream supervisors will reject.\n\n"
        "## Continuity context\n"
        f"- previous_chapter_summary: {_clip(payload.previous_chapter_summary, PLANNER_PREVIOUS_CHAPTER_SUMMARY_CAP)}\n"
        f"{tail_line}"
        f"- recent_chapter_context: {_clip(payload.recent_chapter_context, PLANNER_RECENT_CHAPTER_CONTEXT_CAP)}\n"
        f"- last_known_location: {payload.last_known_location}\n"
        f"- continuity_notes: {_clip_note_lines(list(payload.continuity_notes))}\n"
        f"- recent_entities: {_clip_entity_names(list(payload.recent_entity_names))}\n\n"
        "## Chapter narrative direction\n"
        f"- directive: {payload.narrative_directive}\n"
        f"- active_epoch: {payload.active_epoch_id}\n"
        f"- pov_character: {payload.pov_character_id}\n"
        f"- current_volume_title: {payload.current_volume_title}\n"
        f"- current_volume_summary: {_clip(payload.current_volume_summary, PLANNER_VOLUME_SUMMARY_CAP)}\n"
        f"- current_anchor_id: {payload.target_anchor_id}\n"
        f"- current_anchor_title: {payload.current_anchor_title}\n"
        f"- current_anchor_description: {payload.current_anchor_description}\n"
        "- upcoming_unachieved_anchors: sliding window of nearest unfinished anchors (id/title/chapter_target); "
        "**treat current_anchor as this chapter's primary target**—others are pacing only; do not script concrete bridges or endings for far future anchors.\n"
        f"- upcoming_unachieved_anchors: {upcoming_json}\n\n"
        "## World and retrieval context\n"
        f"- story_premise: {payload.story_premise}\n"
        f"- bible_context: {_clip(payload.bible_context, PLANNER_BIBLE_CONTEXT_CAP)}\n"
        f"- graph_context: {_clip(payload.graph_context, PLANNER_GRAPH_CONTEXT_CAP)}\n"
        f"- vector_context: {_clip(payload.vector_context, PLANNER_VECTOR_CONTEXT_CAP)}\n\n"
        "## Prior plan attempt (for revision)\n"
        f"- previous_attempt_ground_truth_events: {prev_events}\n"
        f"- previous_attempt_narrative_script: {_clip(payload.previous_attempt_narrative_script, PLANNER_PREVIOUS_NARRATIVE_CAP)}\n\n"
        "## Prior planning feedback\n"
        f"- prior_feedback: {prior_fb}\n\n"
        "## Director directives (chapter type and creation)\n"
        f"- chapter_type: {payload.chapter_type}\n"
        f"- b_story_directive: {payload.b_story_directive or ''}\n"
        f"- new_elements_to_introduce: {payload.new_elements_to_introduce}\n"
        f"- request_new_b_story: {payload.request_new_b_story}\n"
        f"- distance_to_anchor: {payload.distance_to_anchor}\n"
        f"- active_b_stories: {json.dumps(payload.active_b_stories, ensure_ascii=False)[:800]}\n"
        f"- lore_mysteries_progression: {json.dumps(payload.lore_mysteries_progression, ensure_ascii=False)[:1000]}\n"
        f"- ending_vibe_cooldown_constraint: {json.dumps(payload.ending_vibe_cooldown_constraint, ensure_ascii=False)}\n"
        f"- writing_note_rules: {json.dumps(payload.writing_note, ensure_ascii=False)[:800]}\n"
        "- If b_story_directive is non-empty, weave it into narrative_script; include at least one must_include_beat that is mundane/sensory detail unrelated to mainline puzzle-solving.\n"
        "- writing_note_rules are fixed craft constraints for this project—follow them and do not contradict them.\n"
        "- If this chapter uses memory acquisition / flashback, take the next pending stage from lore_mysteries_progression and materialize it in the matching "
        "proposed_new_nodes / must_include_beats for new_elements_to_introduce—do not replay an old stage.\n"
        "- If ending_vibe_cooldown_constraint.active=true, end-of-chapter planning must honor required_vibe and avoid forbidden_vibes.\n"
        "- New important-entity quota: 0 by default; if you must add new important entities, at most 2 and only with clear plot necessity. Otherwise reuse existing cast/locations/props.\n"
        "- For each new_elements_to_introduce item, emit a proposed_new_nodes row (node_id, node_type, role, canonical_name, writing_brief); "
        "if node_type is CHARACTER, also emit character_profile (core_motivation, core_value, fatal_flaw, speech_style, quirks_and_habits, short_bio, age) "
        "with semantics aligned to macro-compiled cast. At most 2 nodes, and schedule interaction in ground_truth_events.\n"
        "- If request_new_b_story is non-empty: instantiate it in new_active_b_stories (aligned type, concrete desc) or explain why existing active_b_stories absorbs it instead.\n"
        "- new_active_b_stories: if opening a **new** independent B-story this chapter (stable id), at most 2 rows each with id, desc, type, **resolution_condition** (objective completion test); "
        "type is a BStoryType among FETCH_QUEST / RELATIONSHIP_DRAMA / ENVIRONMENTAL_HAZARD / LORE_DISCOVERY / INTERNAL_CONFLICT. "
        "Otherwise output []. After approval it merges into bible—do not duplicate existing active_b_stories ids.\n\n"
        "## Output requirements\n"
        "- If previous_attempt_ground_truth_events or previous_attempt_narrative_script is present, this is a revision pass—not a blank-slate rewrite.\n"
        "- When only part of the prior plan failed, keep sound event chains and chapter direction; fix only the feedback-flagged segments, events, or location fields.\n"
        "- Do not replace the whole chapter spine because of a single rejection point unless the prior version is globally broken—keep the same core mission and causal thrust.\n"
        "- This chapter must add new causal advancement, not merely restate the previous chapter.\n"
        "- Do not repackage completed trades, discoveries, dialogues, or conflicts from the prior chapter as 'new' events here.\n"
        "- Each ground_truth_events row must encode a new state change for this chapter—not a recap masquerading as events.\n"
        "- Event granularity (hard): default-merge continuous fights or continuous dialogue into one macro EVENT; "
        "split only when goals, dominant actors, scene location, or outcome phase changes.\n"
        "- Do not explode one continuous action beat into micro-events (e.g. dodge/punch/counter/roll); summarize as one event.\n"
        "- Each ground_truth_events item must emit nested links[] only (no separate top-level event_links array). "
        "Each link requires target_event_id and link_type in {CAUSAL, TEMPORAL}. "
        "Do not infer CAUSAL from sequence alone; if only order is known, use TEMPORAL.\n"
        "- narrative_script must clearly separate what continues from the prior chapter versus new actions, discoveries, conflict, and end-of-chapter shift this chapter.\n"
        "- You MUST output chapter_start_location; if no hard cut, default-continue last_known_location.\n"
        "- If chapter_start_location differs from last_known_location, ground_truth_events and narrative_script must first plan movement, extraction, travel, scene change, or other extractable transition.\n"
        "- Also produce the author-facing safe task card without leaking hidden ground-truth.\n"
        "- author_goal: 1–2 sentences stating the dramaturgical job the lead author must complete this chapter.\n"
        "- must_include_beats: 3–5 concrete, observable, writable surface beats.\n"
        "- reader_visible_facts: facts readers should clearly know by chapter end, directly observable from prose—no secret actions smuggled in as 'facts'.\n"
        "- reader_unresolved_questions: open questions or unknowns to preserve after this chapter—use information asymmetry for tension without giving answers.\n"
        "- private_facts_or_secret_actions: secret moves, private discoveries, surveillance, or internal plotting that exist this chapter but are not public common knowledge—feeds extractor is_public=false; not shown raw to author.\n"
        "- ending_state_shift: one sentence on how end-state must differ from opening state.\n"
        "- chapter_start_location: one sentence for where POV/lead is at chapter open; if continuing, state the prior chapter's end position.\n"
        "- chapter_end_location_hint: one sentence for where POV/lead effectively is at chapter end; if no move, still state where they remain.\n"
        "- ending_boundary_rule: 1–2 sentences for the farthest stop this chapter may reach and what must wait for next chapter.\n"
        "- forbidden_next_scene_actions: 2–4 lines this chapter must not cross (entries, meetings, hard cuts to next location, premature reveals, etc.).\n"
        "- Spatial/boundary consistency (hard): mandatory: true rows in proposed_new_nodes (characters/items/locations) and creation nodes implied by Director new_elements_to_introduce "
        "must be physically/temporally plausible **before** the end stop defined by ending_boundary_rule; narrative_script, ground_truth_events, and must_include_beats must support observable presence or interaction inside that boundary. "
        "Never require the Author to stage entity contact or scenes that belong after the boundary (e.g. forbidden entries/meetings/arrivals already banned). "
        "If an entity can only appear after the boundary, do not mark it mandatory this chapter—defer to next chapter or relax/move ending_boundary_rule to reconcile.\n"
        "- forbidden_reveals: 2–4 boundaries the author must not cross early or invent; do not embed the actual secret answers—only describe the guardrails.\n"
        "- The author task card is surface-writable only—do not expose ground-truth not yet observed by characters or readers.\n"
        "- If there is movement, must_include_beats, reader_visible_facts, chapter_start_location, chapter_end_location_hint, and ending_boundary_rule must agree.\n"
        "- author_safe_continuity_notes: 0–4 short lines for the lead author's continuity reminders only.\n"
        "  * continuity_notes may include RAG/extraction 'unresolved thread' lines with proper names or future plot the reader/POV should not rightfully know—**do not paste them verbatim to the author**.\n"
        "  * Rewrite under pov_character, previous_chapter_summary, recent_chapter_context, ground_truth_events, and reader_visible_facts into surface-suspense the character can feel now; output [] if nothing is safe.\n"
        "  * You may anonymize (e.g. 'Is an outside faction tracking them?') or defer to reader_unresolved_questions—do not introduce new unapproved proper names in this field.\n"
    )
