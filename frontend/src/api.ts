import type { ChapterContent, ChapterSummary, GraphSnapshot, MacroCompileData, StoryInput, WorkflowPayload } from "./types";

const API_BASE = "http://localhost:8000/api";

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Request failed");
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

export async function fetchGraph(storyId: string): Promise<GraphSnapshot> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/graph`);
  return parseJson(response);
}

export async function fetchChapters(storyId: string): Promise<ChapterSummary[]> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters`);
  return parseJson(response);
}

export async function fetchChapter(storyId: string, chapterId: number): Promise<ChapterContent> {
  const response = await fetch(`${API_BASE}/stories/${storyId}/chapters/${chapterId}`);
  return parseJson(response);
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
