# English agent prompts + story output language (revised)

## Scope lock: supported languages (v1)

Implement **three** story output modes only:

- `en` — English  
- `zh-Hant` — Traditional Chinese  
- `zh-Hans` — Simplified Chinese  

No `ja` / `ko` in v1. UI dropdown lists exactly these three.

---

## Sanity checks (do not regress)

### 1. JSON keys and enums are immutable

When translating [`profiles.py`](backend/app/services/workflow/profiles.py) and [`extraction.py`](backend/app/services/workflow/extraction.py) (and any user prompt that references the schema):

- **Never** rename JSON keys in instructions (e.g. keep `node_type`, not “node category”).
- **Never** rename or paraphrase **enum values** or **relation_type** literals in prose. Example: translate the *sentence* around `LOCATED_IN`, but the token **`LOCATED_IN`** must appear exactly as today (all caps, unchanged).

Prompts should explicitly say things like: *You must return JSON using the exact key names and enum strings required by the schema.*

### 2. Internal vs external natural language (no “English brain” leakage)

Blind spot: not every agent writes **story prose**. The same `output_language` must govern **chapter outlines**, **supervisor / reader feedback and critiques**, **alignment notes**, **extractor summaries and `context_details`**, and any other **human-readable string values** returned to the app — otherwise HITL and graph UIs fill with English while the novel stays Chinese.

**Canonical contract block** (append via `augment_profile_system_prompt`; English wording, `{label}` interpolated):

> CRITICAL LANGUAGE REQUIREMENT: While this system prompt is in English, ALL generated natural-language content—including the actual story prose, character dialogues, chapter outlines, internal feedback/critiques, and summaries—MUST be written entirely in {label}. Only JSON keys and ENUM values must remain in exact English as defined by the schema.

This explicitly covers **feedback** and **outline** text, not only “正文”.

### 3. Proper nouns — no translation or transliteration

Blind spot: with an English system prompt, models may **translate or pinyin-ize** user-provided names (e.g.「弈」→ “Yi”,「諾亞」→ “Noah”), causing graph / continuity drift.

Add to the **same** contract block:

> Do NOT translate or transliterate user-provided proper nouns (character names, locations, special terms). Keep them in their original language as provided in the context.

(Together with §2 this subsumes the older “retain original language” one-liner.)

### 4. Single contract for all NL JSON strings — no extractor split

**Do not** special-case the extractor to English while the author writes Chinese.

- When `story.output_language` is `zh-Hant`, **every** free-text JSON value listed in §2 (including extraction summaries / `context_details`) should match that language so GraphRAG, vectors, and author-facing panels stay consistent.

Enum fields and structural tokens stay English as today.

### 5. `StoryPatch` optional + repository must not null out

- In [`schema.py`](backend/app/domain/schema.py): `StoryPatch.output_language` must be **`Optional[Literal["en", "zh-Hant", "zh-Hans"]] = None`** (or equivalent). Partial PATCH bodies from older clients may omit the field.
- In [`story_repository.py`](backend/app/repositories/sqlite/story_repository.py) `patch_story`: if `output_language` is **`None`**, **do not** emit `output_language = ?` in the UPDATE — leave the DB row unchanged. Never write SQL `NULL` into `output_language` from a missing PATCH key.

---

## Phased execution order (mandatory)

Large blast radius, low logic complexity — follow this order to avoid getting stuck mid-refactor.

### Step 1 — Data + API + UI only (no prompt translation)

- SQLite: `output_language` column (`TEXT NOT NULL DEFAULT 'zh-Hant'`) via [`database.py`](backend/app/repositories/sqlite/database.py) `_ensure_column`.
- [`schema.py`](backend/app/domain/schema.py): `StoryInput.output_language` required with default `zh-Hant` and `Literal["en","zh-Hant","zh-Hans"]`; **`StoryPatch.output_language` optional (`None` = omit)** per §5.
- [`story_repository.py`](backend/app/repositories/sqlite/story_repository.py): create / patch / get + `get_story` setdefault for safety; **patch skips `output_language` when `None`**.
- [`service.py`](backend/app/services/workflow/service.py): `macro_compile` rebuilt `StoryInput` includes `output_language`.
- Frontend: [`types.ts`](frontend/src/types.ts), [`StorySetupForm.tsx`](frontend/src/features/story-setup/StorySetupForm.tsx), [`api.ts`](frontend/src/api.ts) — dropdown only.
- **Do not** change any LLM prompt strings in this step. Run tests; behavior should match pre-change defaults (`zh-Hant`).

### Step 2 — Language interceptor only

- Add [`output_language.py`](backend/app/services/workflow/output_language.py) (or equivalent): `augment_profile_system_prompt` appends the **canonical contract** from §2–§3 (CRITICAL LANGUAGE REQUIREMENT + proper-noun rule).
- Extend [`WorkflowContext`](backend/app/services/workflow/context.py) with `output_language`; populate in [`WorkflowService._build_context`](backend/app/services/workflow/service.py) from run → story.
- Wire **augmentation** at every `invoke_text` / `invoke_json` / profile-using `invoke` path **and** macro compile’s `macro_planner` profile — **without** yet translating existing Chinese prompts to English (profiles may still be Chinese briefly; the appended English contract is still valid).
- Small unit test: augmented `system_prompt` ends with / contains expected English fragments for a given code.

### Step 3 — The Great Translation

- Translate all LLM-facing strings to English in the file checklist from the original plan (`profiles.py`, `author.py`, `planner.py`, `director.py`, supervisors, `logic_alignment.py`, `extraction.py`, `anchor_service.py` macro user prompt, other nodes, `MockLLMClient` sample text).
- Throughout: preserve **keys**, **enum values**, and **tokens like `LOCATED_IN`** verbatim in instructional text.

### Step 4 — Test healing

- Fix pytest assertions that matched Chinese substrings or mock output.
- Re-run full backend (and affected frontend) tests.

---

## Implementation todos (tracked)

1. **schema-db-ui** — Step 1: SQLite + Pydantic (`StoryInput` default + optional `StoryPatch`) + repository patch skip-on-None + frontend dropdown + macro `StoryInput` rebuild; **no** prompt edits.
2. **context-augment** — Step 2: `WorkflowContext.output_language`, `augment_profile_system_prompt` (full contract), wire all LLM profile usages + macro; unit test on suffix.
3. **translate-prompts** — Step 3: English prompts with sacred keys/enums/tokens preserved.
4. **test-healing** — Step 4: update tests and mocks.

---

## Non-goals (unchanged)

HITL UI labels, `writing_preamble.py` pacing hints, OpenAPI-only `Field(description=...)` unless they are embedded in model prompts.
