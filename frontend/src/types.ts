/** Optional structured core cast for macro compile; empty keeps LLM-only roster. */
export type StoryCastSeedEntry = {
  canonical_name: string;
  role?: "protagonist" | "supporting" | "antagonist" | null;
  short_hint?: string;
};

export type StoryInput = {
  title: string;
  premise: string;
  /** Filled after macro compile; creation sends `{}`. */
  bible: Record<string, unknown>;
  macro_author_notes?: string;
  cast_seed?: StoryCastSeedEntry[];
  target_total_words: number;
  plan_retry_limit: number;
  draft_loop_retry_limit: number;
};

export type ImportMergeMode = "replace" | "merge";

export type StorySettingsExportPayload = {
  kind: "story_settings";
  version: 1;
  story: StoryInput;
};

export type StoryPatch = {
  title?: string;
  premise?: string;
  target_total_words?: number;
  plan_retry_limit?: number;
  draft_loop_retry_limit?: number;
  macro_author_notes?: string;
  cast_seed?: StoryCastSeedEntry[];
};

export type VolumePlan = {
  volume_id: string;
  title: string;
  summary: string;
  chapter_start: number;
  chapter_end: number;
  target_volume_words?: number;
};

export type Anchor = {
  anchor_id: string;
  story_id?: string;
  volume_id?: string;
  title: string;
  description: string;
  chapter_target: number;
  target_state: Record<string, unknown>;
  priority?: number;
};

export type CastMember = {
  node_id: string;
  canonical_name: string;
  role: string;
  short_bio?: string;
  aliases?: string[];
  age?: string;
  motivation?: string;
  core_motivation?: string;
  core_value?: string;
  speech_style?: string;
  fatal_flaw?: string;
  quirks_and_habits?: string;
};

/** PUT /api/stories/:id/macro-plan — full replace (manual edit). */
export type MacroPlanPutBody = {
  bible: Record<string, unknown>;
  volumes: VolumePlan[];
  anchors: Array<{
    anchor_id: string;
    volume_id: string;
    title?: string;
    description?: string;
    target_state?: Record<string, unknown>;
    chapter_target: number;
    priority?: number;
  }>;
  cast: CastMember[];
  protagonist_character_id?: string | null;
};

export type MacroCompileExportPayload = {
  kind: "macro_compile";
  version: 1;
  macro_plan: MacroPlanPutBody;
};

/** Single-file export: story fields + optional macro plan (legacy kinds remain importable). */
export type StoryProjectBundlePayload = {
  kind: "story_project_bundle";
  version: 1;
  story?: StoryInput;
  macro_plan?: MacroPlanPutBody;
};

export type MacroCompileData = {
  story_id: string;
  bible?: Record<string, unknown>;
  macro_author_notes?: string;
  cast_seed?: StoryCastSeedEntry[];
  volumes: VolumePlan[];
  anchors: Anchor[];
  cast?: CastMember[];
  protagonist_character_id?: string;
};

/** Row from GET /api/stories (lightweight list). */
export type StoryListItem = {
  story_id: string;
  title: string;
  premise: string;
  target_total_words: number;
  created_at: string;
};

/** GET /api/stories/:id/macro-snapshot — same as macro compile payload plus compiled flag. */
export type MacroSnapshotResponse = MacroCompileData & {
  compiled: boolean;
  macro_compile_status?: string;
  macro_compile_updated_at?: string;
  macro_compile_error?: string;
};

/** GET /api/stories/:id — full story row fields for Configuration + lock flag. */
export type StoryDetailResponse = StoryInput & {
  story_id: string;
  configuration_locked: boolean;
  macro_author_notes: string;
  macro_compile_status?: string;
  macro_compile_updated_at?: string;
  macro_compile_error?: string;
};

export type WorkflowRun = {
  run_id: string;
  story_id: string;
  chapter_id: number;
  status: string;
  current_agent?: string;
  requires_hitl: boolean;
  hitl_reason: string;
  hitl_decision_mode: string;
};

export type WorkflowStep = {
  step_id: string;
  step_index: number;
  agent_name: string;
  status: string;
  input_payload_json: Record<string, unknown>;
  output_payload_json: Record<string, unknown>;
  masked_payload_json: Record<string, unknown>;
  token_usage: number;
  latency_ms: number;
  route_decision: string;
};

export type WorkflowPayload = {
  run: WorkflowRun;
  state: Record<string, unknown>;
  steps: WorkflowStep[];
};

export type GraphNodeType =
  | "CHARACTER"
  | "PERSONA"
  | "EPOCH"
  | "LOCATION"
  | "ITEM"
  | "EVENT"
  | "CONCEPT"
  | "RULE"
  | string;

export type GraphNode = {
  node_id: string;
  node_type: GraphNodeType;
  canonical_name?: string;
  aliases?: string[];
  /** Free-form labels; node_type stays an enum on the backend. */
  tags?: string[];
  /** JSON-compatible key-value extras from extraction / graph store. */
  metadata?: Record<string, unknown>;
  description?: string;
  /** LOCATION: ambient state text from backend defaults. */
  environmental_condition?: string;
  title?: string;
  order_index?: number;
  is_alive?: boolean;
  is_accessible?: boolean;
  item_status?: string;
  /** ITEM: single-instance lore flag. */
  is_unique?: boolean;
  /** RULE: violation cost text from graph. */
  penalty?: string | null;
  /** RULE: false when rule no longer applies. */
  is_active?: boolean;
  [key: string]: unknown;
};

export type GraphEdge = {
  edge_id?: string;
  source_id: string;
  target_id: string;
  relation_type?: string;
  valid_epoch?: string;
  start_event_id?: string;
  end_event_id?: string;
  is_truth?: boolean;
  is_public?: boolean;
  known_by?: string[];
  holder?: string[];
  context_details?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type GraphSnapshot = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type ChapterSummary = {
  chapter_key: string;
  story_id: string;
  chapter_id: number;
  title: string;
  status: string;
};

export type ChapterContent = {
  chapter_key: string;
  story_id: string;
  chapter_id: number;
  title: string;
  content: string;
  status: string;
};
