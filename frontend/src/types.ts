export type StoryInput = {
  title: string;
  premise: string;
  bible: Record<string, unknown>;
  target_total_words: number;
  plan_retry_limit: number;
  draft_loop_retry_limit: number;
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
};

export type MacroCompileData = {
  story_id: string;
  volumes: VolumePlan[];
  anchors: Anchor[];
  cast?: CastMember[];
  protagonist_character_id?: string;
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

export type GraphSnapshot = {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
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
