from __future__ import annotations

import json

from app.domain.schema import AuthorExtractionHintsOutput, AuthorExtractionSurfaceEntry, AuthorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.constants import LOCAL_ENFORCED_RULES_CONTEXT_CAP
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_author_payload
from app.services.workflow.output_language import (
    augment_profile_system_prompt,
    chapter_heading_line,
    heading_first_line_matches_chapter,
    strip_leading_chapter_heading_line,
)
from app.services.workflow.profiles import freedom_adjusted_profile, get_profile
from app.services.workflow.utils import chapter_content_length

_MAX_HINTS_CHAPTER_CHARS = 28000


def _filter_surface_hints_to_exact_substrings(chapter_content: str, hints: AuthorExtractionHintsOutput) -> list[dict]:
    """Drop any surface string not occurring verbatim in chapter_content."""
    out: list[dict] = []
    for ent in hints.entries:
        nid = (ent.node_id or "").strip()
        if not nid:
            continue
        ok = [s for s in ent.surface_forms if isinstance(s, str) and s and s in chapter_content]
        out.append({"node_id": nid, "surface_forms": ok})
    return out


def _mandatory_node_ids_from_payload(payload) -> set[str]:
    rows = getattr(payload, "mandatory_new_entities", None) or []
    out: set[str] = set()
    for row in rows:
        nid = str(getattr(row, "node_id", "") or "").strip()
        if nid:
            out.add(nid)
    return out


def _find_missing_mandatory_hint_ids(filtered_hints: list[dict], mandatory_ids: set[str]) -> list[str]:
    if not mandatory_ids:
        return []
    by_id = {
        str(h.get("node_id", "")).strip(): [s for s in (h.get("surface_forms") or []) if isinstance(s, str) and s]
        for h in filtered_hints
        if isinstance(h, dict) and str(h.get("node_id", "")).strip()
    }
    missing: list[str] = []
    for nid in sorted(mandatory_ids):
        if not by_id.get(nid):
            missing.append(nid)
    return missing


def _build_extraction_hints_prompt(chapter_content: str, state: dict, payload) -> str:
    excerpt = chapter_content[:_MAX_HINTS_CHAPTER_CHARS]
    planned = list(state.get("planned_graph_nodes") or [])
    mandatory = getattr(payload, "mandatory_new_entities", None) or []
    mand_ids = [{"node_id": m.node_id, "role": m.role, "canonical_name": m.canonical_name} for m in mandatory]
    instructions = {
        "task": "author_extraction_surface_hints",
        "rules": [
            "Output JSON: entries is an array; each item has node_id and surface_forms (string array).",
            "Only handle node_id values tied to this chapter's plan or mandatory list (see planned_graph_nodes and mandatory_new_entities).",
            "Each string in surface_forms must be an exact substring of the chapter body—same characters, punctuation, and whitespace; "
            "no paraphrase, summary, punctuation edits, or synonym swaps.",
            "If a node_id has no verbatim surface form in the text, that entry's surface_forms must be [].",
            "Do not invent strings that do not appear in the chapter text.",
        ],
        "planned_graph_nodes": planned[:24],
        "mandatory_new_entities": mand_ids,
        "chapter_excerpt": excerpt,
        "excerpt_was_truncated": len(chapter_content) > len(excerpt),
    }
    return json.dumps(instructions, ensure_ascii=False)


def _build_retry_extraction_hints_prompt(chapter_content: str, state: dict, payload, missing_ids: list[str]) -> str:
    base = json.loads(_build_extraction_hints_prompt(chapter_content, state, payload))
    base["retry_required_for_node_ids"] = missing_ids
    base["rules"].append(
        "Retry mode: for each retry_required_for_node_ids value, return at least one exact in-text surface form when possible."
    )
    return json.dumps(base, ensure_ascii=False)


def _format_local_enforced_rules_for_author(payload) -> str:
    raw = str(getattr(payload, "local_enforced_rules_context", "") or "").strip()
    if not raw:
        return ""
    clipped = raw[:LOCAL_ENFORCED_RULES_CONTEXT_CAP]
    if len(raw) > LOCAL_ENFORCED_RULES_CONTEXT_CAP:
        clipped += "…"
    return f"## Local absolute rules (hard; override conflicting hints in narrative_script)\n{clipped}\n"


def _format_author_safe_continuity(notes: list[str]) -> str:
    cleaned = [(line or "").strip() for line in notes if (line or "").strip()]
    if not cleaned:
        return "(none)"
    return "\n".join(f"- {line}" for line in cleaned)


def run_author(state: dict, context: WorkflowContext) -> tuple[dict, dict, int, int]:
    payload = build_author_payload(state)
    _len_lang = str(state.get("story_output_language") or context.output_language or "")
    prompt = _build_author_prompt(payload)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(
            freedom_adjusted_profile(
                "author",
                ai_freedom_level=str(state.get("ai_freedom_level") or "balanced"),
                outline_binding_mode=str(state.get("outline_binding_mode") or "ABSENT"),
            ),
            context.output_language,
        )
        llm_result = context.llm_client.invoke_text(prompt, profile)
        chapter_content = _ensure_chapter_heading(
            state["chapter_id"], llm_result.content, context.output_language
        )
        token_usage = llm_result.token_usage
        latency_ms = llm_result.latency_ms
        chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
            state["chapter_id"],
            payload,
            chapter_content,
            context,
            profile,
        )
        token_usage += repair_tokens
        latency_ms += repair_latency

        compression_round = 0
        while chapter_content_length(chapter_content, _len_lang) > payload.normalized_length_max and compression_round < 2:
            compression_round += 1
            over_length = chapter_content_length(chapter_content, _len_lang) - payload.normalized_length_max
            compression_prompt = _build_compression_prompt(payload, chapter_content, over_length)
            compression_result = context.llm_client.invoke_text(compression_prompt, profile)
            compressed_content = _ensure_chapter_heading(
                state["chapter_id"], compression_result.content, context.output_language
            )
            if compressed_content.strip() == chapter_content.strip():
                break
            chapter_content = compressed_content
            token_usage += compression_result.token_usage
            latency_ms += compression_result.latency_ms
            chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
                state["chapter_id"],
                payload,
                chapter_content,
                context,
                profile,
            )
            token_usage += repair_tokens
            latency_ms += repair_latency

        expansion_round = 0
        while chapter_content_length(chapter_content, _len_lang) < payload.normalized_length_min and expansion_round < 2:
            expansion_round += 1
            missing_length = payload.normalized_length_min - chapter_content_length(chapter_content, _len_lang)
            continuation_prompt = _build_expansion_prompt(payload, chapter_content, missing_length)
            continuation_result = context.llm_client.invoke_text(continuation_prompt, profile)
            continuation = strip_leading_chapter_heading_line(continuation_result.content)
            if not continuation:
                break
            chapter_content = f"{chapter_content.rstrip()}\n\n{continuation.strip()}"
            token_usage += continuation_result.token_usage
            latency_ms += continuation_result.latency_ms
            chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
                state["chapter_id"],
                payload,
                chapter_content,
                context,
                profile,
            )
            token_usage += repair_tokens
            latency_ms += repair_latency

        hints_profile = augment_profile_system_prompt(get_profile("author_extraction_hints"), context.output_language)
        hints_prompt = _build_extraction_hints_prompt(chapter_content, state, payload)
        mandatory_ids = _mandatory_node_ids_from_payload(payload)
        hints_diagnostics: dict[str, object] = {}
        try:
            hints_struct, hints_res = context.llm_client.invoke_json(hints_prompt, AuthorExtractionHintsOutput, hints_profile)
            token_usage += hints_res.token_usage
            latency_ms += hints_res.latency_ms
        except Exception:
            hints_struct = AuthorExtractionHintsOutput(entries=[])
        filtered = _filter_surface_hints_to_exact_substrings(chapter_content, hints_struct)
        missing_mandatory = _find_missing_mandatory_hint_ids(filtered, mandatory_ids)
        if missing_mandatory:
            retry_prompt = _build_retry_extraction_hints_prompt(chapter_content, state, payload, missing_mandatory)
            try:
                retry_struct, retry_res = context.llm_client.invoke_json(
                    retry_prompt, AuthorExtractionHintsOutput, hints_profile
                )
                token_usage += retry_res.token_usage
                latency_ms += retry_res.latency_ms
                retry_filtered = _filter_surface_hints_to_exact_substrings(chapter_content, retry_struct)
                retry_missing = _find_missing_mandatory_hint_ids(retry_filtered, mandatory_ids)
                if len(retry_missing) <= len(missing_mandatory):
                    filtered = retry_filtered
                    missing_mandatory = retry_missing
            except Exception:
                pass
        if missing_mandatory:
            hints_diagnostics = {
                "missing_mandatory_hint_node_ids": missing_mandatory,
                "expected_mandatory_node_ids": sorted(mandatory_ids),
            }
        surface_models = [AuthorExtractionSurfaceEntry(node_id=e["node_id"], surface_forms=e["surface_forms"]) for e in filtered]
        output = AuthorOutput(
            chapter_content=chapter_content,
            word_count=chapter_content_length(chapter_content, _len_lang),
            extraction_surface_hints=surface_models,
        )
        dumped = output.model_dump(mode="json")
        dumped["author_extraction_surface_hints"] = dumped.pop("extraction_surface_hints", [])
        if hints_diagnostics:
            dumped["author_extraction_hints_diagnostics"] = hints_diagnostics
        return dumped, payload.model_dump(mode="json"), token_usage, latency_ms

    llm_result = context.llm_client.invoke(prompt)
    base_paragraphs = [
        f"He still carries the prior chapter's situation: {payload.previous_chapter_summary}"
        if payload.previous_chapter_summary
        else "",
        f"Tail mood/position reference (do not paste verbatim): {payload.previous_chapter_tail_excerpt}"
        if payload.previous_chapter_tail_excerpt
        else "",
        f"Last locked position after the prior chapter: {payload.last_known_location}" if payload.last_known_location else "",
        f"Opening position for this chapter: {payload.chapter_start_location}" if payload.chapter_start_location else "",
        f"Primary author_goal: {payload.author_goal}" if payload.author_goal else "",
        f"Must-include beats: {'; '.join(payload.must_include_beats)}" if payload.must_include_beats else "",
        f"Safe continuity hints: {'; '.join(payload.author_safe_continuity_notes)}"
        if payload.author_safe_continuity_notes
        else "",
        f"Key entities in play: {'; '.join(payload.recent_entity_names)}" if payload.recent_entity_names else "",
        f"Reader-visible facts after this chapter: {'; '.join(payload.reader_visible_facts)}"
        if payload.reader_visible_facts
        else "",
        f"Reader should still wonder about: {'; '.join(payload.reader_unresolved_questions)}"
        if payload.reader_unresolved_questions
        else "",
        f"End-of-chapter location hint: {payload.chapter_end_location_hint}" if payload.chapter_end_location_hint else "",
        "He stops at tonight's safe perimeter; one more step would spill into the next arc."
        if payload.ending_boundary_rule
        else "",
        "Some moves must wait—doing them now would jump the story too early." if payload.forbidden_next_scene_actions else "",
        "The street is quiet; he cannot afford to stall. Another slow minute and the trail goes cold.",
        "He handles what is in front of him before choosing the next move—emotion does not drive the feet.",
        "Every line, glance, and pause on-site could shove him into worse trouble.",
        f"{payload.narrative_script}",
        "He does not forecast too far ahead; he grips the change already in his hands.",
        f"By chapter end the board should shift: {payload.ending_state_shift}"
        if payload.ending_state_shift
        else "By chapter end he is pushed forward; the risk is higher than at sunrise.",
        "This chapter cannot idle in place—people and stakes must land somewhere new before the last line.",
    ]
    chapter_content = f"{chapter_heading_line(state['chapter_id'], context.output_language)}\n\n"
    while chapter_content_length(chapter_content, _len_lang) < payload.normalized_length_min:
        chapter_content += "\n\n" + "\n".join(paragraph for paragraph in base_paragraphs if paragraph)
    output = AuthorOutput(
        chapter_content=chapter_content,
        word_count=chapter_content_length(chapter_content, _len_lang),
        extraction_surface_hints=[],
    )
    dumped = output.model_dump(mode="json")
    dumped["author_extraction_surface_hints"] = []
    return dumped, payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms


def _format_mandatory_new_entities(payload) -> str:
    rows = getattr(payload, "mandatory_new_entities", None) or []
    if not rows:
        return "(No mandatory new-entity seeds for this chapter.)"
    lines: list[str] = []
    for m in rows:
        lines.append(
            f"- node_id={m.node_id} | role={m.role or '(unset)'} | display_name={m.canonical_name or '(unset)'}\n"
            f"  writing_brief: {m.writing_brief or 'Give recognizable traits.'}\n"
            f"  hard requirement: the prose must contain at least one surface form aligned with role or display_name for downstream extraction."
        )
    return "\n".join(lines)


def _format_general_world_lore(payload) -> str:
    text = str(getattr(payload, "general_world_lore", None) or "").strip()
    return text if text else "(none)"


def _format_active_character_profiles(payload) -> str:
    rows = list(getattr(payload, "active_character_profiles", None) or [])
    if not rows:
        return "(none)"
    lines: list[str] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("canonical_name") or "").strip() or "(unnamed)"
        current_p = str(row.get("current_personality") or "").strip() or "(unset)"
        current_s = str(row.get("current_speech_style") or "").strip() or "(unset)"
        past = str(row.get("past_personality_reference") or "").strip() or "(no history)"
        lines.append(
            f"- {name} | current_personality={current_p} | current_speech_style={current_s}\n"
            f"  past_personality_reference={past}"
        )
    return "\n".join(lines) if lines else "(none)"


def _format_beat_outlines(payload) -> str:
    rows = list(getattr(payload, "must_include_beat_outlines", None) or [])
    if not rows:
        return "\n".join(f"- text={beat}" for beat in (getattr(payload, "must_include_beats", None) or []) if beat) or "(none)"
    lines: list[str] = []
    for row in rows:
        text = str(getattr(row, "text", "") or "").strip()
        if not text:
            continue
        is_ai = bool(getattr(row, "is_ai_invention", False))
        scope = str(getattr(row, "invention_scope", "") or "").strip() or "(unset)"
        lines.append(f"- text={text} | is_ai_invention={str(is_ai).lower()} | invention_scope={scope}")
    return "\n".join(lines) if lines else "(none)"


def _build_author_prompt(payload) -> str:
    draft_feedback_text = _format_feedback_entries(payload.draft_feedback, "draft")
    reader_feedback_text = _format_feedback_entries(payload.reader_feedback, "reader")
    previous_attempt_draft = _truncate_previous_attempt_draft(payload.previous_attempt_draft)
    tail_excerpt_block = (
        f"Previous chapter tail excerpt (timing/mood/position only; do not paste verbatim into this chapter):\n"
        f"{payload.previous_chapter_tail_excerpt}\n\n"
        if payload.previous_chapter_tail_excerpt
        else ""
    )
    freedom = str(getattr(payload, "ai_freedom_level", None) or "balanced")
    bind = str(getattr(payload, "outline_binding_mode", None) or "ABSENT")
    return f"""
You are this chapter's ghostwriter: write only from the surface narrative_script and beats—do not invent extra truth.
Do not add characters, twists, or dialogue motives outside must_include_beats / narrative_script; expand only where schema marks is_ai_invention=true.
Output novel prose only—no JSON, no field labels, no meta commentary.

## Runtime (system)
- ai_freedom_level: {freedom}
- outline_binding_mode: {bind}

## Targets
Tone/mood: {payload.tone_direction}
Target word count (reference): {payload.target_word_count}
Normalized length floor: at least {payload.normalized_length_min}
Normalized allowed band: {payload.normalized_length_min} - {payload.normalized_length_max}

## Length adjustment mode
length_adjustment: {payload.length_adjustment}
- EXPAND: prior draft too short—add new actions, dialogue, reactions, or plot push.
- COMPRESS: prior draft too long—keep core events/beats, cut repeated waiting, repeated interior monologue, dead-end atmosphere padding.
- NONE: normal chapter writing, still stay inside the allowed band.

## Author world / craft lore (hard)
{_format_general_world_lore(payload)}
This block is a hard constraint for this chapter; if it conflicts with generic style advice, obey this lore.

## Absolute chapter laws (hard; treat as physics)
{str(getattr(payload, "safe_chapter_rules", "") or "").strip() or "(no hard rules)"}
Character actions and any system/game beats must never violate the laws above.

{_format_local_enforced_rules_for_author(payload)}

## Naming discipline (show, don't label)
1. Name only when needed: skip new proper nouns unless the entity recurs, drives decisions, or is a core beat anchor.
2. If you must name, stay sparse: avoid stacking multiple new parallel names in one chapter; keep names short—no "quote + subtitle + colon" packaging.
3. Describe before you label: prefer observable light, sound, touch, outcomes before slapping a term on something.
4. Unless a mandatory seed entity requires it, avoid invented move codenames, system jargon, or location codes—express effects in plain prose.

Primary author_goal:
{payload.author_goal}

## Continuity pack

### Hard bridge from prior chapter prose
1. This chapter **continues** time: the opening must move **forward** (new action, dialogue, observation)—do not stall retelling the prior ending.
2. Use "previous summary" and "tail excerpt" only for causal/positional/mood grounding—**do not** paste whole sentences from them as this chapter's opening.
3. Do not repeat the tail excerpt as your first paragraph; at most one very short transition, then **new** sentences absent from those sources.
4. If you echo a prior beat, **rewrite** wording and specifics; avoid 10+ consecutive characters identical to summary/tail (ignore punctuation/space).

Previous chapter summary:
{payload.previous_chapter_summary}

{tail_excerpt_block}
Last known position (end of prior chapter):
{payload.last_known_location}

Opening position (this chapter):
{payload.chapter_start_location}

Continuity notes (POV-filtered; safe for the author; empty means no extra hints):
{_format_author_safe_continuity(payload.author_safe_continuity_notes)}

Recent important entities:
{payload.recent_entity_names}

## Character voice reference
{_format_active_character_profiles(payload)}
Rules:
- Obey current_personality and current_speech_style for present action.
- past_personality_reference is only for flashbacks, retellings, or historical contrast scenes.

## This chapter's narrative direction
Surface narrative_script:
{payload.narrative_script}

## Must-do beats
must_include_beats_with_schema_flags:
{_format_beat_outlines(payload)}

## Mandatory new-entity seeds (hard; must be extractable)
{_format_mandatory_new_entities(payload)}

Ending state shift:
{payload.ending_state_shift}

End-of-chapter location hint:
{payload.chapter_end_location_hint}

## Hard boundaries
Farthest you may write:
{payload.ending_boundary_rule}

Forbidden early beats:
{payload.forbidden_next_scene_actions}

## Reader knowledge delta
After this chapter the reader should know:
{payload.reader_visible_facts}

After this chapter the reader should still not know:
{payload.reader_unresolved_questions}

## Forbidden early reveals
{payload.forbidden_reveals}

## Prior draft (for revision passes)
{previous_attempt_draft}

## Revision priority
1) Satisfy author_goal, must_include_beats, ending_state_shift, chapter_end_location_hint, ending_boundary_rule.
2) Fix hard issues in draft_feedback (broken chain, inconsistent locations, boundary overshoot, POV leaks).
3) Only if (1)(2) are met, apply reader_feedback polish (wording, rhythm, repetition, tension).
4) If reader_feedback conflicts with (1)(2), ignore reader_feedback.

## Historical rejection notes (logic)
{draft_feedback_text}

## Reader feedback
{reader_feedback_text}

Reader feedback is literary polish only—it cannot override the locked event chain, beats, end location, or hard boundaries.

## Writing checklist
1) If a prior draft exists, revise—do not nuke working material untouched by feedback.
2) Finish all must-do beats before cosmetic polish; never delete key events to please readers.
3) Add at least one clear on-page push: new action, discovery, or conflict.
4) End state must differ from the opening and match ending_state_shift.
5) If the prior draft already satisfied beats and draft_feedback is silent, patch locally—do not swap in a different event set.
6) draft_feedback is hard; reader_feedback is soft.
7) Use knowledge asymmetry for suspense—never violate forbidden_reveals.
8) If characters move, make leave/arrive/stay explicit for extraction.
9) No off-task new puzzles, systems, or world rules; no resolving hidden ground-truth on your own.
10) Plain, short sentences; concrete action and dialogue first.
11) Avoid purple stacks of metaphor; do not open every paragraph with mood-only staging.
12) Length checks use normalized counts; for EXPAND/short drafts add real scenes/dialogue, not repetition padding.
13) chapter_end_location_hint and hard boundaries are ceilings, not suggestions.
14) If you execute any forbidden_next_scene_actions beat, you have jumped to the next chapter—rewrite the ending.
15) For localized feedback (ending overshoot, missing beat), patch the affected spans only—do not rewrite the whole front half.
16) For COMPRESS/long drafts, cut redundant patrol loops, idle waiting, spiral interior monologue, and repeated mood lines—never drop must_include_beats, ending_state_shift, or end location.
17) Honor the four bridge rules: no near-copy of summary/tail; the opening must be new forward motion.
18) For unfamiliar mechanisms/objects/areas, show perceivable effects before naming; do not substitute jargon for description.
19) Without plot need, avoid inventing quoted/colon-heavy proprietary names; if you must name, keep density low.
""".strip()


def _format_feedback_entries(entries: list[dict], source: str) -> str:
    if not entries:
        return "(none)"
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        attempt = entry.get("attempt", index)
        violation = entry.get("violation", [])
        suggestion = entry.get("suggestion", "")
        message = entry.get("message", "")
        if source == "draft":
            lines.append(
                f"- rejection attempt {attempt} | violation={violation} | suggestion={suggestion} | message={message}"
            )
            missing_struct = entry.get("missing_mandatory_entities")
            if isinstance(missing_struct, list) and missing_struct:
                sub: list[str] = []
                for row in missing_struct:
                    if not isinstance(row, dict):
                        continue
                    nid = row.get("node_id", "")
                    note = row.get("note", "")
                    if note == "not_in_planned":
                        sub.append(f"  · {nid} (not listed in planner table)")
                    else:
                        sub.append(
                            f"  · node_id={nid} | node_type={row.get('node_type', '')} | "
                            f"planned_name={row.get('canonical_name', '')!r} | role={row.get('role', '')!r}"
                        )
                if sub:
                    lines.append("  missing entities (structured):\n" + "\n".join(sub))
        else:
            lines.append(
                f"- reader review attempt {attempt} | score={entry.get('score', '')} | "
                f"suggestion={entry.get('suggestion', '')} | message={message}"
            )
    return "\n".join(lines)


def _truncate_previous_attempt_draft(text: str, max_chars: int = 7000) -> str:
    if not text:
        return "(none)"
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[Prior draft truncated to first {max_chars} characters for revision context.]"


def _build_expansion_prompt(payload, chapter_content: str, missing_length: int) -> str:
    return f"""
Continue the SAME chapter body—do not rewrite the opening and do not summarize prior text.
Normalized length is still short by at least {missing_length}.
Continue from the last paragraph with new plot, dialogue, action, and reaction—no padding, no repeating already-stated facts.
Keep plain, short sentences; avoid heavy metaphor.
Do not cross hard boundaries; if must_include_beats are satisfied, extend only with reactions/aftermath in the same scene—no new scene launch.
End-of-chapter location hint: {payload.chapter_end_location_hint}
Hard boundary: {payload.ending_boundary_rule}
Forbidden early beats: {payload.forbidden_next_scene_actions}
If any beats below are unfinished, prioritize them:
{payload.must_include_beats}

Current body:
{chapter_content}
""".strip()


def _build_compression_prompt(payload, chapter_content: str, excess_length: int) -> str:
    return f"""
Compress the SAME chapter body—do not turn it into summary and do not delete core events.
Normalized length exceeds the cap; shorten by at least {excess_length}.
Keep event order, must_include_beats, ending state, and end location—cut redundant waiting, patrol loops, spiral interior monologue, repeated setting lines, and dead sentences.
Rewrite as tighter prose in plain short sentences.
End-of-chapter location hint: {payload.chapter_end_location_hint}
Hard boundary: {payload.ending_boundary_rule}
Forbidden early beats: {payload.forbidden_next_scene_actions}
Beats you must keep:
{payload.must_include_beats}

Current body:
{chapter_content}
""".strip()


def _repair_boundary_if_needed(chapter_id: int, payload, chapter_content: str, context: WorkflowContext, profile) -> tuple[str, int, int]:
    return chapter_content, 0, 0


def _extract_boundary_cues(action: str) -> list[str]:
    raw_parts = [part.strip() for part in action.replace("，", " ").replace("、", " ").replace("。", " ").split() if part.strip()]
    cues: list[str] = []
    for part in raw_parts:
        normalized = part
        for prefix in ("不要", "不可", "不得", "避免", "本章", "提前"):
            normalized = normalized.removeprefix(prefix)
        normalized = normalized.strip()
        if len(normalized) >= 3:
            cues.append(normalized)
    return cues


def _ensure_chapter_heading(chapter_id: int, content: str, output_language: str) -> str:
    stripped = content.strip()
    lines = stripped.splitlines()
    if lines and heading_first_line_matches_chapter(lines[0], chapter_id):
        return stripped
    head = chapter_heading_line(chapter_id, output_language)
    return f"{head}\n\n{stripped}"
