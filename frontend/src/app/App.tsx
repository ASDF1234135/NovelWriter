import { useEffect, useMemo, useRef, useState } from "react";
import {
  createStory,
  downloadChapterTxt,
  fetchChapter,
  fetchChapterIfExists,
  fetchChapters,
  fetchGraph,
  fetchMacroSnapshot,
  fetchStoryDetail,
  fetchWorkflow,
  macroCompile,
  putMacroPlan,
  patchStory,
  runChapter,
  subscribeWorkflowEvents,
  sendAnchorDelay,
  sendBStoryJudgement,
  sendContextPrune,
  sendDirectorPatch,
  sendDraftEdit,
  sendExtractionHints,
  sendExtractionRemap,
  sendHitlDecision,
  sendOutlineEdit,
  sendStateInjection,
} from "../api";
import { AgentOutputView } from "../features/agent-output/AgentOutputView";
import { ChapterReader } from "../features/chapter-reader/ChapterReader";
import { GraphView } from "../features/graph-view/GraphView";
import { HitlPanel } from "../features/hitl-panel/HitlPanel";
import { MacroPlanPanel } from "../features/macro-plan/MacroPlanPanel";
import { StoryLibrary } from "../features/story-library/StoryLibrary";
import { StorySetupForm } from "../features/story-setup/StorySetupForm";
import { WorkflowMonitor } from "../features/workflow-monitor/WorkflowMonitor";
import type {
  ChapterContent,
  ChapterSummary,
  GraphSnapshot,
  ImportMergeMode,
  MacroCompileData,
  MacroPlanPutBody,
  StoryCastSeedEntry,
  StoryDetailResponse,
  StoryInput,
  StoryProjectBundlePayload,
  WorkflowPayload,
} from "../types";
import { AppShell, type AppView } from "./AppShell";

function storyDetailToInput(d: StoryDetailResponse): StoryInput {
  const bible = d.bible;
  return {
    title: d.title,
    premise: d.premise,
    bible: bible && typeof bible === "object" && !Array.isArray(bible) ? (bible as Record<string, unknown>) : {},
    macro_author_notes: d.macro_author_notes ?? "",
    cast_seed: Array.isArray(d.cast_seed) ? d.cast_seed : [],
    target_total_words: d.target_total_words,
    plan_retry_limit: d.plan_retry_limit,
    draft_loop_retry_limit: d.draft_loop_retry_limit,
  };
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function buildMacroPutBody(data: MacroCompileData): MacroPlanPutBody {
  return {
    bible: isObjectRecord(data.bible) ? { ...data.bible } : {},
    volumes: [...(data.volumes ?? [])],
    anchors: (data.anchors ?? []).map((a) => ({
      anchor_id: a.anchor_id,
      volume_id: a.volume_id ?? "",
      title: a.title ?? "",
      description: a.description ?? "",
      target_state: isObjectRecord(a.target_state) ? { ...a.target_state } : {},
      chapter_target: a.chapter_target,
      priority: a.priority ?? 1,
    })),
    cast: [...(data.cast ?? [])],
    protagonist_character_id: data.protagonist_character_id?.trim() || null,
  };
}

function parseStorySettingsImportJson(raw: string): StoryInput {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("故事設定 JSON 格式不正確");
  }
  const candidate = isObjectRecord(parsed) && parsed.kind === "story_settings" ? parsed.story : parsed;
  if (!isObjectRecord(candidate)) throw new Error("故事設定 JSON 結構錯誤");
  const title = String(candidate.title ?? "").trim();
  const premise = String(candidate.premise ?? "").trim();
  if (!title || !premise) throw new Error("故事設定需包含 title 與 premise");
  const target_total_words = Number(candidate.target_total_words ?? 0);
  const plan_retry_limit = Number(candidate.plan_retry_limit ?? 0);
  const draft_loop_retry_limit = Number(candidate.draft_loop_retry_limit ?? 0);
  if (!Number.isFinite(target_total_words) || target_total_words < 1) throw new Error("target_total_words 必須大於 0");
  if (!Number.isFinite(plan_retry_limit) || plan_retry_limit < 0 || plan_retry_limit > 20) throw new Error("plan_retry_limit 必須介於 0 到 20");
  if (!Number.isFinite(draft_loop_retry_limit) || draft_loop_retry_limit < 0 || draft_loop_retry_limit > 20) {
    throw new Error("draft_loop_retry_limit 必須介於 0 到 20");
  }
  const castSeedRaw = Array.isArray(candidate.cast_seed) ? candidate.cast_seed : [];
  const cast_seed: StoryCastSeedEntry[] = [];
  for (const item of castSeedRaw) {
    if (!isObjectRecord(item)) continue;
    const canonical_name = String(item.canonical_name ?? "").trim();
    if (!canonical_name) continue;
    const roleRaw = item.role;
    const role =
      roleRaw === "protagonist" || roleRaw === "supporting" || roleRaw === "antagonist" ? roleRaw : undefined;
    const short_hint = String(item.short_hint ?? "").trim();
    cast_seed.push({
      canonical_name,
      ...(role ? { role } : {}),
      ...(short_hint ? { short_hint } : {}),
    });
  }

  return {
    title,
    premise,
    bible: isObjectRecord(candidate.bible) ? candidate.bible : {},
    macro_author_notes: String(candidate.macro_author_notes ?? ""),
    cast_seed,
    target_total_words,
    plan_retry_limit,
    draft_loop_retry_limit,
  };
}

function parseMacroImportJson(raw: string): MacroPlanPutBody {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("compile JSON 格式不正確");
  }
  const candidate = isObjectRecord(parsed) && parsed.kind === "macro_compile" ? parsed.macro_plan : parsed;
  if (!isObjectRecord(candidate)) throw new Error("compile JSON 結構錯誤");
  const volumes = Array.isArray(candidate.volumes) ? candidate.volumes : [];
  const anchors = Array.isArray(candidate.anchors) ? candidate.anchors : [];
  if (volumes.length === 0 || anchors.length === 0) throw new Error("volumes 與 anchors 不可為空");
  const volumeIds = new Set<string>();
  for (const row of volumes) {
    const item = row as { volume_id?: unknown };
    const volumeId = String(item.volume_id ?? "").trim();
    if (!volumeId) throw new Error("volumes 內含空白 volume_id");
    if (volumeIds.has(volumeId)) throw new Error(`volumes 出現重複 volume_id：${volumeId}`);
    volumeIds.add(volumeId);
  }
  const anchorIds = new Set<string>();
  for (const row of anchors) {
    const item = row as { anchor_id?: unknown; volume_id?: unknown };
    const anchorId = String(item.anchor_id ?? "").trim();
    if (!anchorId) throw new Error("anchors 內含空白 anchor_id");
    if (anchorIds.has(anchorId)) throw new Error(`anchors 出現重複 anchor_id：${anchorId}`);
    anchorIds.add(anchorId);
    const linkedVolumeId = String(item.volume_id ?? "").trim();
    if (!linkedVolumeId) throw new Error(`anchor ${anchorId} 缺少 volume_id`);
    if (!volumeIds.has(linkedVolumeId)) throw new Error(`anchor ${anchorId} 指向不存在的 volume_id：${linkedVolumeId}`);
  }
  return {
    bible: isObjectRecord(candidate.bible) ? candidate.bible : {},
    volumes: volumes as MacroPlanPutBody["volumes"],
    anchors: anchors as MacroPlanPutBody["anchors"],
    cast: Array.isArray(candidate.cast) ? (candidate.cast as MacroPlanPutBody["cast"]) : [],
    protagonist_character_id:
      typeof candidate.protagonist_character_id === "string" || candidate.protagonist_character_id === null
        ? candidate.protagonist_character_id
        : null,
  };
}

function parseProjectBundleJson(raw: string): { story?: StoryInput; macro_plan?: MacroPlanPutBody } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("專案 JSON 格式不正確");
  }
  if (!isObjectRecord(parsed)) throw new Error("專案 JSON 結構錯誤");
  const kind = parsed.kind;

  if (kind === "story_settings") {
    return { story: parseStorySettingsImportJson(raw) };
  }
  if (kind === "macro_compile") {
    return { macro_plan: parseMacroImportJson(raw) };
  }
  if (kind === "story_project_bundle") {
    const out: { story?: StoryInput; macro_plan?: MacroPlanPutBody } = {};
    if (parsed.story !== undefined && parsed.story !== null) {
      out.story = parseStorySettingsImportJson(JSON.stringify(parsed.story));
    }
    if (parsed.macro_plan !== undefined && parsed.macro_plan !== null) {
      out.macro_plan = parseMacroImportJson(
        JSON.stringify({ kind: "macro_compile", version: 1, macro_plan: parsed.macro_plan }),
      );
    }
    if (!out.story && !out.macro_plan) {
      throw new Error("專案 JSON 需至少包含 story 或 macro_plan");
    }
    return out;
  }
  throw new Error("不支援的專案 JSON kind");
}

function mergeStorySettings(current: StoryInput, incoming: StoryInput): StoryInput {
  const currentCast = current.cast_seed ?? [];
  const incomingCast = incoming.cast_seed ?? [];
  const seen = new Set(currentCast.map((x) => x.canonical_name.trim()));
  const mergedCast = [...currentCast];
  for (const entry of incomingCast) {
    const key = entry.canonical_name.trim();
    if (!key || seen.has(key)) continue;
    mergedCast.push(entry);
    seen.add(key);
  }
  return {
    title: current.title.trim() ? current.title : incoming.title,
    premise: current.premise.trim() ? current.premise : incoming.premise,
    bible: Object.keys(current.bible ?? {}).length ? current.bible : incoming.bible,
    macro_author_notes: current.macro_author_notes?.trim() ? current.macro_author_notes : incoming.macro_author_notes,
    cast_seed: mergedCast,
    target_total_words: current.target_total_words > 0 ? current.target_total_words : incoming.target_total_words,
    plan_retry_limit: Number.isFinite(current.plan_retry_limit) ? current.plan_retry_limit : incoming.plan_retry_limit,
    draft_loop_retry_limit: Number.isFinite(current.draft_loop_retry_limit)
      ? current.draft_loop_retry_limit
      : incoming.draft_loop_retry_limit,
  };
}

function mergeMacroPlan(current: MacroPlanPutBody, incoming: MacroPlanPutBody): MacroPlanPutBody {
  const volumes = [...current.volumes];
  const volumeIds = new Set(current.volumes.map((v) => v.volume_id));
  for (const v of incoming.volumes) {
    if (!volumeIds.has(v.volume_id)) {
      volumes.push(v);
      volumeIds.add(v.volume_id);
    }
  }
  const anchors = [...current.anchors];
  const anchorIds = new Set(current.anchors.map((a) => a.anchor_id));
  for (const a of incoming.anchors) {
    if (!anchorIds.has(a.anchor_id)) {
      anchors.push(a);
      anchorIds.add(a.anchor_id);
    }
  }
  const cast = [...current.cast];
  const castIds = new Set(current.cast.map((c) => c.node_id));
  for (const c of incoming.cast) {
    if (!castIds.has(c.node_id)) {
      cast.push(c);
      castIds.add(c.node_id);
    }
  }
  return {
    bible: Object.keys(current.bible ?? {}).length ? current.bible : incoming.bible,
    volumes,
    anchors,
    cast,
    protagonist_character_id: current.protagonist_character_id ?? incoming.protagonist_character_id ?? null,
  };
}

function namespaceMacroPlanIdsForStory(body: MacroPlanPutBody, storyId: string): MacroPlanPutBody {
  const mappedVolumes = body.volumes.map((v) => {
    const original = String(v.volume_id ?? "").trim();
    const volume_id = original.startsWith(`${storyId}_`) ? original : `${storyId}_${original}`;
    return { ...v, volume_id };
  });
  const volumeMap = new Map<string, string>();
  for (const v of mappedVolumes) {
    const original = String(v.volume_id ?? "").trim();
    if (original.startsWith(`${storyId}_`)) {
      const raw = original.slice(storyId.length + 1);
      volumeMap.set(raw, original);
      volumeMap.set(original, original);
    }
  }
  const mappedAnchors = body.anchors.map((a) => {
    const rawAnchorId = String(a.anchor_id ?? "").trim();
    const anchor_id = rawAnchorId.startsWith(`${storyId}_`) ? rawAnchorId : `${storyId}_${rawAnchorId}`;
    const rawVolumeId = String(a.volume_id ?? "").trim();
    const volume_id = volumeMap.get(rawVolumeId) ?? (rawVolumeId.startsWith(`${storyId}_`) ? rawVolumeId : `${storyId}_${rawVolumeId}`);
    return { ...a, anchor_id, volume_id };
  });
  return {
    ...body,
    volumes: mappedVolumes,
    anchors: mappedAnchors,
  };
}

function downloadJsonFile(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(objectUrl);
}

export default function App() {
  const [view, setView] = useState<AppView>("library");
  const [storyId, setStoryId] = useState<string>("");
  const [storyTitle, setStoryTitle] = useState<string>("");
  const [chapterId, setChapterId] = useState<number>(1);
  const [macroData, setMacroData] = useState<MacroCompileData | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowPayload | null>(null);
  const [graph, setGraph] = useState<GraphSnapshot | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<ChapterContent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");
  const [chapterAlreadyCompleted, setChapterAlreadyCompleted] = useState(false);
  const [storyConfigSnapshot, setStoryConfigSnapshot] = useState<StoryInput | null>(null);
  const [configurationLocked, setConfigurationLocked] = useState(false);
  const [chapterOutline, setChapterOutline] = useState("");
  const [chapterHardRules, setChapterHardRules] = useState("");
  const [configVersion, setConfigVersion] = useState(0);
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);
  const storyIdRef = useRef(storyId);
  const chapterIdRef = useRef(chapterId);
  const chapterHardRulesRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    storyIdRef.current = storyId;
  }, [storyId]);
  useEffect(() => {
    chapterIdRef.current = chapterId;
  }, [chapterId]);

  useEffect(() => {
    return () => {
      workflowEventsUnsubRef.current?.();
      workflowEventsUnsubRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!storyId && (view === "manuscript" || view === "graph" || view === "console")) {
      setView("library");
    }
  }, [storyId, view]);

  useEffect(() => {
    const reason = String(workflow?.state?.hitl_reason ?? workflow?.run?.hitl_reason ?? "");
    const waiting =
      workflow?.run?.requires_hitl === true || String(workflow?.state?.workflow_status ?? "") === "WAITING_HITL";
    if (!waiting || reason !== "Alignment_Rules_Required") return;
    // Non-intrusive: do not force jump to library/setup from manuscript/console/graph.
    if (view !== "setup" && view !== "library") return;
    requestAnimationFrame(() => {
      chapterHardRulesRef.current?.focus();
      chapterHardRulesRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, [workflow?.run?.hitl_reason, workflow?.state?.hitl_reason, workflow?.state?.workflow_status, workflow?.run?.requires_hitl, view]);

  const alignmentRulesPromptActive = useMemo(() => {
    const reason = String(workflow?.state?.hitl_reason ?? workflow?.run?.hitl_reason ?? "");
    const waiting =
      workflow?.run?.requires_hitl === true || String(workflow?.state?.workflow_status ?? "") === "WAITING_HITL";
    return waiting && reason === "Alignment_Rules_Required";
  }, [workflow]);

  useEffect(() => {
    if (!storyId || chapterId < 1) {
      setChapterAlreadyCompleted(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const row = await fetchChapterIfExists(storyId, chapterId);
        if (!cancelled) {
          setChapterAlreadyCompleted(row?.status === "completed");
        }
      } catch {
        if (!cancelled) setChapterAlreadyCompleted(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [storyId, chapterId]);

  const latestChapterId = useMemo(() => {
    if (!chapters.length) return 1;
    return Math.max(...chapters.map((c) => c.chapter_id));
  }, [chapters]);

  /** Auto agent pipeline running for current workflow (not terminal, not HITL pause). */
  const workflowConflictLocked = useMemo(() => {
    if (!workflow) return false;
    const st = String(workflow.state.workflow_status ?? "");
    if (st === "COMPLETED" || st === "FAILED") return false;
    if (workflow.run.requires_hitl === true || st === "WAITING_HITL") return false;
    return true;
  }, [workflow]);

  const storySummary = useMemo(() => {
    if (!macroData) {
      return "尚未完成世界觀編譯。";
    }
    const volumes = macroData.volumes ?? [];
    const anchors = macroData.anchors ?? [];
    const cast = macroData.cast ?? [];
    const castPart = cast.length > 0 ? ` · 人物 ${cast.length} 位` : "";
    return `分卷 ${volumes.length} · 里程碑 ${anchors.length}${castPart}`;
  }, [macroData]);

  async function handleCreateStory(payload: StoryInput) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const story = await createStory(payload);
      setStoryId(String(story.story_id));
      setStoryTitle(payload.title);
      setStoryConfigSnapshot(payload);
      setConfigurationLocked(false);
      setConfigVersion((v) => v + 1);
      setWorkflow(null);
      setMacroData(null);
      setGraph(null);
      setChapters([]);
      setSelectedChapter(null);
      setView("setup");
    } catch (err) {
      setError(err instanceof Error ? err.message : "無法建立故事");
    } finally {
      setBusy(false);
    }
  }

  function handleNewStoryFromLibrary() {
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    setStoryId("");
    setStoryTitle("");
    setWorkflow(null);
    setMacroData(null);
    setGraph(null);
    setChapters([]);
    setSelectedChapter(null);
    setChapterId(1);
    setChapterAlreadyCompleted(false);
    setStoryConfigSnapshot(null);
    setConfigurationLocked(false);
    setConfigVersion((v) => v + 1);
    setError("");
    setView("setup");
  }

  function handleStoryDeleted(deletedId: string) {
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    if (deletedId !== storyId) return;
    setStoryId("");
    setStoryTitle("");
    setWorkflow(null);
    setMacroData(null);
    setGraph(null);
    setChapters([]);
    setSelectedChapter(null);
    setChapterId(1);
    setChapterAlreadyCompleted(false);
    setStoryConfigSnapshot(null);
    setConfigurationLocked(false);
    setConfigVersion((v) => v + 1);
    setError("");
    setView("library");
  }

  async function handleSelectStoryFromLibrary(selectedId: string, title?: string) {
    setBusy(true);
    setError("");
    setNotice("");
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    try {
      const detail = await fetchStoryDetail(selectedId);
      setStoryConfigSnapshot(storyDetailToInput(detail));
      setConfigurationLocked(detail.configuration_locked);
      setConfigVersion((v) => v + 1);
      const snap = await fetchMacroSnapshot(selectedId);
      setStoryId(selectedId);
      setStoryTitle(title?.trim() || detail.title || "");
      setWorkflow(null);
      setMacroData({
        story_id: snap.story_id,
        bible: snap.bible ?? {},
        macro_author_notes: snap.macro_author_notes,
        cast_seed: snap.cast_seed,
        volumes: snap.volumes,
        anchors: snap.anchors,
        cast: snap.cast,
        protagonist_character_id: snap.protagonist_character_id,
      });
      try {
        setGraph(await fetchGraph(selectedId));
      } catch {
        setGraph(null);
      }
      try {
        setChapters(await fetchChapters(selectedId));
      } catch {
        setChapters([]);
      }
      setSelectedChapter(null);
      setChapterId(1);
      setChapterAlreadyCompleted(false);
      setView("setup");
    } catch (err) {
      setError(err instanceof Error ? err.message : "無法載入故事");
    } finally {
      setBusy(false);
    }
  }

  async function handleMacroCompile() {
    if (!storyId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await macroCompile(storyId);
      setMacroData(result);
      setGraph(await fetchGraph(storyId));
      try {
        const detail = await fetchStoryDetail(storyId);
        setStoryConfigSnapshot(storyDetailToInput(detail));
      } catch {
        /* optional refresh */
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "世界觀編譯失敗");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveStorySettings(payload: StoryInput) {
    if (!storyId || configurationLocked) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await patchStory(storyId, {
        title: payload.title,
        premise: payload.premise,
        target_total_words: payload.target_total_words,
        plan_retry_limit: payload.plan_retry_limit,
        draft_loop_retry_limit: payload.draft_loop_retry_limit,
        macro_author_notes: payload.macro_author_notes ?? "",
        cast_seed: payload.cast_seed ?? [],
      });
      setStoryConfigSnapshot(payload);
      setStoryTitle(payload.title);
    } catch (err) {
      setError(err instanceof Error ? err.message : "儲存設定失敗");
    } finally {
      setBusy(false);
    }
  }

  async function finalizeWorkflowRunUi(runId: string) {
    try {
      const wf = await fetchWorkflow(runId);
      setWorkflow(wf);
      if (String(wf.state.workflow_status ?? "") === "COMPLETED") {
        setView("manuscript");
      }
      const sid = storyIdRef.current;
      if (sid) {
        setGraph(await fetchGraph(sid));
        setChapters(await fetchChapters(sid));
        try {
          setMacroData(await fetchMacroSnapshot(sid));
        } catch {
          /* optional */
        }
        try {
          setSelectedChapter(await fetchChapter(sid, chapterIdRef.current));
        } catch {
          /* missing */
        }
        const probe = await fetchChapterIfExists(sid, chapterIdRef.current);
        setChapterAlreadyCompleted(probe?.status === "completed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "流程結束後更新畫面失敗");
    } finally {
      setBusy(false);
    }
  }

  function attachWorkflowEventStream(runId: string) {
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = subscribeWorkflowEvents(runId, {
      onProgress: async () => {
        try {
          setWorkflow(await fetchWorkflow(runId));
          const sid = storyIdRef.current;
          if (sid) {
            try {
              setGraph(await fetchGraph(sid));
            } catch {
              /* optional */
            }
          }
        } catch {
          /* ignore */
        }
      },
      onEnd: async () => {
        workflowEventsUnsubRef.current = null;
        await finalizeWorkflowRunUi(runId);
      },
      onError: (err) => {
        workflowEventsUnsubRef.current = null;
        void (async () => {
          try {
            const wf = await fetchWorkflow(runId);
            const status = String(wf.state.workflow_status ?? "");
            const terminal = status === "COMPLETED" || status === "FAILED";
            const waitingHitl = wf.run.requires_hitl === true || status === "WAITING_HITL";
            setWorkflow(wf);
            if (terminal) {
              await finalizeWorkflowRunUi(runId);
              return;
            }
            if (waitingHitl) {
              setBusy(false);
              return;
            }
          } catch {
            /* fall through and show SSE error */
          }
          setError(err.message);
          setBusy(false);
        })();
      },
    });
  }

  /** After HITL apply returns: resume SSE if run is in progress, else finalize or stay idle at next HITL. */
  function applyHitlWorkflowResponse(wf: WorkflowPayload) {
    const st = String(wf.state.workflow_status ?? "");
    const terminal = st === "COMPLETED" || st === "FAILED";
    const waiting = wf.run.requires_hitl === true || st === "WAITING_HITL";
    setWorkflow(wf);
    if (terminal) {
      workflowEventsUnsubRef.current?.();
      workflowEventsUnsubRef.current = null;
      void finalizeWorkflowRunUi(wf.run.run_id);
    } else if (waiting) {
      workflowEventsUnsubRef.current?.();
      workflowEventsUnsubRef.current = null;
      setBusy(false);
    } else {
      attachWorkflowEventStream(wf.run.run_id);
    }
  }

  async function handleRunChapter() {
    if (!storyId) return;
    setError("");
    setNotice("");
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    setBusy(true);
    try {
      const initial = await runChapter(storyId, chapterId, { chapterOutline, chapterHardRules });
      setWorkflow(initial);
      try {
        const detail = await fetchStoryDetail(storyId);
        setStoryConfigSnapshot(storyDetailToInput(detail));
        setConfigurationLocked(detail.configuration_locked);
      } catch {
        setConfigurationLocked(true);
      }
      setConfigVersion((v) => v + 1);
      const runId = initial.run.run_id;
      setView("console");
      attachWorkflowEventStream(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "無法開始撰寫本章");
    } finally {
      setBusy(false);
    }
  }

  async function refreshWorkflow() {
    if (!workflow?.run.run_id) return;
    setWorkflow(await fetchWorkflow(workflow.run.run_id));
    if (storyId) {
      setGraph(await fetchGraph(storyId));
      setChapters(await fetchChapters(storyId));
      if (selectedChapter) {
        try {
          setSelectedChapter(await fetchChapter(storyId, selectedChapter.chapter_id));
        } catch (err) {
          const msg = err instanceof Error ? err.message : "";
          if (msg.includes("Chapter not found")) {
            setSelectedChapter(null);
            setNotice("目標章節尚未落盤，請稍後再讀取。");
          } else {
            throw err;
          }
        }
      }
      try {
        const probe = await fetchChapterIfExists(storyId, chapterId);
        setChapterAlreadyCompleted(probe?.status === "completed");
      } catch {
        setChapterAlreadyCompleted(false);
      }
    }
  }

  function exportProjectBundle() {
    if (!storyId) return;
    const story = storyConfigSnapshot ??
      ({
        title: storyTitle || "",
        premise: "",
        bible: {},
        macro_author_notes: "",
        cast_seed: [],
        target_total_words: 100000,
        plan_retry_limit: 3,
        draft_loop_retry_limit: 3,
      } satisfies StoryInput);
    const payload: StoryProjectBundlePayload = {
      kind: "story_project_bundle",
      version: 1,
      story,
    };
    const vols = macroData?.volumes ?? [];
    const ancs = macroData?.anchors ?? [];
    if (vols.length > 0 && ancs.length > 0 && macroData) {
      payload.macro_plan = buildMacroPutBody(macroData);
    }
    downloadJsonFile(`${storyId}-project.json`, payload);
  }

  async function importProjectBundle(jsonText: string, mode: ImportMergeMode) {
    if (!storyId || configurationLocked) return;
    const { story: parsedStory, macro_plan: parsedMacroRaw } = parseProjectBundleJson(jsonText);
    const parsedMacro = parsedMacroRaw ? namespaceMacroPlanIdsForStory(parsedMacroRaw, storyId) : undefined;
    const modeLabel = mode === "replace" ? "覆蓋" : "合併";
    const storySummary = parsedStory
      ? `故事：${parsedStory.title} · 核心角色 ${parsedStory.cast_seed?.length ?? 0} 位`
      : "（無故事區塊）";
    const macroSummary = parsedMacro
      ? `宏觀：分卷 ${parsedMacro.volumes.length} · 里程碑 ${parsedMacro.anchors.length} · 人物 ${parsedMacro.cast.length}`
      : "（無宏觀區塊）";
    const proceed = window.confirm(`即將匯入專案 JSON（${modeLabel}）\n${storySummary}\n${macroSummary}\n\n確定要繼續嗎？`);
    if (!proceed) return;

    if (parsedStory) {
      const current =
        storyConfigSnapshot ??
        ({
          title: "",
          premise: "",
          bible: {},
          macro_author_notes: "",
          cast_seed: [],
          target_total_words: 100000,
          plan_retry_limit: 3,
          draft_loop_retry_limit: 3,
        } satisfies StoryInput);
      const merged = mode === "replace" ? parsedStory : mergeStorySettings(current, parsedStory);
      await patchStory(storyId, {
        title: merged.title,
        premise: merged.premise,
        target_total_words: merged.target_total_words,
        plan_retry_limit: merged.plan_retry_limit,
        draft_loop_retry_limit: merged.draft_loop_retry_limit,
        macro_author_notes: merged.macro_author_notes ?? "",
        cast_seed: merged.cast_seed ?? [],
      });
      setStoryConfigSnapshot(merged);
      setStoryTitle(merged.title);
    }

    if (parsedMacro) {
      const current = macroData ? buildMacroPutBody(macroData) : null;
      const body = mode === "replace" || !current ? parsedMacro : mergeMacroPlan(current, parsedMacro);
      const putResult = await putMacroPlan(storyId, body);
      setMacroData({
        story_id: putResult.story_id,
        bible: putResult.bible ?? {},
        macro_author_notes: putResult.macro_author_notes,
        cast_seed: putResult.cast_seed,
        volumes: putResult.volumes,
        anchors: putResult.anchors,
        cast: putResult.cast,
        protagonist_character_id: putResult.protagonist_character_id,
      });
      try {
        setMacroData(await fetchMacroSnapshot(storyId));
      } catch {
        /* fallback to put result above */
      }
    }

    if (parsedStory || parsedMacro) {
      setConfigVersion((v) => v + 1);
      setNotice(`專案 JSON 已匯入（${modeLabel}）`);
    }
  }

  const hitlHandlers = {
    onDecision: async (optionId: string) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendHitlDecision(workflow.run.run_id, optionId));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法送出您的選擇");
        setBusy(false);
      }
    },
    onOutlineEdit: async (payload: Parameters<typeof sendOutlineEdit>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendOutlineEdit(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用大綱變更");
        setBusy(false);
      }
    },
    onDraftEdit: async (payload: Parameters<typeof sendDraftEdit>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendDraftEdit(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用內文變更");
        setBusy(false);
      }
    },
    onStateInjection: async (payload: Parameters<typeof sendStateInjection>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendStateInjection(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法寫入資料");
        setBusy(false);
      }
    },
    onDirectorPatch: async (payload: Parameters<typeof sendDirectorPatch>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendDirectorPatch(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用章節方向調整");
        setBusy(false);
      }
    },
    onExtractionHints: async (payload: Parameters<typeof sendExtractionHints>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendExtractionHints(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用專名線索");
        setBusy(false);
      }
    },
    onExtractionRemap: async (payload: Parameters<typeof sendExtractionRemap>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendExtractionRemap(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用名稱對照");
        setBusy(false);
      }
    },
    onBStoryJudgement: async (payload: Parameters<typeof sendBStoryJudgement>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendBStoryJudgement(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法送出副線判定");
        setBusy(false);
      }
    },
    onAnchorDelay: async (payload: Parameters<typeof sendAnchorDelay>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendAnchorDelay(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法延後里程碑");
        setBusy(false);
      }
    },
    onContextPrune: async (payload: Parameters<typeof sendContextPrune>[1]) => {
      if (!workflow) return;
      setBusy(true);
      setError("");
      try {
        applyHitlWorkflowResponse(await sendContextPrune(workflow.run.run_id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : "無法套用背景精簡");
        setBusy(false);
      }
    },
  };

  const showStorySection = Boolean(storyId) || view === "setup";
  const storySectionLabel =
    storyTitle.trim() || (storyId ? `${storyId.slice(0, 10)}…` : "");

  return (
    <AppShell
      activeView={view}
      onViewChange={setView}
      hasSelectedStory={Boolean(storyId)}
      showStorySection={showStorySection}
      storySectionLabel={storySectionLabel}
    >
      {error ? (
        <div className="mx-4 mt-4 rounded-xl border border-error/40 bg-error/10 px-4 py-3 font-label text-sm text-error">
          {error}
        </div>
      ) : null}
      {!error && notice ? (
        <div className="mx-4 mt-4 rounded-xl border border-secondary/35 bg-secondary/10 px-4 py-3 font-label text-sm text-secondary">
          {notice}
        </div>
      ) : null}
      {!error && alignmentRulesPromptActive && view !== "setup" && view !== "library" ? (
        <div className="mx-4 mt-4 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 font-label text-sm text-on-surface">
          偵測到複雜智鬥，需補充硬性規則。你可以先留在此頁查看流程，或前往「故事設定」填寫 `chapter_hard_rules`。
          <button type="button" className="btn-secondary ml-3" onClick={() => setView("setup")}>
            前往故事設定
          </button>
        </div>
      ) : null}

      {view === "library" ? (
        <StoryLibrary
          onSelectStory={handleSelectStoryFromLibrary}
          onNewStory={handleNewStoryFromLibrary}
          onStoryDeleted={handleStoryDeleted}
          busy={busy}
          blockSelectingStories={workflowConflictLocked}
        />
      ) : null}

      {view === "setup" ? (
        <div className="px-4 pb-12 pt-8 md:px-10 lg:px-12">
          <div className="mb-10 max-w-7xl">
            <span className="mb-2 block font-label text-xs font-semibold uppercase tracking-[0.3em] text-secondary">
              專案設定
            </span>
            <h1 className="mb-3 font-headline text-4xl font-black tracking-tighter text-on-surface">故事設定</h1>
            <p className="max-w-2xl font-body text-lg italic text-on-surface-variant">
              在此整理故事梗概與參數，並執行世界觀編譯以生成分卷、人物與里程碑。
            </p>
          </div>

          {storyId && !configurationLocked ? (
            <div className="mb-4 max-w-7xl rounded-xl border border-tertiary/25 bg-tertiary/5 px-4 py-3 font-body text-sm leading-relaxed text-on-surface">
              <span className="font-headline font-bold text-tertiary">重新執行世界觀編譯</span>
              會覆寫自動產生的角色節點，以及目前儲存的世界觀總表、分卷與里程碑；若你曾在圖譜上手動改過這些自動產生的角色，那些修改會消失。
            </div>
          ) : null}

          <div className="mb-8 max-w-7xl rounded-xl border border-outline-variant/10 bg-surface-container-low/80 p-4 font-label shadow-glow">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-primary-gradient flex items-center gap-2 text-sm"
                onClick={handleMacroCompile}
                disabled={!storyId || busy || workflowConflictLocked || configurationLocked}
              >
                <span className="material-symbols-outlined text-lg">auto_awesome</span>
                產生世界觀與結構
              </button>
              <label className="flex items-center gap-2 text-xs uppercase tracking-wider text-on-surface-variant">
                章節
                <input
                  type="number"
                  min={1}
                  value={chapterId}
                  onChange={(e) => setChapterId(Number(e.target.value))}
                  className="w-20 rounded-lg border border-outline-variant/20 bg-surface-container-highest px-2 py-2 text-on-surface"
                />
              </label>
              <button
                type="button"
                className="btn-secondary"
                title="將章節選擇設為目前已有的最大章節"
                disabled={!storyId || busy || chapters.length === 0}
                onClick={() => setChapterId(latestChapterId)}
              >
                <span className="material-symbols-outlined align-middle text-base">skip_next</span>
                最新章
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={handleRunChapter}
                disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
              >
                撰寫本章
              </button>
              <button type="button" className="btn-secondary" onClick={refreshWorkflow} disabled={!workflow || busy}>
                重新整理狀態
              </button>
            </div>
            <div className="rounded-xl border border-outline-variant/15 bg-surface-container px-4 py-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">Chapter Direction</p>
                  <p className="font-body text-sm text-on-surface">本章寫作大綱（可偏差）</p>
                </div>
                {chapterAlreadyCompleted ? (
                  <span className="rounded-full border border-tertiary/30 bg-tertiary/10 px-2 py-1 text-xs text-tertiary">
                    第 {chapterId} 章已完成（無法重跑）
                  </span>
                ) : null}
              </div>
              <textarea
                value={chapterOutline}
                onChange={(e) => setChapterOutline(e.target.value)}
                maxLength={2000}
                rows={3}
                placeholder="例如：本章以對話推進謎底、避免打鬥場面…"
                disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                className="mb-3 w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
              />
              <div className="mb-2">
                <p className="font-body text-sm text-on-surface">本章硬性規則（需保真、嚴格遵守）</p>
              </div>
              <textarea
                value={chapterHardRules}
                onChange={(e) => setChapterHardRules(e.target.value)}
                ref={chapterHardRulesRef}
                maxLength={8000}
                rows={4}
                placeholder="例如：遊戲規則、勝負條件、不可違背的系統法則（POV 不可知的底牌請標示清楚）"
                disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
              />
            </div>
          </div>

          <div className="mb-6 max-w-7xl rounded-xl border border-outline-variant/10 bg-surface-container-low px-6 py-4 font-label text-sm text-on-surface-variant">
            <span className="text-secondary">故事編號</span> {storyId || "未建立"} · {storySummary}
          </div>

          <div className="grid max-w-7xl grid-cols-1 items-start gap-8 lg:grid-cols-12">
            <div className="lg:col-span-5">
              <StorySetupForm
                resetKey={`${storyId || "new"}-${configVersion}`}
                initialValues={storyId ? storyConfigSnapshot : null}
                locked={Boolean(storyId && configurationLocked)}
                onValuesChange={storyId && !configurationLocked ? setStoryConfigSnapshot : undefined}
                onSubmit={handleCreateStory}
                onSaveSettings={storyId && !configurationLocked ? handleSaveStorySettings : undefined}
                showCreateButton={!storyId}
                onExportProjectBundle={storyId ? exportProjectBundle : undefined}
                onImportProjectBundle={storyId && !configurationLocked ? importProjectBundle : undefined}
                onBusy={setBusy}
                onError={setError}
                disabled={busy}
              />
            </div>
            <div className="lg:col-span-7">
              <MacroPlanPanel
                macroData={macroData}
                storyId={storyId || null}
                configurationLocked={configurationLocked}
                onMacroDataUpdate={setMacroData}
                onBusy={setBusy}
                onError={setError}
              />
            </div>
          </div>
        </div>
      ) : null}

      {view === "manuscript" ? (
        <div className="flex h-[calc(100vh-4rem)] flex-col bg-surface-container-lowest lg:flex-row">
          <ChapterReader
            storyId={storyId}
            currentChapterId={selectedChapter?.chapter_id ?? chapterId}
            chapters={chapters}
            chapter={selectedChapter}
            busy={busy}
            onSelectChapter={async (nextChapterId) => {
              if (!storyId) return;
              setBusy(true);
              setError("");
              try {
                setChapterId(nextChapterId);
                setSelectedChapter(await fetchChapter(storyId, nextChapterId));
              } catch (err) {
                const msg = err instanceof Error ? err.message : "";
                if (msg.includes("Chapter not found")) {
                  setNotice("章節尚未落盤，請稍後再讀取。");
                  setSelectedChapter(null);
                } else {
                  setError(err instanceof Error ? err.message : "無法載入章節");
                }
              } finally {
                setBusy(false);
              }
            }}
            onDownloadChapter={async (nextChapterId) => {
              if (!storyId) return;
              setBusy(true);
              setError("");
              try {
                await downloadChapterTxt(storyId, nextChapterId);
              } catch (err) {
                setError(err instanceof Error ? err.message : "無法下載章節");
              } finally {
                setBusy(false);
              }
            }}
            rightRail={
              <div className="flex flex-col gap-4 p-4">
                <WorkflowMonitor workflow={workflow} variant="compact" />
                <HitlPanel workflow={workflow} variant="compact" {...hitlHandlers} />
                <AgentOutputView workflow={workflow} variant="compact" />
              </div>
            }
          />
        </div>
      ) : null}

      {view === "graph" ? (
        <div className="min-h-[calc(100vh-4rem)] bg-background p-4 md:p-8">
          <div className="mb-4 flex items-center justify-end gap-3">
            <span className="rounded-full border border-secondary/20 bg-secondary/10 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-secondary">
              僅供閱覽
            </span>
          </div>
          <GraphView graph={graph} protagonistCharacterId={macroData?.protagonist_character_id} />
        </div>
      ) : null}

      {view === "console" ? (
        <div className="space-y-6 px-4 py-8 md:px-10">
          <WorkflowMonitor workflow={workflow} />
          <HitlPanel workflow={workflow} {...hitlHandlers} />
          <AgentOutputView workflow={workflow} />
        </div>
      ) : null}
    </AppShell>
  );
}
