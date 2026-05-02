import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  createStory,
  downloadChapterTxt,
  fetchChapter,
  fetchChapterIfExists,
  fetchChapters,
  fetchGraph,
  fetchMacroSnapshot,
  fetchStoryDetail,
  fetchWritingPreamble,
  regenerateChapterSummary,
  fetchWorkflow,
  macroCompile,
  putMacroPlan,
  patchStory,
  runChapter,
  subscribeWorkflowEvents,
  sendAnchorDelay,
  sendAnchorResolution,
  sendContextPrune,
  sendDirectorPatch,
  sendDraftEdit,
  sendExtractionRemap,
  sendHitlDecision,
  sendOutlineEdit,
  sendStateInjection,
  type MacroCompileProgress,
} from "../api";
import { AgentOutputView } from "../features/agent-output/AgentOutputView";
import { ChapterReader } from "../features/chapter-reader/ChapterReader";
import { GraphView } from "../features/graph-view/GraphView";
import { HitlPanel } from "../features/hitl-panel/HitlPanel";
import { AnchorNodesGraphView } from "../features/macro-plan/AnchorNodesGraphView";
import { MacroPlanPanel } from "../features/macro-plan/MacroPlanPanel";
import { StoryLibrary } from "../features/story-library/StoryLibrary";
import { StorySetupForm } from "../features/story-setup/StorySetupForm";
import { WorkflowMonitor } from "../features/workflow-monitor/WorkflowMonitor";
import { WorkflowProgressTrack } from "../features/workflow-monitor/WorkflowProgressTrack";
import { ExportCenter } from "../features/export-center/ExportCenter";
import type {
  AiFreedomLevel,
  ChapterContent,
  ChapterSummary,
  GraphSnapshot,
  ImportMergeMode,
  MacroCompileData,
  MacroPlanPutBody,
  StoryCastSeedEntry,
  StoryDetailResponse,
  StoryInput,
  StoryOutputLanguage,
  StoryProjectBundlePayload,
  WorkflowPayload,
  WritingPreambleResponse,
} from "../types";
import { AppShell, type AppView, type TaskFlowStageId } from "./AppShell";
import { buildMacroPutBody, mergeMacroPlan, namespaceMacroPlanIdsForStory, parseMacroImportJson } from "./macroPlanBundle";
import { localizeUserFacingError } from "../i18n/userFacingError";
import { useI18n } from "../i18n/useI18n";

/** Same heuristic as backend OUTLINE_MIN_CHARS_FOR_FULL_BINDING — UX hint only. */
const OUTLINE_FULL_BINDING_MIN_CHARS = 100;

const CHAPTER_SUMMARIZER_LLM_SOURCE = "CHAPTER_SUMMARIZER_LLM";

const VIEW_PATH_MAP: Record<AppView, string> = {
  library: "/library",
  setup: "/setup",
  write: "/write",
  review: "/review",
  graph: "/graph",
  export: "/export",
};

function pathToView(pathname: string): AppView {
  const cleaned = pathname.replace(/\/+$/, "") || "/";
  switch (cleaned) {
    case "/":
    case "/library":
      return "library";
    case "/setup":
      return "setup";
    case "/write":
      return "write";
    case "/review":
      return "review";
    case "/graph":
      return "graph";
    case "/export":
      return "export";
    default:
      return "library";
  }
}

/** True when backend persisted a summary row whose text was not produced by the chapter_summarizer LLM path. */
function plotSummarySourceNeedsRegenerate(src: string | undefined): boolean {
  if (src === undefined || src === null || src === "") return false;
  return src !== CHAPTER_SUMMARIZER_LLM_SOURCE;
}

export function normalizeOutputLanguage(v: unknown): StoryOutputLanguage {
  if (v === "en" || v === "zh-Hant" || v === "zh-Hans") return v;
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "zh-cn" || s === "zh-sg" || s === "zh-hans") return "zh-Hans";
  if (s === "zh-tw" || s === "zh-hk" || s === "zh-mo" || s === "zh-hant") return "zh-Hant";
  if (s === "en-us" || s === "en-gb") return "en";
  return "zh-Hant";
}

export function storyDetailToInput(
  d: StoryDetailResponse,
  fallbackLanguage: StoryOutputLanguage = "zh-Hant",
): StoryInput {
  const bible = d.bible;
  const rawLanguage = (d as StoryDetailResponse & { output_language?: unknown }).output_language;
  return {
    title: d.title,
    premise: d.premise,
    bible: bible && typeof bible === "object" && !Array.isArray(bible) ? (bible as Record<string, unknown>) : {},
    macro_author_notes: d.macro_author_notes ?? "",
    cast_seed: Array.isArray(d.cast_seed) ? d.cast_seed : [],
    target_total_words: d.target_total_words,
    plan_retry_limit: d.plan_retry_limit,
    draft_loop_retry_limit: d.draft_loop_retry_limit,
    output_language:
      rawLanguage === undefined || rawLanguage === null || String(rawLanguage).trim() === ""
        ? fallbackLanguage
        : normalizeOutputLanguage(rawLanguage),
  };
}

function normalizeStoryInputForCompare(input: StoryInput): StoryInput {
  const castSeed = Array.isArray(input.cast_seed) ? [...input.cast_seed] : [];
  castSeed.sort((a, b) => String(a.canonical_name ?? "").localeCompare(String(b.canonical_name ?? "")));
  return {
    title: String(input.title ?? "").trim(),
    premise: String(input.premise ?? "").trim(),
    bible: input.bible && typeof input.bible === "object" && !Array.isArray(input.bible) ? input.bible : {},
    macro_author_notes: String(input.macro_author_notes ?? ""),
    cast_seed: castSeed,
    target_total_words: Number(input.target_total_words ?? 0),
    plan_retry_limit: Number(input.plan_retry_limit ?? 0),
    draft_loop_retry_limit: Number(input.draft_loop_retry_limit ?? 0),
    output_language: normalizeOutputLanguage(input.output_language),
  };
}

export function isStoryConfigDirty(current: StoryInput | null, persisted: StoryInput | null): boolean {
  if (!current || !persisted) return false;
  return JSON.stringify(normalizeStoryInputForCompare(current)) !== JSON.stringify(normalizeStoryInputForCompare(persisted));
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
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
    output_language: normalizeOutputLanguage(candidate.output_language),
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
    output_language: normalizeOutputLanguage(current.output_language ?? incoming.output_language),
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
  const { locale, t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const view = pathToView(location.pathname);
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
  function reportApiError(err: unknown, fallbackKey: string) {
    const raw = err instanceof Error ? err.message : "";
    setError(localizeUserFacingError(raw, t) || t(fallbackKey));
  }
  const [notice, setNotice] = useState<string>("");
  const [chapterAlreadyCompleted, setChapterAlreadyCompleted] = useState(false);
  const [storyConfigSnapshot, setStoryConfigSnapshot] = useState<StoryInput | null>(null);
  const [persistedStoryConfig, setPersistedStoryConfig] = useState<StoryInput | null>(null);
  const [configurationLocked, setConfigurationLocked] = useState(false);
  const [chapterOutline, setChapterOutline] = useState("");
  const [chapterHardRules, setChapterHardRules] = useState("");
  const [aiFreedomLevel, setAiFreedomLevel] = useState<AiFreedomLevel>("balanced");
  const [selectedAnchorIds, setSelectedAnchorIds] = useState<string[]>([]);
  const [manualAnchorSelectionOpen, setManualAnchorSelectionOpen] = useState(false);
  const [writingPreamble, setWritingPreamble] = useState<WritingPreambleResponse | null>(null);
  const [preamblePanelOpen, setPreamblePanelOpen] = useState(false);
  const [writePanelTab, setWritePanelTab] = useState<"progress" | "logs">("progress");
  const [compileInProgress, setCompileInProgress] = useState(false);
  const [compileProgress, setCompileProgress] = useState<MacroCompileProgress | null>(null);
  const [regenSummaryBusyChapter, setRegenSummaryBusyChapter] = useState<number | null>(null);
  const [configVersion, setConfigVersion] = useState(0);
  const [hasExportedChapter, setHasExportedChapter] = useState(false);
  const [hasExportedProject, setHasExportedProject] = useState(false);
  const [navCount, setNavCount] = useState(0);
  const [stageVisitCount, setStageVisitCount] = useState<Record<TaskFlowStageId, number>>({
    projectSetup: 0,
    planStructure: 0,
    writeChapter: 0,
    reviewFix: 0,
    export: 0,
  });
  const [setupSelectedAnchorNodeId, setSetupSelectedAnchorNodeId] = useState<string | null>(null);
  const [flowStartedAt, setFlowStartedAt] = useState<number | null>(null);
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);
  const storyIdRef = useRef(storyId);
  const chapterIdRef = useRef(chapterId);
  const chapterHardRulesRef = useRef<HTMLTextAreaElement | null>(null);
  const toolbarImportInputRef = useRef<HTMLInputElement | null>(null);

  function setView(nextView: AppView, replace = false) {
    const targetPath = VIEW_PATH_MAP[nextView];
    if (location.pathname !== targetPath) {
      navigate(targetPath, { replace });
    }
  }

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
    if (!storyId && (view === "write" || view === "review" || view === "graph" || view === "export")) {
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

  const workflowHitlActive = useMemo(() => {
    if (!workflow) return false;
    const st = String(workflow.state.workflow_status ?? "");
    return (
      workflow.run.requires_hitl === true ||
      workflow.run.status === "WAITING_HITL" ||
      st === "WAITING_HITL"
    );
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

  useEffect(() => {
    if (!storyId || chapterId < 1) {
      setWritingPreamble(null);
      return;
    }
    let cancelled = false;
    setWritingPreamble(null);
    void (async () => {
      try {
        const p = await fetchWritingPreamble(storyId, chapterId);
        if (!cancelled) setWritingPreamble(p);
      } catch {
        if (!cancelled) setWritingPreamble(null);
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

  const chapterAnchorCandidates = useMemo(() => {
    const nodes = macroData?.anchor_nodes ?? [];
    return nodes.filter((n) => n.status === "UNLOCKED");
  }, [macroData?.anchor_nodes]);
  const setupAnchorNodes = useMemo(() => macroData?.anchor_nodes ?? [], [macroData?.anchor_nodes]);
  const setupSelectedAnchorNode = useMemo(() => {
    if (!setupAnchorNodes.length) return null;
    if (setupSelectedAnchorNodeId) {
      return setupAnchorNodes.find((n) => String(n.id) === setupSelectedAnchorNodeId) ?? setupAnchorNodes[0];
    }
    return setupAnchorNodes[0];
  }, [setupAnchorNodes, setupSelectedAnchorNodeId]);
  const setupCanEditSelectedNode = useMemo(() => {
    if (!setupSelectedAnchorNode) return false;
    const isMainline = (setupSelectedAnchorNode.storyline_ids ?? []).some((sid) => String(sid).endsWith("_main"));
    const kind = String(setupSelectedAnchorNode.node_kind ?? "NORMAL").toUpperCase();
    const resolved = String(setupSelectedAnchorNode.status ?? "").toUpperCase() === "RESOLVED";
    return !isMainline && kind === "NORMAL" && !resolved;
  }, [setupSelectedAnchorNode]);

  useEffect(() => {
    const candidateIds = new Set(chapterAnchorCandidates.map((n) => n.id));
    setSelectedAnchorIds((prev) => prev.filter((id) => candidateIds.has(id)).slice(0, 2));
  }, [chapterAnchorCandidates]);
  const autoNextAnchorIds = useMemo(() => {
    const nodes = macroData?.anchor_nodes ?? [];
    if (!nodes.length || selectedAnchorIds.length === 0) return [];
    const selectedSet = new Set(selectedAnchorIds);
    const children: Array<{ id: string; chapter: number; order: number }> = [];
    nodes.forEach((node, order) => {
      const id = String(node.id);
      const deps = node.depends_on ?? [];
      const status = String(node.status ?? "").toUpperCase();
      if (selectedSet.has(id)) return;
      if (status === "RESOLVED") return;
      if (!deps.some((dep) => selectedSet.has(String(dep)))) return;
      children.push({ id, chapter: Number(node.estimated_chapter ?? Number.MAX_SAFE_INTEGER), order });
    });
    children.sort((a, b) => a.chapter - b.chapter || a.order - b.order || a.id.localeCompare(b.id));
    const picked = children.map((r) => r.id).slice(0, 2);
    if (picked.length >= 1) return picked;
    const fallback = nodes
      .filter((n) => String(n.status ?? "").toUpperCase() === "UNLOCKED" && !selectedSet.has(String(n.id)))
      .map((n) => String(n.id))
      .slice(0, 2);
    return fallback;
  }, [macroData?.anchor_nodes, selectedAnchorIds]);

  useEffect(() => {
    if (!setupAnchorNodes.length) {
      setSetupSelectedAnchorNodeId(null);
      return;
    }
    if (!setupSelectedAnchorNodeId || !setupAnchorNodes.some((n) => String(n.id) === setupSelectedAnchorNodeId)) {
      setSetupSelectedAnchorNodeId(String(setupAnchorNodes[0]?.id ?? ""));
    }
  }, [setupAnchorNodes, setupSelectedAnchorNodeId]);

  const storySummary = useMemo(() => {
    if (!macroData) {
      return locale === "en" ? "World compile not completed yet." : locale === "zh-Hans" ? "尚未完成世界观编译。" : "尚未完成世界觀編譯。";
    }
    const volumes = macroData.volumes ?? [];
    const anchors = (macroData.anchor_nodes ?? []).length > 0 ? macroData.anchor_nodes ?? [] : macroData.anchors ?? [];
    const cast = macroData.cast ?? [];
    const castPart =
      cast.length > 0
        ? locale === "en"
          ? ` · Cast ${cast.length}`
          : locale === "zh-Hans"
            ? ` · 人物 ${cast.length} 位`
            : ` · 人物 ${cast.length} 位`
        : "";
    if (locale === "en") return `Volumes ${volumes.length} · Milestones ${anchors.length}${castPart}`;
    if (locale === "zh-Hans") return `分卷 ${volumes.length} · 里程碑 ${anchors.length}${castPart}`;
    return `分卷 ${volumes.length} · 里程碑 ${anchors.length}${castPart}`;
  }, [locale, macroData]);

  const preambleHasNonLlmSummary = useMemo(() => {
    if (!writingPreamble || chapterId <= 1) return false;
    const prev = writingPreamble.plot_progress.previous_chapter;
    if (plotSummarySourceNeedsRegenerate(prev.plot_summary_source)) {
      return true;
    }
    return writingPreamble.plot_progress.recent_summaries.some((r) => plotSummarySourceNeedsRegenerate(r.plot_summary_source));
  }, [writingPreamble, chapterId]);

  async function handleRegenerateChapterSummary(targetChapterId: number) {
    if (!storyId) return;
    setRegenSummaryBusyChapter(targetChapterId);
    setError("");
    try {
      await regenerateChapterSummary(storyId, targetChapterId);
      const p = await fetchWritingPreamble(storyId, chapterId);
      setWritingPreamble(p);
    } catch (err) {
      reportApiError(err, "errors.regenerateSummaryFailed");
    } finally {
      setRegenSummaryBusyChapter(null);
    }
  }

  async function handleCreateStory(payload: StoryInput) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const story = await createStory(payload);
      setStoryId(String(story.story_id));
      setStoryTitle(payload.title);
      setStoryConfigSnapshot(payload);
      setPersistedStoryConfig(payload);
      setConfigurationLocked(false);
      setConfigVersion((v) => v + 1);
      setWorkflow(null);
      setMacroData(null);
      setGraph(null);
      setChapters([]);
      setSelectedChapter(null);
      setWritingPreamble(null);
      setHasExportedChapter(false);
      setHasExportedProject(false);
      setNavCount(0);
      setFlowStartedAt(Date.now());
      setStageVisitCount({ projectSetup: 1, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
      setView("setup");
    } catch (err) {
      reportApiError(err, "errors.createStoryFailed");
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
    setWritingPreamble(null);
    setStoryConfigSnapshot(null);
    setPersistedStoryConfig(null);
    setConfigurationLocked(false);
    setHasExportedChapter(false);
    setHasExportedProject(false);
    setNavCount(0);
    setFlowStartedAt(null);
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
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
    setWritingPreamble(null);
    setStoryConfigSnapshot(null);
    setPersistedStoryConfig(null);
    setConfigurationLocked(false);
    setHasExportedChapter(false);
    setHasExportedProject(false);
    setNavCount(0);
    setFlowStartedAt(null);
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
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
      const nextConfig = storyDetailToInput(detail, storyConfigSnapshot?.output_language ?? "zh-Hant");
      setStoryConfigSnapshot(nextConfig);
      setPersistedStoryConfig(nextConfig);
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
        storylines: snap.storylines ?? [],
        anchor_nodes: snap.anchor_nodes ?? [],
        cast: snap.cast,
        protagonist_character_id: snap.protagonist_character_id,
        macro_topology_mode: snap.macro_topology_mode,
        topology_locked: snap.topology_locked,
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
      setHasExportedChapter(false);
      setHasExportedProject(false);
      setNavCount(0);
      setFlowStartedAt(Date.now());
      setStageVisitCount({ projectSetup: 1, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
      setView("setup");
    } catch (err) {
      reportApiError(err, "errors.loadStoryFailed");
    } finally {
      setBusy(false);
    }
  }

  async function handleMacroCompile() {
    if (!storyId) return;
    setBusy(true);
    setCompileInProgress(true);
    setCompileProgress({ status: "QUEUED", percent: 5, message: "Macro compile queued..." });
    setError("");
    setNotice("");
    try {
      if (!configurationLocked && isStoryConfigDirty(storyConfigSnapshot, persistedStoryConfig) && storyConfigSnapshot) {
        const confirmed = window.confirm(
          locale === "en"
            ? "Unsaved story settings detected (including output language). Save settings before running compile?"
            : locale === "zh-Hans"
              ? "检测到未保存的故事设置（含输出语言）。是否先保存设置再执行编译？"
              : "偵測到未儲存的故事設定（包含輸出語言）。是否先儲存設定再執行 compile？",
        );
        if (!confirmed) {
          setNotice(t("setup.compileCancelledNotice"));
          return;
        }
        await patchStory(storyId, {
          title: storyConfigSnapshot.title,
          premise: storyConfigSnapshot.premise,
          target_total_words: storyConfigSnapshot.target_total_words,
          branch_count_override: storyConfigSnapshot.branch_count_override ?? null,
          plan_retry_limit: storyConfigSnapshot.plan_retry_limit,
          draft_loop_retry_limit: storyConfigSnapshot.draft_loop_retry_limit,
          macro_author_notes: storyConfigSnapshot.macro_author_notes ?? "",
          cast_seed: storyConfigSnapshot.cast_seed ?? [],
          output_language: normalizeOutputLanguage(storyConfigSnapshot.output_language),
        });
        setPersistedStoryConfig(storyConfigSnapshot);
      }
      const result = await macroCompile(storyId, (progress) => {
        setCompileProgress(progress);
      });
      setMacroData(result);
      setGraph(await fetchGraph(storyId));
      try {
        const detail = await fetchStoryDetail(storyId);
        const nextConfig = storyDetailToInput(detail, storyConfigSnapshot?.output_language ?? "zh-Hant");
        setStoryConfigSnapshot(nextConfig);
        setPersistedStoryConfig(nextConfig);
      } catch {
        /* optional refresh */
      }
    } catch (err) {
      reportApiError(err, "errors.macroCompileFailed");
    } finally {
      setCompileInProgress(false);
      setCompileProgress(null);
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
        branch_count_override: payload.branch_count_override ?? null,
        plan_retry_limit: payload.plan_retry_limit,
        draft_loop_retry_limit: payload.draft_loop_retry_limit,
        macro_author_notes: payload.macro_author_notes ?? "",
        cast_seed: payload.cast_seed ?? [],
        output_language: normalizeOutputLanguage(payload.output_language),
      });
      setStoryConfigSnapshot(payload);
      setPersistedStoryConfig(payload);
      setStoryTitle(payload.title);
    } catch (err) {
      reportApiError(err, "errors.saveSettingsFailed");
    } finally {
      setBusy(false);
    }
  }

  async function finalizeWorkflowRunUi(runId: string) {
    try {
      const wf = await fetchWorkflow(runId);
      setWorkflow(wf);
      if (String(wf.state.workflow_status ?? "") === "COMPLETED") {
        setView("review");
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
      reportApiError(err, "errors.finalizeWorkflowFailed");
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
          setError(localizeUserFacingError(err.message, t));
          setBusy(false);
        })();
      },
    });
  }

  /** After HITL apply returns: resume SSE if run is in progress, else finalize or stay idle at next HITL. */
  function applyHitlWorkflowResponse(wf: WorkflowPayload) {
    setError("");
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
    if (manualAnchorSelectionOpen && selectedAnchorIds.length < 1) {
      setError(
        locale === "en"
          ? "Select at least one anchor in advanced mode, or collapse to let director decide."
          : locale === "zh-Hans"
            ? "进阶模式下请至少选择一个 anchor，或收起选项改由 director 自动决定。"
            : "進階模式下請至少選擇一個 anchor，或收起選項改由 director 自動決定。",
      );
      return;
    }
    setError("");
    setNotice("");
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    setWorkflow(null);
    setSelectedChapter(null);
    setBusy(true);
    try {
      const runOptions = {
        chapterOutline,
        chapterHardRules,
        aiFreedomLevel,
        selectedAnchorIds: manualAnchorSelectionOpen ? selectedAnchorIds : undefined,
        nextAnchorIds: manualAnchorSelectionOpen ? autoNextAnchorIds : undefined,
      };
      const initial = await runChapter(storyId, chapterId, {
        ...runOptions,
      });
      setWorkflow(initial);
      try {
        const detail = await fetchStoryDetail(storyId);
        const nextConfig = storyDetailToInput(detail, storyConfigSnapshot?.output_language ?? "zh-Hant");
        setStoryConfigSnapshot(nextConfig);
        setPersistedStoryConfig(nextConfig);
        setConfigurationLocked(detail.configuration_locked);
      } catch {
        setConfigurationLocked(true);
      }
      setConfigVersion((v) => v + 1);
      const runId = initial.run.run_id;
      setView("write");
      attachWorkflowEventStream(runId);
    } catch (err) {
      reportApiError(err, "errors.runChapterFailed");
    } finally {
      setBusy(false);
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
        output_language: "zh-Hant",
      } satisfies StoryInput);
    const vols = macroData?.volumes ?? [];
    const ancs = (macroData?.anchor_nodes ?? []).length > 0 ? macroData?.anchor_nodes ?? [] : macroData?.anchors ?? [];
    const includeMacro = vols.length > 0 && ancs.length > 0 && macroData;
    const payload: StoryProjectBundlePayload = {
      kind: "story_project_bundle",
      version: 1,
      story: includeMacro ? { ...story, bible: {} } : story,
    };
    if (includeMacro && macroData) {
      payload.macro_plan = buildMacroPutBody(macroData);
    }
    downloadJsonFile(`${storyId}-project.json`, payload);
    setHasExportedProject(true);
  }

  async function importProjectBundle(jsonText: string, mode: ImportMergeMode) {
    if (!storyId || configurationLocked) return;
    const { story: parsedStory, macro_plan: parsedMacroRaw } = parseProjectBundleJson(jsonText);
    const parsedMacro = parsedMacroRaw ? namespaceMacroPlanIdsForStory(parsedMacroRaw, storyId) : undefined;
    const modeLabel =
      mode === "replace"
        ? locale === "en"
          ? "Replace"
          : locale === "zh-Hans"
            ? "覆盖"
            : "覆蓋"
        : locale === "en"
          ? "Merge"
          : locale === "zh-Hans"
            ? "合并"
            : "合併";
    const storySummary = parsedStory
      ? locale === "en"
        ? `Story: ${parsedStory.title}`
        : `故事：${parsedStory.title}`
      : locale === "en"
        ? "(No story block)"
        : locale === "zh-Hans"
          ? "（无故事区块）"
          : "（無故事區塊）";
    const nodeCount = (parsedMacro?.anchor_nodes ?? []).length;
    const slCount = (parsedMacro?.storylines ?? []).length;
    const macroSummary = parsedMacro
      ? locale === "en"
        ? `Macro: Volumes ${parsedMacro.volumes.length} · DAG nodes ${nodeCount} · Storylines ${slCount} · Cast ${parsedMacro.cast.length}`
        : locale === "zh-Hans"
          ? `宏观：分卷 ${parsedMacro.volumes.length} · 剧情节点 ${nodeCount} · 剧情线 ${slCount} · 人物 ${parsedMacro.cast.length}`
          : `宏觀：分卷 ${parsedMacro.volumes.length} · 劇情節點 ${nodeCount} · 劇情線 ${slCount} · 人物 ${parsedMacro.cast.length}`
      : locale === "en"
        ? "(No macro block)"
        : locale === "zh-Hans"
          ? "（无宏观区块）"
          : "（無宏觀區塊）";
    const proceed = window.confirm(
      locale === "en"
        ? `About to import project JSON (${modeLabel})\n${storySummary}\n${macroSummary}\n\nContinue?`
        : locale === "zh-Hans"
          ? `即将导入项目 JSON（${modeLabel}）\n${storySummary}\n${macroSummary}\n\n确定继续吗？`
          : `即將匯入專案 JSON（${modeLabel}）\n${storySummary}\n${macroSummary}\n\n確定要繼續嗎？`,
    );
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
          output_language: "zh-Hant",
        } satisfies StoryInput);
      const merged = mode === "replace" ? parsedStory : mergeStorySettings(current, parsedStory);
      if (parsedMacro && (!merged.bible || Object.keys(merged.bible).length === 0) && isObjectRecord(parsedMacro.bible)) {
        merged.bible = parsedMacro.bible as Record<string, unknown>;
      }
      await patchStory(storyId, {
        title: merged.title,
        premise: merged.premise,
        target_total_words: merged.target_total_words,
        branch_count_override: merged.branch_count_override ?? null,
        plan_retry_limit: merged.plan_retry_limit,
        draft_loop_retry_limit: merged.draft_loop_retry_limit,
        macro_author_notes: merged.macro_author_notes ?? "",
        cast_seed: merged.cast_seed ?? [],
        output_language: normalizeOutputLanguage(merged.output_language),
      });
      setStoryConfigSnapshot(merged);
      setPersistedStoryConfig(merged);
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
        storylines: putResult.storylines ?? [],
        anchor_nodes: putResult.anchor_nodes ?? [],
        cast: putResult.cast,
        protagonist_character_id: putResult.protagonist_character_id,
        macro_topology_mode: putResult.macro_topology_mode,
        topology_locked: putResult.topology_locked,
      });
      try {
        setMacroData(await fetchMacroSnapshot(storyId));
      } catch {
        /* fallback to put result above */
      }
    }

    if (parsedStory || parsedMacro) {
      setConfigVersion((v) => v + 1);
      setNotice(
        locale === "en"
          ? `Project JSON imported (${modeLabel})`
          : locale === "zh-Hans"
            ? `项目 JSON 已导入（${modeLabel}）`
            : `專案 JSON 已匯入（${modeLabel}）`,
      );
    }
  }

  function askImportMode(): ImportMergeMode {
    const replace = window.confirm(
      locale === "en"
        ? "Import mode: OK = Replace current data; Cancel = Merge (prefer existing values)."
        : locale === "zh-Hans"
          ? "导入模式：按“确定”= 覆盖当前数据；按“取消”= 合并（已有值优先）"
          : "匯入模式：按「確定」= 覆蓋目前資料；按「取消」= 合併（已有值優先）",
    );
    return replace ? "replace" : "merge";
  }

  async function handleToolbarImportProjectBundle(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !storyId || configurationLocked) return;
    const mode = askImportMode();
    setBusy(true);
    setError("");
    try {
      const text = await file.text();
      await importProjectBundle(text, mode);
    } catch (err) {
      reportApiError(err, "errors.importJsonFailed");
    } finally {
      setBusy(false);
    }
  }

  function patchSetupAnchorNode(patch: Partial<NonNullable<MacroCompileData["anchor_nodes"]>[number]>) {
    if (!macroData || !setupSelectedAnchorNode) return;
    const nextNodes = (macroData.anchor_nodes ?? []).map((n) =>
      String(n.id) === String(setupSelectedAnchorNode.id) ? { ...n, ...patch } : n,
    );
    setMacroData({ ...macroData, anchor_nodes: nextNodes });
  }

  async function persistSetupDagChanges() {
    if (!storyId || !macroData || configurationLocked) return;
    setBusy(true);
    setError("");
    try {
      const payload = buildMacroPutBody(macroData);
      const updated = await putMacroPlan(storyId, payload);
      setMacroData({
        story_id: updated.story_id,
        bible: updated.bible ?? {},
        macro_author_notes: updated.macro_author_notes,
        cast_seed: updated.cast_seed,
        volumes: updated.volumes,
        anchors: updated.anchors,
        storylines: updated.storylines ?? [],
        anchor_nodes: updated.anchor_nodes ?? [],
        cast: updated.cast,
        protagonist_character_id: updated.protagonist_character_id,
        macro_topology_mode: updated.macro_topology_mode,
        topology_locked: updated.topology_locked,
      });
      setNotice(locale === "en" ? "DAG changes saved." : locale === "zh-Hans" ? "DAG 变更已保存。" : "DAG 變更已儲存。");
    } catch (err) {
      reportApiError(err, "errors.saveDagFailed");
    } finally {
      setBusy(false);
    }
  }

  async function runHitlAction<TPayload>(
    send: (runId: string, payload: TPayload) => Promise<WorkflowPayload>,
    payload: TPayload,
    fallbackI18nKey: string,
  ) {
    if (!workflow) return;
    setBusy(true);
    setError("");
    try {
      applyHitlWorkflowResponse(await send(workflow.run.run_id, payload));
    } catch (err) {
      reportApiError(err, fallbackI18nKey);
      setBusy(false);
    }
  }

  const hitlHandlers = {
    onDecision: async (optionId: string) => runHitlAction(sendHitlDecision, optionId, "errors.sendChoiceFailed"),
    onOutlineEdit: async (payload: Parameters<typeof sendOutlineEdit>[1]) =>
      runHitlAction(sendOutlineEdit, payload, "errors.applyOutlineFailed"),
    onDraftEdit: async (payload: Parameters<typeof sendDraftEdit>[1]) =>
      runHitlAction(sendDraftEdit, payload, "errors.applyDraftFailed"),
    onStateInjection: async (payload: Parameters<typeof sendStateInjection>[1]) =>
      runHitlAction(sendStateInjection, payload, "errors.writeDataFailed"),
    onDirectorPatch: async (payload: Parameters<typeof sendDirectorPatch>[1]) =>
      runHitlAction(sendDirectorPatch, payload, "errors.directorPatchFailed"),
    onExtractionRemap: async (payload: Parameters<typeof sendExtractionRemap>[1]) =>
      runHitlAction(sendExtractionRemap, payload, "errors.extractionRemapFailed"),
    onAnchorResolution: async (payload: Parameters<typeof sendAnchorResolution>[1]) =>
      runHitlAction(sendAnchorResolution, payload, "errors.anchorResolutionFailed"),
    onAnchorDelay: async (payload: Parameters<typeof sendAnchorDelay>[1]) =>
      runHitlAction(sendAnchorDelay, payload, "errors.anchorDelayFailed"),
    onContextPrune: async (payload: Parameters<typeof sendContextPrune>[1]) =>
      runHitlAction(sendContextPrune, payload, "errors.contextPruneFailed"),
  };

  const showStorySection = Boolean(storyId) || view === "setup";
  const compileProgressText = useMemo(() => {
    if (!compileInProgress) return "";
    const st = String(compileProgress?.status ?? "QUEUED").toUpperCase();
    if (st === "RUNNING") return t("compile.progress.running");
    if (st === "SUCCEEDED") return t("compile.progress.succeeded");
    if (st === "FAILED") return t("compile.progress.failed");
    return t("compile.progress.queued");
  }, [compileInProgress, compileProgress?.status, t]);
  const storySectionLabel =
    storyTitle.trim() || (storyId ? `${storyId.slice(0, 10)}…` : "");
  const hasMacroCompiled = Boolean(
    macroData &&
      macroData.volumes.length > 0 &&
      (((macroData.anchor_nodes ?? []).length > 0) || ((macroData.anchors ?? []).length > 0)),
  );
  const hasChapterRun = Boolean(workflow || chapters.length > 0);
  const hasReviewed = Boolean(selectedChapter || chapters.length > 0);
  const hasExported = hasExportedChapter || hasExportedProject;
  const workflowMiniStatus = useMemo(() => {
    if (!workflow) return locale === "en" ? "Chapter not run yet" : locale === "zh-Hans" ? "尚未执行章节" : "尚未執行章節";
    const status = String(workflow.state.workflow_status ?? workflow.run.status ?? "");
    if (status === "WAITING_HITL") return locale === "en" ? "Waiting for human decision" : locale === "zh-Hans" ? "等待人工决策" : "等待人工決策";
    if (status === "COMPLETED") return locale === "en" ? "Chapter workflow completed" : locale === "zh-Hans" ? "章节流程已完成" : "章節流程已完成";
    if (status === "FAILED") return locale === "en" ? "Chapter workflow failed" : locale === "zh-Hans" ? "章节流程失败" : "章節流程失敗";
    return locale === "en" ? "Chapter workflow running" : locale === "zh-Hans" ? "章节流程执行中" : "章節流程執行中";
  }, [locale, workflow]);
  const failureNotice = useMemo(() => {
    if (!workflow) return "";
    const status = String(workflow.state.workflow_status ?? workflow.run.status ?? "");
    if (status !== "FAILED") return "";
    const failureType = String(workflow.state.failure_type ?? "");
    const timeoutBucket = String(workflow.state.timeout_bucket ?? "");
    const resetDone = workflow.state.thread_reset_done === true;
    const commitExecuted = workflow.state.commit_executed === true;
    const reason = String(workflow.state.hitl_reason ?? workflow.run.hitl_reason ?? "").trim();
    const typeLabel =
      failureType === "TIMEOUT" ? t("workflow.failure.typeTimeout") : t("workflow.failure.typeWorkflow");
    const bucketLabel =
      timeoutBucket === "llm"
        ? t("workflow.failure.bucketLlm")
        : timeoutBucket === "logic"
          ? t("workflow.failure.bucketLogic")
          : "";
    const commitLabel = commitExecuted ? t("workflow.failure.commitYes") : t("workflow.failure.commitNo");
    const resetLabel = resetDone ? t("workflow.failure.threadResetYes") : t("workflow.failure.threadResetNo");
    const reasonLine = reason ? t("workflow.failure.reasonLine", undefined, { reason }) : "";
    return t("workflow.failure.notice", undefined, {
      type: typeLabel,
      bucket: bucketLabel,
      commit: commitLabel,
      reset: resetLabel,
      reasonLine,
    });
  }, [workflow, t]);
  function handleViewChange(nextView: AppView) {
    if (nextView === view) return;
    const markStageVisit = (stage: TaskFlowStageId) => {
      setStageVisitCount((prev) => ({ ...prev, [stage]: prev[stage] + 1 }));
      setNavCount((prev) => prev + 1);
    };
    if (!storyId && nextView !== "library" && nextView !== "setup") {
      setNotice(
        locale === "en"
          ? "Select or create a story in library first."
          : locale === "zh-Hans"
            ? "请先在故事库选择或创建故事。"
            : "請先在故事庫選擇或建立故事。",
      );
      setView("library");
      return;
    }
    if (nextView === "write" && !hasMacroCompiled) {
      setNotice(
        locale === "en"
          ? "Finish macro compile in Setup & Planning first."
          : locale === "zh-Hans"
            ? "请先在“设置与规划”完成世界观编译。"
            : "請先在「設定與規劃」完成世界觀編譯。",
      );
      setView("setup");
      return;
    }
    if ((nextView === "review" || nextView === "export") && !hasChapterRun) {
      setNotice(
        locale === "en"
          ? "Run at least one chapter workflow first."
          : locale === "zh-Hans"
            ? "请先执行至少一轮章节流程。"
            : "請先執行至少一輪章節流程。",
      );
      setView("write");
      return;
    }
    if (nextView === "setup") {
      markStageVisit(hasMacroCompiled ? "planStructure" : "projectSetup");
    } else if (nextView === "write") {
      markStageVisit("writeChapter");
    } else if (nextView === "review" || nextView === "graph") {
      markStageVisit("reviewFix");
    } else if (nextView === "export") {
      markStageVisit("export");
    }
    setView(nextView);
  }

  return (
    <AppShell
      activeView={view}
      onViewChange={handleViewChange}
      hasSelectedStory={Boolean(storyId)}
      showStorySection={showStorySection}
      storySectionLabel={storySectionLabel}
      workflowMiniStatus={workflowMiniStatus}
    >
      <div className="mx-4 mt-4 min-h-[3.5rem]">
        {error ? (
          <div className="rounded-xl border border-error/40 bg-error/10 px-4 py-3 font-label text-sm text-error">{error}</div>
        ) : null}
        {!error && failureNotice ? (
          <div className="mt-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 font-label text-sm text-on-surface">
            {failureNotice}
          </div>
        ) : null}
        {!error && notice ? (
          <div className="rounded-xl border border-secondary/35 bg-secondary/10 px-4 py-3 font-label text-sm text-secondary">{notice}</div>
        ) : null}
      </div>
      {!error && alignmentRulesPromptActive && view !== "setup" && view !== "library" ? (
        <div className="mx-4 mt-4 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 font-label text-sm text-on-surface">
          偵測到複雜智鬥，需補充硬性規則。你可以先留在此頁查看流程，或前往「故事設定」填寫 `chapter_hard_rules`。
          <button type="button" className="btn-secondary ml-3" onClick={() => setView("setup")}>
            前往故事設定
          </button>
        </div>
      ) : null}
      {view === "library" ? (
        <div className="min-h-[calc(100vh-12rem)]">
          <StoryLibrary
            onSelectStory={handleSelectStoryFromLibrary}
            onNewStory={handleNewStoryFromLibrary}
            onStoryDeleted={handleStoryDeleted}
            busy={busy}
            blockSelectingStories={workflowConflictLocked}
          />
        </div>
      ) : null}

      {view === "setup" ? (
        <div className="min-h-[calc(100vh-12rem)] px-4 pb-12 pt-8 md:px-10 lg:px-12">
          <div className="mb-10 max-w-7xl">
            <span className="mb-2 block font-label text-xs font-semibold uppercase tracking-[0.3em] text-secondary">
              {locale === "en" ? "Project Setup" : locale === "zh-Hans" ? "项目设置" : "專案設定"}
            </span>
            <h1 className="mb-3 font-headline text-4xl font-black tracking-tighter text-on-surface">
              {locale === "en" ? "Story Settings" : locale === "zh-Hans" ? "故事设置" : "故事設定"}
            </h1>
            <p className="max-w-2xl font-body text-lg italic text-on-surface-variant">
              {locale === "en"
                ? "Define premise and parameters here, then run world compile to generate volumes, cast, and milestones."
                : locale === "zh-Hans"
                  ? "在此整理故事梗概与参数，并执行世界观编译以生成分卷、人物与里程碑。"
                  : "在此整理故事梗概與參數，並執行世界觀編譯以生成分卷、人物與里程碑。"}
            </p>
          </div>

          {storyId && !configurationLocked ? (
            <div className="mb-4 max-w-7xl rounded-xl border border-tertiary/25 bg-tertiary/5 px-4 py-3 font-body text-sm leading-relaxed text-on-surface">
              <span className="font-headline font-bold text-tertiary">
                {locale === "en" ? "Re-run World Compile" : locale === "zh-Hans" ? "重新执行世界观编译" : "重新執行世界觀編譯"}
              </span>
              {locale === "en"
                ? " will overwrite auto-generated cast nodes and current world bible/volumes/milestones. Manual edits on those generated nodes will be lost."
                : locale === "zh-Hans"
                  ? "会覆写自动生成的角色节点，以及当前保存的世界观总表、分卷与里程碑；若你曾在图谱手动修改这些自动生成角色，这些改动会消失。"
                  : "會覆寫自動產生的角色節點，以及目前儲存的世界觀總表、分卷與里程碑；若你曾在圖譜上手動改過這些自動產生的角色，那些修改會消失。"}
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
                {locale === "en" ? "Compile World & Structure" : locale === "zh-Hans" ? "生成世界观与结构" : "產生世界觀與結構"}
              </button>
              <button type="button" className="btn-secondary" onClick={storyId ? exportProjectBundle : undefined} disabled={!storyId || busy}>
                {locale === "en" ? "Export Project JSON" : locale === "zh-Hans" ? "导出项目 JSON" : "匯出專案 JSON"}
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => toolbarImportInputRef.current?.click()}
                disabled={!storyId || busy || configurationLocked}
              >
                {locale === "en" ? "Import Project JSON" : locale === "zh-Hans" ? "导入项目 JSON" : "匯入專案 JSON"}
              </button>
              <input
                ref={toolbarImportInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => void handleToolbarImportProjectBundle(e)}
              />
            </div>
            {compileInProgress ? (
              <div className="rounded-xl border border-secondary/30 bg-secondary/8 px-3 py-2">
                <p className="font-mono text-xs text-secondary">
                  <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-secondary" />
                  {compileProgressText} ({Math.max(0, Math.min(100, Number(compileProgress?.percent ?? 5)))}%)
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-container-highest/70">
                  <div
                    className="h-full rounded-full bg-secondary transition-[width] duration-300"
                    style={{ width: `${Math.max(0, Math.min(100, Number(compileProgress?.percent ?? 5)))}%` }}
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="mb-6 max-w-7xl rounded-xl border border-outline-variant/10 bg-surface-container-low px-6 py-4 font-label text-sm text-on-surface-variant">
            <span className="text-secondary">{locale === "en" ? "Story ID" : locale === "zh-Hans" ? "故事编号" : "故事編號"}</span>{" "}
            {storyId || (locale === "en" ? "Not created" : locale === "zh-Hans" ? "未建立" : "未建立")} · {storySummary}
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
              <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/50 p-3">
                <div className="mb-3 px-1">
                  <h3 className="font-label text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                    {locale === "en" ? "World & Structure Editor" : locale === "zh-Hans" ? "世界观与结构编修" : "世界觀與結構編修"}
                  </h3>
                </div>
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
          <div className="mt-8 max-w-7xl">
            <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/50 p-3">
              <div className="mb-3 px-1">
                <h3 className="font-label text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                  {locale === "en" ? "Anchor DAG GraphView" : locale === "zh-Hans" ? "Anchor DAG 图谱" : "Anchor DAG 圖譜"}
                </h3>
              </div>
              {setupAnchorNodes.length > 0 ? (
                <div className="space-y-3">
                  <AnchorNodesGraphView
                    nodes={setupAnchorNodes.map((n) => ({
                      id: String(n.id),
                      title: String(n.title ?? ""),
                      status: n.status,
                      node_kind: n.node_kind,
                      storyline_ids: [...(n.storyline_ids ?? [])],
                      depends_on: [...(n.depends_on ?? [])],
                    }))}
                    storylines={macroData?.storylines}
                    selectedId={setupSelectedAnchorNodeId}
                    onSelect={(nodeId) => setSetupSelectedAnchorNodeId(nodeId)}
                    height={420}
                  />
                  <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-on-surface-variant">
                        {locale === "en" ? "Node Detail Card" : locale === "zh-Hans" ? "节点详情卡" : "節點詳情卡"}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="rounded-lg border border-secondary/40 px-3 py-1.5 text-xs font-semibold text-secondary"
                          onClick={persistSetupDagChanges}
                          disabled={!storyId || configurationLocked || busy}
                        >
                          {locale === "en" ? "Save DAG JSON" : locale === "zh-Hans" ? "保存 DAG JSON" : "儲存 DAG JSON"}
                        </button>
                      </div>
                    </div>
                    <p className="mb-2 text-[11px] text-on-surface-variant">
                      {locale === "en"
                        ? "Temporary mode: node add/remove is paused. You can edit side-arc node title/description only."
                        : locale === "zh-Hans"
                          ? "临时模式：暂停新增/删除节点，目前仅提供支线节点内容编辑。"
                          : "臨時模式：暫停新增/刪除節點，目前僅提供支線節點內容編輯。"}
                    </p>
                    {setupSelectedAnchorNode ? (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        <label className="text-xs text-on-surface-variant">
                          {locale === "en" ? "Node ID" : locale === "zh-Hans" ? "节点 ID" : "節點 ID"}
                          <input
                            value={String(setupSelectedAnchorNode.id)}
                            disabled
                            className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="text-xs text-on-surface-variant">
                          {locale === "en" ? "Depends On" : locale === "zh-Hans" ? "依赖节点" : "依賴節點"}
                          <input
                            value={(setupSelectedAnchorNode.depends_on ?? []).join(", ")}
                            disabled
                            className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="text-xs text-on-surface-variant">
                          {locale === "en" ? "Status" : locale === "zh-Hans" ? "状态" : "狀態"}
                          <input
                            value={
                              String(setupSelectedAnchorNode.status ?? "LOCKED").toUpperCase() === "RESOLVED"
                                ? locale === "en"
                                  ? "Resolved"
                                  : locale === "zh-Hans"
                                    ? "已解决"
                                    : "已解決"
                                : String(setupSelectedAnchorNode.status ?? "LOCKED").toUpperCase() === "UNLOCKED"
                                  ? locale === "en"
                                    ? "Unlocked"
                                    : locale === "zh-Hans"
                                      ? "已解锁"
                                      : "已解鎖"
                                  : locale === "en"
                                    ? "Locked"
                                    : locale === "zh-Hans"
                                      ? "已锁定"
                                      : "已上鎖"
                            }
                            disabled
                            className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="text-xs text-on-surface-variant">
                          {locale === "en" ? "Title" : locale === "zh-Hans" ? "标题" : "標題"}
                          <input
                            value={String(setupSelectedAnchorNode.title ?? "")}
                            onChange={(e) => patchSetupAnchorNode({ title: e.target.value })}
                            disabled={!setupCanEditSelectedNode || configurationLocked}
                            className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="text-xs text-on-surface-variant md:col-span-2">
                          {locale === "en" ? "Description" : locale === "zh-Hans" ? "描述" : "描述"}
                          <textarea
                            value={String(setupSelectedAnchorNode.description ?? "")}
                            onChange={(e) => patchSetupAnchorNode({ description: e.target.value })}
                            disabled={!setupCanEditSelectedNode || configurationLocked}
                            rows={3}
                            className="mt-1 w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                          />
                        </label>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-4 text-sm text-on-surface-variant">
                  {locale === "en"
                    ? "No anchor_nodes yet. Run macro compile first."
                    : locale === "zh-Hans"
                      ? "尚无 anchor_nodes，请先执行 macro compile。"
                      : "尚無 anchor_nodes，請先執行 macro compile。"}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {view === "review" ? (
        <div className="flex min-h-[calc(100vh-12rem)] flex-col bg-surface-container-lowest lg:flex-row">
          <ChapterReader
            storyId={storyId}
            currentChapterId={selectedChapter?.chapter_id ?? chapterId}
            chapters={chapters}
            chapter={selectedChapter}
            outputLanguage={normalizeOutputLanguage(storyConfigSnapshot?.output_language ?? "zh-Hant")}
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
                  reportApiError(err, "errors.loadChapterFailed");
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
                setHasExportedChapter(true);
              } catch (err) {
                reportApiError(err, "errors.downloadChapterFailed");
              } finally {
                setBusy(false);
              }
            }}
            rightRail={
              <div className="flex flex-col gap-4 p-4">
                <WorkflowProgressTrack workflow={workflow} compact />
                <WorkflowMonitor workflow={workflow} variant="compact" />
                <HitlPanel
                  workflow={workflow}
                  graph={graph}
                  storyId={storyId || null}
                  variant="compact"
                  busy={busy}
                  workflowError={workflowHitlActive ? error : ""}
                  {...hitlHandlers}
                />
                <AgentOutputView workflow={workflow} variant="compact" />
              </div>
            }
          />
        </div>
      ) : null}

      {view === "graph" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background p-4 md:p-8">
          <div className="mb-4 flex items-center justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={() => setView("setup")}>
              {locale === "en" ? "Back to Setup & Planning" : locale === "zh-Hans" ? "回到设置与规划" : "回到設定與規劃"}
            </button>
            <span className="rounded-full border border-secondary/20 bg-secondary/10 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-secondary">
              {locale === "en" ? "Read Only" : locale === "zh-Hans" ? "仅供阅览" : "僅供閱覽"}
            </span>
          </div>
          <GraphView graph={graph} protagonistCharacterId={macroData?.protagonist_character_id} />
        </div>
      ) : null}

      {view === "write" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
            <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-4 shadow-glow">
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(180px,220px)_minmax(220px,280px)_auto] lg:items-end">
                <div className="flex flex-col gap-1.5">
                  <span className="font-label text-[10px] uppercase tracking-wider text-outline">
                    {locale === "en" ? "Chapter" : locale === "zh-Hans" ? "章节" : "章節"}
                  </span>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      value={chapterId}
                      onChange={(e) => setChapterId(Number(e.target.value))}
                      className="h-10 w-24 rounded-lg border border-outline-variant/20 bg-surface-container-highest px-2 py-2 text-on-surface"
                    />
                    <button
                      type="button"
                      className="btn-secondary h-10"
                      title={locale === "en" ? "Set to latest existing chapter" : locale === "zh-Hans" ? "将章节设为当前最新章节" : "將章節選擇設為目前已有的最大章節"}
                      disabled={!storyId || busy || chapters.length === 0}
                      onClick={() => setChapterId(latestChapterId)}
                    >
                      <span className="material-symbols-outlined align-middle text-base">skip_next</span>
                      {locale === "en" ? "Latest" : locale === "zh-Hans" ? "最新章" : "最新章"}
                    </button>
                  </div>
                </div>
                <label className="flex min-w-0 flex-col gap-1.5 font-body text-sm text-on-surface">
                  <span className="font-label text-[10px] uppercase tracking-wider text-outline">
                    {locale === "en" ? "AI Freedom" : locale === "zh-Hans" ? "创作自由度" : "創作自由度"}
                  </span>
                  <select
                    value={aiFreedomLevel}
                    onChange={(e) => setAiFreedomLevel(e.target.value as AiFreedomLevel)}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="auteur-input h-10 w-full text-sm"
                  >
                    <option value="strict">
                      {locale === "en"
                        ? "Strict (fixed facts cannot change; outline must be specific)"
                        : locale === "zh-Hans"
                          ? "严格（已写明处不可改；大纲需更具体）"
                          : "嚴格（已寫明處不可改；大綱需較具體才 FULL 綁定）"}
                    </option>
                    <option value="balanced">{locale === "en" ? "Balanced (default)" : locale === "zh-Hans" ? "平衡（预设）" : "平衡（預設）"}</option>
                    <option value="wild">
                      {locale === "en"
                        ? "Wild (more creative fill-in, still marked [AI_INVENTION])"
                        : locale === "zh-Hans"
                          ? "狂野（留白脑补更多，仍标 [AI_INVENTION]）"
                          : "狂野（留白腦補多，仍標 [AI_INVENTION]）"}
                    </option>
                  </select>
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    className="btn-primary-gradient h-10"
                    onClick={handleRunChapter}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                  >
                    {locale === "en" ? "Run Chapter" : locale === "zh-Hans" ? "撰写本章" : "撰寫本章"}
                  </button>
                </div>
              </div>
              {chapterAlreadyCompleted ? (
                <div className="mt-3">
                  <span className="rounded-full border border-tertiary/30 bg-tertiary/10 px-2 py-1 text-xs text-tertiary">
                    {locale === "en"
                      ? `Chapter ${chapterId} already completed. Change chapter number to continue.`
                      : locale === "zh-Hans"
                        ? `第 ${chapterId} 章已完成，请改章节号后再执行`
                        : `第 ${chapterId} 章已完成，請改章號後再執行`}
                  </span>
                </div>
              ) : null}
              <div className="mt-3 rounded-lg border border-outline-variant/15 bg-surface-container-high/30 p-3">
                <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
                  {locale === "en" ? "Start Chapter Anchors" : locale === "zh-Hans" ? "开章锚点选择" : "開章 Anchor 選點"}
                </p>
                <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low px-3 py-2">
                  <p className="text-xs text-on-surface-variant">
                    {locale === "en"
                      ? "Default: keep collapsed and run chapter directly. Director will pick anchors automatically."
                      : locale === "zh-Hans"
                        ? "默认：保持收起并直接运行章节，由 director 自动选择锚点。"
                        : "預設：保持收起並直接執行章節，由 director 自動選擇錨點。"}
                  </p>
                  <button
                    type="button"
                    className="mt-2 rounded-md border border-secondary/35 px-3 py-1.5 text-xs font-semibold text-secondary"
                    onClick={() => setManualAnchorSelectionOpen((v) => !v)}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                  >
                    {manualAnchorSelectionOpen
                      ? locale === "en"
                        ? "Hide Advanced Manual Selection"
                        : locale === "zh-Hans"
                          ? "收起进阶手动选择"
                          : "收起進階手動選擇"
                      : locale === "en"
                        ? "Show Advanced Manual Selection"
                        : locale === "zh-Hans"
                          ? "展开进阶手动选择"
                          : "展開進階手動選擇"}
                  </button>
                </div>
                {manualAnchorSelectionOpen ? (
                  chapterAnchorCandidates.length === 0 ? (
                    <p className="mt-2 text-xs text-on-surface-variant">
                      {locale === "en" ? "No unlocked anchor candidates yet." : locale === "zh-Hans" ? "目前没有可用的解锁锚点。" : "目前沒有可用的已解鎖 Anchor。"}
                    </p>
                  ) : (
                    <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
                      {chapterAnchorCandidates.map((n) => (
                        <label key={n.id} className="rounded-md border border-outline-variant/15 bg-surface-container-low px-2 py-2 text-xs text-on-surface">
                          <div className="mb-1 font-semibold">{n.title}</div>
                          <div className="mb-2 line-clamp-2 text-on-surface-variant">{n.description}</div>
                          <label className="inline-flex items-center gap-1">
                            <input
                              type="checkbox"
                              checked={selectedAnchorIds.includes(n.id)}
                              onChange={(e) =>
                                setSelectedAnchorIds((prev) => {
                                  const next = e.target.checked ? [...prev, n.id] : prev.filter((id) => id !== n.id);
                                  return Array.from(new Set(next)).slice(0, 2);
                                })
                              }
                              disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                            />
                            <span>{locale === "en" ? "Use For This Chapter" : locale === "zh-Hans" ? "用于本章" : "用於本章"}</span>
                          </label>
                        </label>
                      ))}
                    </div>
                  )
                ) : null}
                {manualAnchorSelectionOpen ? (
                  <p className="mt-2 text-[11px] text-on-surface-variant">
                    {locale === "en"
                      ? `Advanced mode enabled: director will be skipped. Selected anchors carry auto next-step anchors (window size = 2): ${autoNextAnchorIds.join(", ") || "auto-detecting..."}`
                      : locale === "zh-Hans"
                        ? `已启用进阶模式：将跳过 director。已选锚点会自动携带下一步锚点（window size = 2）：${autoNextAnchorIds.join("、") || "自动推断中…"}`
                        : `已啟用進階模式：將跳過 director。已選錨點會自動帶出下一步錨點（window size = 2）：${autoNextAnchorIds.join("、") || "自動推斷中…"}`
                    }
                  </p>
                ) : null}
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <div>
                  <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
                    {locale === "en" ? "Chapter Direction" : locale === "zh-Hans" ? "章节方向" : "Chapter Direction"}
                  </p>
                  <textarea
                    value={chapterOutline}
                    onChange={(e) => setChapterOutline(e.target.value)}
                    maxLength={2000}
                    rows={4}
                    placeholder={
                      locale === "en"
                        ? "e.g. advance mystery through dialogue, avoid combat scenes..."
                        : locale === "zh-Hans"
                          ? "例如：本章以对话推进谜底、避免打斗场面…"
                          : "例如：本章以對話推進謎底、避免打鬥場面…"
                    }
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
                  />
                  {chapterOutline.trim().length > 0 && chapterOutline.trim().length < OUTLINE_FULL_BINDING_MIN_CHARS ? (
                    <p className="mt-2 font-body text-xs text-secondary">
                      大綱較短（低於 {OUTLINE_FULL_BINDING_MIN_CHARS} 字）：流程會保留 AI 填坑權；strict 僅約束你已寫明的片段。
                    </p>
                  ) : null}
                </div>
                <div>
                  <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
                    {locale === "en" ? "Hard Rules for This Chapter" : locale === "zh-Hans" ? "本章硬性规则" : "本章硬性規則"}
                  </p>
                  <textarea
                    value={chapterHardRules}
                    onChange={(e) => setChapterHardRules(e.target.value)}
                    ref={chapterHardRulesRef}
                    maxLength={8000}
                    rows={4}
                    placeholder={
                      locale === "en"
                        ? "e.g. game rules, win conditions, immutable system laws..."
                        : locale === "zh-Hans"
                          ? "例如：游戏规则、胜负条件、不可违背的系统法则（POV 不可知底牌请标清）"
                          : "例如：遊戲規則、勝負條件、不可違背的系統法則（POV 不可知的底牌請標示清楚）"
                    }
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
                  />
                </div>
              </div>
              {storyId ? (
                <div className="mt-3 overflow-hidden rounded-xl border border-outline-variant/15 bg-surface-container/90">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-surface-container-highest/50"
                    onClick={() => setPreamblePanelOpen((o) => !o)}
                  >
                    <span className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="font-label text-[11px] font-bold uppercase tracking-wider text-secondary">
                        {locale === "en" ? "Pre-write Reference" : locale === "zh-Hans" ? "开写前参考" : "開寫前參考"}
                      </span>
                      <span className="truncate font-body text-sm text-on-surface-variant">
                        {locale === "en"
                          ? `Story progress (through chapter ${Math.max(0, chapterId - 1)})`
                          : locale === "zh-Hans"
                            ? `剧情进度（至第 ${Math.max(0, chapterId - 1)} 章）`
                            : `劇情進度（至第 ${Math.max(0, chapterId - 1)} 章）`}
                      </span>
                    </span>
                    <span className="material-symbols-outlined shrink-0 text-on-surface-variant">
                      {preamblePanelOpen ? "expand_less" : "expand_more"}
                    </span>
                  </button>
                  {preamblePanelOpen && !writingPreamble ? (
                    <div className="border-t border-outline-variant/10 px-4 py-3 font-body text-sm text-on-surface-variant">
                      {locale === "en" ? "Loading..." : locale === "zh-Hans" ? "加载中…" : "載入提示中…"}
                    </div>
                  ) : null}
                  {preamblePanelOpen && writingPreamble ? (
                    <div className="space-y-2 border-t border-outline-variant/10 px-4 py-3 font-body text-sm text-on-surface-variant">
                      <p>
                        {locale === "en" ? "Previous chapter: " : locale === "zh-Hans" ? "上一章：" : "上一章："}
                        {writingPreamble.plot_progress.previous_chapter.plot_summary ||
                          (locale === "en" ? "No structured summary yet" : locale === "zh-Hans" ? "尚无结构化摘要" : "尚無結構化摘要")}
                      </p>
                      {preambleHasNonLlmSummary ? (
                        <p className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-on-surface">
                          {locale === "en"
                            ? "Detected non-summarizer summary; regenerate summary for the related chapter."
                            : locale === "zh-Hans"
                              ? "检测到非章节整理器摘要，建议在对应章节重新生成摘要。"
                              : "偵測到非章節整理器摘要，建議在對應章節重新產生摘要。"}
                        </p>
                      ) : null}
                      {writingPreamble.plot_progress.previous_chapter.chapter_id != null &&
                      plotSummarySourceNeedsRegenerate(writingPreamble.plot_progress.previous_chapter.plot_summary_source) ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={regenSummaryBusyChapter !== null || busy}
                          onClick={() => void handleRegenerateChapterSummary(writingPreamble.plot_progress.previous_chapter.chapter_id!)}
                        >
                          {regenSummaryBusyChapter === writingPreamble.plot_progress.previous_chapter.chapter_id
                            ? locale === "en"
                              ? "Processing..."
                              : locale === "zh-Hans"
                                ? "处理中…"
                                : "處理中…"
                            : locale === "en"
                              ? "Regenerate Previous Summary"
                              : locale === "zh-Hans"
                                ? "重新生成上一章摘要"
                                : "重新產生上一章摘要"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>

            <WorkflowProgressTrack workflow={workflow} />
            <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-2">
              <div className="inline-flex rounded-md bg-surface-container-lowest/40 p-1" role="tablist" aria-label="撰寫資訊檢視模式">
                <button
                  type="button"
                  id="write-tab-progress"
                  role="tab"
                  aria-controls="write-panel-progress"
                  aria-selected={writePanelTab === "progress"}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    writePanelTab === "progress" ? "bg-primary/20 text-primary" : "text-on-surface-variant"
                  }`}
                  onClick={() => setWritePanelTab("progress")}
                  aria-pressed={writePanelTab === "progress"}
                >
                  {locale === "en" ? "Chapter Progress" : locale === "zh-Hans" ? "章节撰写进度" : "章節撰寫進度"}
                </button>
                <button
                  type="button"
                  id="write-tab-logs"
                  role="tab"
                  aria-controls="write-panel-logs"
                  aria-selected={writePanelTab === "logs"}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    writePanelTab === "logs" ? "bg-secondary/20 text-secondary" : "text-on-surface-variant"
                  }`}
                  onClick={() => setWritePanelTab("logs")}
                  aria-pressed={writePanelTab === "logs"}
                >
                  {locale === "en" ? "Run Logs" : locale === "zh-Hans" ? "撰写过程记录" : "撰寫過程紀錄"}
                </button>
              </div>
            </section>
            {writePanelTab === "progress" ? (
              <div id="write-panel-progress" role="tabpanel" aria-labelledby="write-tab-progress" className="grid grid-cols-1 gap-6">
                <div className="min-w-0">
                  <WorkflowMonitor workflow={workflow} />
                  <div className="mt-4">
                    <HitlPanel
                      workflow={workflow}
                      graph={graph}
                      storyId={storyId || null}
                      busy={busy}
                      workflowError={workflowHitlActive ? error : ""}
                      {...hitlHandlers}
                    />
                  </div>
                </div>
              </div>
            ) : (
              <div id="write-panel-logs" role="tabpanel" aria-labelledby="write-tab-logs" className="min-w-0">
                <AgentOutputView workflow={workflow} />
              </div>
            )}
          </div>
        </div>
      ) : null}
      {view === "export" ? (
        <div className="min-h-[calc(100vh-12rem)] px-4 py-8 md:px-10">
          <ExportCenter
            storyId={storyId}
            chapters={chapters}
            busy={busy}
            onExportProject={exportProjectBundle}
            onExportChapter={async (chapterToExport) => {
              if (!storyId) return;
              setBusy(true);
              setError("");
              try {
                await downloadChapterTxt(storyId, chapterToExport);
                setHasExportedChapter(true);
              } catch (err) {
                reportApiError(err, "errors.downloadChapterFailed");
              } finally {
                setBusy(false);
              }
            }}
            uxMetrics={{
              navCount,
              elapsedMinutes: flowStartedAt ? Math.max(1, Math.round((Date.now() - flowStartedAt) / 60000)) : null,
              stageVisitCount,
            }}
          />
        </div>
      ) : null}
    </AppShell>
  );
}
