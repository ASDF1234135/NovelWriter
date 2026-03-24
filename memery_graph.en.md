# Memory Graph (English)

> The repository filename stays **`memery_graph.md`** (historical spelling). This document is the **memory layering** overview.  
> 繁體中文版：[memery_graph.md](./memery_graph.md)。

## Purpose

Explain how NovelBuilder splits **memory** across stores, what each layer owns, and how a **finalized chapter** flows through the **extraction gate** before graph/vector/SQLite writes, including sync with **`bible_json` B-story pools**. Architecture and risks—not an exhaustive API list.

## Three layers

| Layer | Role |
|------|------|
| **SQLite** | System of record: workflow, chapter text, HITL, transactions; **story bible (incl. `active_b_stories`)** |
| **Graph Store** | Structured world: characters, places, items, events, relations |
| **Vector Store** | Semantic retrieval: summaries, excerpts, threads, entity hints |

## SQLite highlights

### Stories

- `story_id`, title, premise, **`bible_json`**, targets, cast, retry limits, etc.  
- **`bible_json.active_b_stories`**: open subplot threads (`id`, `desc`, …). **Macro compile** may seed entries; a **successful chapter commit** may **merge new threads** or **remove resolved ids** in the **same transactional block** as graph/SQLite writes to avoid split brain.

### Other tables

**Volumes**, **anchors**, **chapters**, **workflow_runs**, **workflow_steps**, **hitl_actions**, **state_transactions**—unchanged in intent: execution trace, debugging, replay.

## Graph Store

### Node kinds (summary)

`CHARACTER`, `PERSONA`, `LOCATION`, `ITEM`, `CONCEPT`, `EVENT`, `EPOCH`, etc.

### EVENT

Planner **`ground_truth_events.event_id`** values become **EVENT** nodes during **`state_updater`**, alongside extracted entities/relations. **B-story resolution** evidence ids must be **substantiated in structured post-polish extraction** (entity `node_id` or relation endpoints matching those ids) so SQLite does not retire a subplot while the graph never captured the closing beat (**R2c / causal disconnect**).

### Edges

`is_truth` / `is_public` (**truth ≠ public**), `known_by` / `holder`, **`start_event_id` / `end_event_id`** for lifecycle (including **LOCATED_IN** retirement). Relation families and location lifecycle behave as before.

## Vector Store

After **`state_updater`**, extraction output is split into documents (`text_chunk` + `metadata`). In the current pipeline, extraction usually comes from **`pending_chapter_extraction`** produced at **`extraction_gate`** (after R6), aligned with the polished draft.

## Per-chapter persistence order (updated)

1. Author → draft / reader → **prose polish** (final text for extraction).  
2. **`extraction_gate`**: extract → remap → **R6**; on failure, no downstream commit.  
3. **`b_story_resolve`**: uses **structured extraction** + CoT + evidence event ids.  
4. **`state_updater`**: graph mutations → vector docs → SQLite chapter row → **in the same try**, update **`bible_json.active_b_stories`** (remove **validated** resolves, merge **`pending_b_story_additions`**).  
5. Mark **`state_transaction`** committed (or failed without partial bible side effects).

## Continuity inputs

`graph_rag` still rebuilds `previous_chapter_summary`, `recent_chapter_context`, `last_known_location`, `continuity_notes`, `recent_entity_names` from vector + graph + SQLite (same ideas as the legacy doc).

## Risk notes (extra)

1. **POV / graph node id mismatch** still poisons queries and location continuity.  
2. **`is_public` misuse** still breaks Air-Gap.  
3. **Phantom mandatory nodes**—if draft (R4) and remap (R5) disagree, **R6** after extraction blocks commit and sends the run back to the author.  
4. **Bible vs graph causal split**—retire B-stories only when evidence ids are **substantiated in extraction**.  
5. **Vector vs graph drift** still causes continuity bugs.

## Mental model

- **SQLite**: ledger + chapter bodies + **B-story pool (bible)**  
- **Graph**: world state and causal structure  
- **Vector**: recall index  

With the **post-polish extraction gate** aligned, the system is more likely to ship chapters that are writable, memorable, spoiler-safe, free of empty shell ids, and consistent on subplot lifecycle.
