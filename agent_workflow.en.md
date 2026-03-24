# Agent Workflow (English)

> Traditional Chinese version: [agent_workflow.md](./agent_workflow.md).

## Purpose

Describe how NovelBuilder runs **single-chapter generation**: agent order, shared state, review gates, HITL, and newer behavior around **B-story resolution**, **entity binding**, and the **post-polish extraction gate**. Written for engineers; not a line-by-line code map.

## Two tiers

### 1. Macro planning

Splits the story into **volumes** with nested **anchors**, normalized into SQLite `anchors` (with `volume_id`).

**Contract**: **3–5** anchors per volume; each `chapter_target` must fall inside that volume’s chapter range. The backend pads or truncates as needed.

**Inputs**: title, premise, bible, target total words.

**Outputs**:

- Per-volume title, summary, chapter span, word budget  
- Per-anchor title, description, target state, target chapter  
- **Cast**: at least one **protagonist** and optional **supporting**; stable `node_id` (`{story_id}_mc_01`…), stored in `stories.cast_json` and `protagonist_character_id`  
- **Graph**: old `{story_id}_mc_*` character nodes cleared; one **CHARACTER** node per cast member  
- **Optional B-story seeds**: `initial_b_stories` from macro output are **merged** into `stories.bible_json.active_b_stories` (deduped by id)

**Chapter entry**: `start_run_chapter` loads **`active_b_stories`** from bible, computes **`distance_to_anchor`**, and applies **`normalized_length_min/max`** from **`target_word_count`** (length SSOT).

**In-chapter navigation**: director/planner prompts use a sliding window of upcoming anchors; full unfinished list remains in state.

### 2. Chapter workflow

Runs from **`director`** through review and polish, then **`extraction_gate`**, **`b_story_resolve`**, and **`state_updater`** for atomic persistence.

## Chapter pipeline (happy path)

1. **`director`** — chapter type, B-line hint, POV, epoch, tone, narrative direction  
2. **`graph_rag`** — bible / graph / vector / recent chapter text  
3. **`planner`** — ground truth + surface script + **`proposed_new_nodes` (≤3)** + **`new_active_b_stories` (≤2, optional)** + **`target_word_count`** (length bounds written to state)  
4. **`plan_supervisor`** — outline review (**Hard** vs **Soft**; genesis / B-line core omissions are **Hard**)  
5. **`author`** — writes prose; second LLM pass emits **`author_extraction_surface_hints`** (exact substrings per `node_id`)  
6. **`draft_supervisor`** — length SSOT; mandatory entities checked **deterministically** against **`author_extraction_surface_hints`**  
7. **`reader`** — literary pass  
8. **`extraction_gate`** — extract + **`remap_planned_entities` (R1/R5)** + **`validate_mandatory_planned_nodes` (R6)** (uses author surface hints)  
   - On failure → back to **`author`** (`MISSING_MANDATORY_ENTITY_MAPPING`-style feedback)  
   - On success → **`pending_chapter_extraction`**, then B-story resolution  
9. **`b_story_resolve`** — LLM outputs `resolution_analysis`, `resolution_evidence_event_ids`, `resolved_b_stories`; evidence ids must be **substantiated in structured extraction** (R2c)  
10. **`state_updater`** — builds mutations/vectors from **`pending_chapter_extraction`**; after SQLite chapter write, updates bible: **remove resolved B-stories**, **merge pending seeds**

Supervisors and reader can loop backward; too many retries → HITL. Extraction-gate failures also append **`draft_feedback`**.

## Important state fields

Besides chapter id, contexts, outline, and drafts:

- **Narrative mode**: `chapter_type`, `b_story_directive`, `new_elements_to_introduce`  
- **B-stories**: `active_b_stories` (from bible), **`pending_b_story_additions`** (from planner; applied on successful commit)  
- **Genesis**: `distance_to_anchor`, `planned_graph_nodes`  
- **Length SSOT**: `target_word_count`, `normalized_length_min`, `normalized_length_max`  
- **Warnings**: `plan_warnings` (includes merged **`soft_warnings`** from plan supervisor)  
- **Extraction**: `author_extraction_surface_hints`, `pending_chapter_extraction`, `b_story_resolution`, `post_polish_route`, extraction-gate feedback when failing  

## Agent roles (summary)

| Node | Role |
|------|------|
| **Director** | POV, epoch, direction, `chapter_type` / B-line fields; **`normalize_director_output`** may force WORLD_BUILDING + default B-line text when far from anchor and pool is empty. |
| **Graph RAG** | Assembles retrieval context only. |
| **Planner** | Executable outline, **`proposed_new_nodes`**, **`new_active_b_stories`**, word target; backend stores **`planned_graph_nodes`** and length bounds. |
| **Plan supervisor** | **Hard** for missing genesis/B-line core, timeline/space breaks, etc.; **Soft** warnings must not hide issues that would starve downstream payloads. |
| **Author** | Surface script only; **`mandatory_new_entities`** instructs aligned cues for extractors. |
| **Draft supervisor** | Length from SSOT; **R4** keyword/presence checks on mandatory entities. |
| **Reader** | Literary score; not the length gatekeeper. |
| **Prose polish** | Cosmetic pass; next resume target **`extraction_gate`**. |
| **Extraction gate** | Extract → remap (R5 log on skip) → **R6** mandatory planned ids must appear as entity `node_id`s. |
| **B story resolve** | CoT + evidence event ids + resolved ids; backend validates against **extraction-substantiated** event ids only. |
| **State updater** | Prefers **`pending_chapter_extraction`**; same commit path updates graph, vector, SQLite chapter, and **bible `active_b_stories`**. |

## HITL

Same as before: plan loop, draft loop, outline edit, draft edit, state injection. **`resume_from`** may be **`extraction_gate`** or **`b_story_resolve`** for post-polish recovery.

## Per-chapter artifacts

- SQLite: chapter text, run state, step logs, HITL, transactions, **updated `bible_json.active_b_stories`**  
- Graph / vector: driven by finalized extraction aligned with events  
- Workflow state: continuity for the next chapter  

## Principles

- Director/planner own direction and executable outline; author sees only the safe task card.  
- **R4** (draft) vs **R6** (gate): readable alignment vs structural entity ids after extract/remap.  
- **R5** allows fallback NPC ids when remap is uncertain; **mandatory** planned nodes cannot pass R6 as phantoms.  
- **B-story retirement** must cite **substantiated extraction event ids** so SQLite bible and graph updates stay causally aligned.  
