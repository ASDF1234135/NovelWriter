import type { ChapterContent, ChapterSummary, GraphSnapshot, MacroCompileData, StoryInput, WorkflowPayload } from "./types";

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

export async function macroCompile(storyId: string): Promise<MacroCompileData> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/macro-compile`, {
    method: "POST",
  });
  return parseJson(response);
}

export async function runChapter(storyId: string, chapterId: number): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}/run`, {
    method: "POST",
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
  payload: { mutations: Array<Record<string, unknown>>; reason?: string },
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
  payload: { chapter_content: string; best_draft_content?: string; resume_from?: string; reason?: string },
): Promise<WorkflowPayload> {
  const response = await fetch(`${API_BASE}/workflows/${runId}/hitl/draft-edit`, {
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
    handlers.onError?.(new Error("Workflow 事件流中斷"));
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
