import type {
  AiFreedomLevel,
  ChapterContent,
  ChapterSummary,
  GraphSnapshot,
  MacroCompileData,
  MacroPlanPutBody,
  MacroSnapshotResponse,
  StoryDetailResponse,
  StoryInput,
  StoryListItem,
  StoryPatch,
  WorkflowPayload,
  WritingPreambleResponse,
} from "./types";

const API_BASE = "http://localhost:8000/api";

function formatErrorBody(text: string): string {
  if (!text) return "Request failed";
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) {
      return j.detail
        .map((item) => (typeof item === "object" && item !== null && "msg" in item ? String((item as { msg: string }).msg) : String(item)))
        .join("; ");
    }
  } catch {
    /* not JSON */
  }
  return text;
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(formatErrorBody(text));
  }
  return response.json() as Promise<T>;
}

export async function createStory(payload: StoryInput): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/stories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function fetchStories(): Promise<StoryListItem[]> {
  const response = await fetch(`${API_BASE}/stories`);
  return parseJson(response);
}

export async function fetchStoryDetail(storyId: string): Promise<StoryDetailResponse> {
  const response = await fetch(`${API_BASE}/stories/${encodeURIComponent(storyId)}`);
  return parseJson(response);
}

export async function patchStory(storyId: string, patch: StoryPatch): Promise<StoryDetailResponse> {
  const response = await fetch(`${API_BASE}/stories/${encodeURIComponent(storyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson(response);
}

export async function deleteStory(storyId: string): Promise<{ ok: boolean; story_id: string }> {
  const response = await fetch(`${API_BASE}/stories/${encodeURIComponent(storyId)}`, {
    method: "DELETE",
  });
  return parseJson(response);
}

export async function fetchMacroSnapshot(storyId: string): Promise<MacroSnapshotResponse> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/macro-snapshot`);
  return parseJson(response);
}

export async function putMacroPlan(storyId: string, body: MacroPlanPutBody): Promise<MacroSnapshotResponse> {
  const response = await fetch(`${API_BASE}/stories/${encodeURIComponent(storyId)}/macro-plan`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(response);
}

const MACRO_POLL_MS = 800;
const MACRO_TIMEOUT_MS = 30 * 60 * 1000;

/** POST returns 202; polls macro-snapshot until terminal status, then returns compile-shaped data. */
export async function macroCompile(storyId: string): Promise<MacroCompileData> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/macro-compile`, {
    method: "POST",
  });
  const ack = await parseJson<{ accepted: boolean; story_id: string }>(response);
  if (!ack.accepted) {
    throw new Error("Macro compile was not accepted");
  }
  const deadline = Date.now() + MACRO_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const snap = await fetchMacroSnapshot(storyId);
    const st = snap.macro_compile_status ?? "IDLE";
    if (st === "SUCCEEDED") {
      return {
        story_id: snap.story_id,
        bible: snap.bible,
        macro_author_notes: snap.macro_author_notes,
        cast_seed: snap.cast_seed,
        volumes: snap.volumes,
        anchors: snap.anchors,
        cast: snap.cast,
        protagonist_character_id: snap.protagonist_character_id,
      };
    }
    if (st === "FAILED") {
      throw new Error(snap.macro_compile_error?.trim() || "Macro compile failed");
    }
    await new Promise((r) => setTimeout(r, MACRO_POLL_MS));
  }
  throw new Error("Macro compile timed out waiting for completion");
}

export async function runChapter(
  storyId: string,
  chapterId: number,
  options?: {
    chapterOutline?: string;
    chapterHardRules?: string;
    authorChapterPlan?: string;
    aiFreedomLevel?: AiFreedomLevel;
    extractionSurfaceHints?: Array<{ node_id: string; surface_forms: string[] }>;
    waiveMandatoryNodeIds?: string[];
  },
): Promise<WorkflowPayload> {
  const chapterOutline = (options?.chapterOutline ?? options?.authorChapterPlan ?? "").trim();
  const chapterHardRules = (options?.chapterHardRules ?? "").trim();
  const aiFreedomLevel = options?.aiFreedomLevel ?? "balanced";
  const extraction_surface_hints = options?.extractionSurfaceHints ?? [];
  const waive_mandatory_node_ids = options?.waiveMandatoryNodeIds ?? [];
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      // Backward-compatible: server still accepts author_chapter_plan.
      author_chapter_plan: chapterOutline,
      // New dual-track inputs.
      chapter_outline: chapterOutline,
      chapter_hard_rules: chapterHardRules,
      ai_freedom_level: aiFreedomLevel,
      extraction_surface_hints,
      waive_mandatory_node_ids,
    }),
  });
  return parseJson(response);
}

export async function fetchWorkflow(runId: string): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}`);
  return parseJson(response);
}

export async function sendHitlDecision(runId: string, optionId: string): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ option_id: optionId }),
  });
  return parseJson(response);
}

export async function sendOutlineEdit(
  runId: string,
  payload: { ground_truth_events: Array<Record<string, unknown>>; narrative_script?: string; reason?: string },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/outline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendStateInjection(
  runId: string,
  payload: {
    mutations: Array<Record<string, unknown>>;
    chapter_hard_rules?: string;
    resume_from?: string;
    reason?: string;
    this_chapter_pacing_limit?: string;
    future_anchor_title?: string;
    future_anchor_description?: string;
    chapters_to_delay?: number | null;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/state-injection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendDraftEdit(
  runId: string,
  payload: {
    chapter_content: string;
    best_draft_content?: string;
    resume_from?: string;
    reason?: string;
    merge_extraction_hints?: boolean;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/draft-edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendDirectorPatch(
  runId: string,
  payload: {
    chapter_type?: string;
    b_story_directive?: string | null;
    b_story_type?: string | null;
    new_elements_to_introduce?: string[];
    narrative_directive?: string;
    reason?: string;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/director-patch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

/** Surface hints must be passed to {@link runChapter} before the workflow starts. */
export async function sendExtractionHints(
  _runId: string,
  _payload: {
    entries: Array<{ node_id: string; surface_forms: string[] }>;
    resume_from?: string;
    waive_mandatory_node_ids?: string[];
    reason?: string;
  },
): Promise<WorkflowPayload> {
  throw new Error(
    "專名線索請在「開始撰寫本章」時一併送出（runChapter 的 extractionSurfaceHints / waiveMandatoryNodeIds）；HITL 端點已停用。",
  );
}

export async function sendExtractionRemap(
  runId: string,
  payload: {
    entity_remaps: Array<{ from_node_id: string; to_node_id: string }>;
    waive_mandatory_node_ids?: string[];
    reason?: string;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/extraction-remap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendBStoryJudgement(
  runId: string,
  payload: {
    action: "force_resolve" | "reject";
    resolved_b_stories?: string[];
    resolution_evidence_event_ids?: string[];
    resolution_analysis?: string;
    reject_resume_from?: string;
    reason?: string;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/b-story-judgement`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendAnchorDelay(
  runId: string,
  payload: { anchor_id: string; new_chapter_target: number; reason?: string },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/anchor-delay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

export async function sendContextPrune(
  runId: string,
  payload: {
    graph_rag_context_tier: number;
    reason?: string;
  },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/context-prune`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(response);
}

/** Full story graph (no POV/epoch filter); same shape as filtered snapshot. */
export async function fetchGraph(storyId: string): Promise<GraphSnapshot> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/graph/full`);
  return parseJson(response);
}

/**
 * Subscribe to per-step workflow logs while a run executes in the background.
 * Each SSE message triggers onProgress (caller should fetchWorkflow).
 * Terminal: event "end" with payload { status }.
 */
export function subscribeWorkflowEvents(
  runId: string,
  handlers: {
    onProgress: () => void | Promise<void>;
    onEnd: (status: string) => void | Promise<void>;
    onError?: (err: Error) => void;
  },
): () => void {
  const url = `${API_BASE}/workflows/${runId}/events`;
  const es = new EventSource(url);
  let finished = false;

  const finish = () => {
    if (!finished) {
      finished = true;
      es.close();
    }
  };

  es.onmessage = () => {
    if (finished) return;
    void Promise.resolve(handlers.onProgress()).catch((e) =>
      handlers.onError?.(e instanceof Error ? e : new Error(String(e))),
    );
  };

  es.addEventListener("end", (ev) => {
    if (finished) return;
    let status = "UNKNOWN";
    try {
      const p = JSON.parse((ev as MessageEvent).data) as { status?: string };
      if (typeof p.status === "string") status = p.status;
    } catch {
      /* ignore */
    }
    void Promise.resolve(handlers.onEnd(status)).finally(finish);
  });

  es.onerror = () => {
    if (finished || es.readyState === EventSource.CLOSED) return;
    handlers.onError?.(new Error("與伺服器的即時連線中斷，請重新整理或再試一次"));
    finish();
  };

  return finish;
}

export async function fetchChapters(storyId: string): Promise<ChapterSummary[]> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters`);
  return parseJson(response);
}

export async function fetchChapter(storyId: string, chapterId: number): Promise<ChapterContent> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}`);
  return parseJson(response);
}

export async function fetchWritingPreamble(storyId: string, chapterId: number): Promise<WritingPreambleResponse> {
  const response = await fetch(
    `${API_BASE}/stories/${encodeURIComponent(storyId)}/chapters/${chapterId}/writing-preamble`,
  );
  return parseJson(response);
}

/** Returns null if the chapter row does not exist; used to gate full workflow runs in the UI. */
export async function fetchChapterIfExists(storyId: string, chapterId: number): Promise<ChapterContent | null> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}`);
  if (response.status === 404) return null;
  return parseJson<ChapterContent>(response);
}

export async function downloadChapterTxt(storyId: string, chapterId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}/download.txt`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Download failed");
  }

  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const disposition = response.headers.get("Content-Disposition") || "";
  const filenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const filename = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `${storyId}-chapter-${chapterId}.txt`;
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(objectUrl);
}
