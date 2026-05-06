import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
import { AnchorDagSection } from "../features/macro-plan/AnchorDagSection";
import { AnchorNodesGraphView } from "../features/macro-plan/AnchorNodesGraphView";
import {
  computeDagBlockingHighlights,
  findAnchorNodesWithEmptyTitleOrDescription,
  formatAnchorDagValidationIssue,
  validateAnchorDagComprehensive,
  type AnchorDagValidationIssue,
  type DagValidateLocale,
} from "../features/macro-plan/anchorDagValidate";
import { MacroPlanPanel } from "../features/macro-plan/MacroPlanPanel";
import { StoryLibrary } from "../features/story-library/StoryLibrary";
import { StorySetupForm } from "../features/story-setup/StorySetupForm";
import { WorkflowMonitor } from "../features/workflow-monitor/WorkflowMonitor";
import { HitlDevDropdown } from "../features/workflow-monitor/HitlDevDropdown";
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
import { WORKFLOW_MOCKS } from "../dev/workflowMocks";
import { ConfirmModal } from "../components/ConfirmModal";
import { SetupAnchorDagDetailPanel } from "./views/SetupAnchorDagDetailPanel";
import { AppShell, type AppView, type TaskFlowStageId } from "./AppShell";
import {
  buildMacroPutBody,
  idUnderStoryPrefix,
  mergeMacroPlan,
  namespaceMacroPlanIdsForStory,
  parseMacroImportJson,
} from "./macroPlanBundle";
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

/** If any dependency parent is LOCKED, the child must be LOCKED too (forced). RESOLVED rows unchanged. */
function coerceAnchorsLockedWhenParentLocked(
  nodes: NonNullable<MacroCompileData["anchor_nodes"]>,
): NonNullable<MacroCompileData["anchor_nodes"]> {
  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  return nodes.map((n) => {
    if (String(n.status ?? "").toUpperCase() === "RESOLVED") return n;
    const lockedParent = (n.depends_on ?? []).some((pid) => {
      const p = byId.get(String(pid));
      if (!p) return false;
      return String(p.status ?? "LOCKED").toUpperCase() === "LOCKED";
    });
    if (lockedParent && String(n.status ?? "LOCKED").toUpperCase() === "UNLOCKED") {
      return { ...n, status: "LOCKED" as const };
    }
    return n;
  });
}

function navTargetLabel(target: AppView, tfn: (key: string, fallback?: string, params?: Record<string, string | number>) => string): string {
  const keys: Record<AppView, string> = {
    library: "app.navTarget.library",
    setup: "app.navTarget.setup",
    write: "app.navTarget.write",
    review: "app.navTarget.review",
    graph: "app.navTarget.graph",
    export: "app.navTarget.export",
  };
  return tfn(keys[target]);
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

/** Next chapter the pipeline should write: first non-completed in order, else max chapter + 1. */
function computeNextGeneratableChapterId(chapters: ChapterSummary[]): number {
  if (!chapters.length) return 1;
  const sorted = [...chapters].sort((a, b) => a.chapter_id - b.chapter_id);
  for (const c of sorted) {
    if ((c.status ?? "").trim().toLowerCase() !== "completed") {
      return c.chapter_id;
    }
  }
  return Math.max(...sorted.map((c) => c.chapter_id)) + 1;
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

  useEffect(() => {
    if (typeof window === "undefined") return;
    const flag = String(import.meta.env.VITE_ENABLE_DEV_TOOLS ?? "").trim();
    const enabled = flag === "1" || flag.toLowerCase() === "true";
    if (!enabled) return;

    (window as unknown as { __NB_LIST_WORKFLOW_MOCKS?: () => string[] }).__NB_LIST_WORKFLOW_MOCKS =
      () => Object.keys(WORKFLOW_MOCKS);
    (window as unknown as { __NB_SET_WORKFLOW_MOCK?: (name: string) => void }).__NB_SET_WORKFLOW_MOCK =
      (name: string) => {
        const entry = WORKFLOW_MOCKS[String(name)];
        if (!entry) {
          throw new Error(`Unknown mock: ${name}. Use __NB_LIST_WORKFLOW_MOCKS()`);
        }
        setWorkflow(entry.workflow);
        if (entry.graph) setGraph(entry.graph);
      };

    return () => {
      delete (window as unknown as { __NB_LIST_WORKFLOW_MOCKS?: unknown }).__NB_LIST_WORKFLOW_MOCKS;
      delete (window as unknown as { __NB_SET_WORKFLOW_MOCK?: unknown }).__NB_SET_WORKFLOW_MOCK;
    };
  }, []);

  function reportApiError(err: unknown, fallbackKey: string) {
    const raw = err instanceof Error ? err.message : "";
    setError(localizeUserFacingError(raw, t) || t(fallbackKey));
  }
  const [notice, setNotice] = useState<string>("");
  const [chapterAlreadyCompleted, setChapterAlreadyCompleted] = useState(false);
  const [storyConfigSnapshot, setStoryConfigSnapshot] = useState<StoryInput | null>(null);
  const [persistedStoryConfig, setPersistedStoryConfig] = useState<StoryInput | null>(null);
  const [chapterOutline, setChapterOutline] = useState("");
  const [chapterHardRules, setChapterHardRules] = useState("");
  const [aiFreedomLevel, setAiFreedomLevel] = useState<AiFreedomLevel>("balanced");
  const [selectedAnchorIds, setSelectedAnchorIds] = useState<string[]>([]);
  const [manualAnchorSelectionOpen, setManualAnchorSelectionOpen] = useState(false);
  const [writingPreamble, setWritingPreamble] = useState<WritingPreambleResponse | null>(null);
  const [preamblePanelOpen, setPreamblePanelOpen] = useState(false);
  const [writePanelTab, setWritePanelTab] = useState<"progress" | "logs">("progress");
  const [reviewPanelTab, setReviewPanelTab] = useState<"progress" | "logs">("progress");
  const [compileSaveModalOpen, setCompileSaveModalOpen] = useState(false);
  const [toolbarImportModeOpen, setToolbarImportModeOpen] = useState(false);
  const [toolbarImportConfirmOpen, setToolbarImportConfirmOpen] = useState(false);
  const toolbarPendingImportTextRef = useRef<string | null>(null);
  const [toolbarImportPreview, setToolbarImportPreview] = useState<{
    mode: ImportMergeMode;
    storyLine: string;
    macroLine: string;
  } | null>(null);
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
  const [dagLayoutEpoch, setDagLayoutEpoch] = useState(0);
  const [anchorDagFullscreen, setAnchorDagFullscreen] = useState(false);
  const [dagGraphHeight, setDagGraphHeight] = useState(420);
  const [dagDetailPanelOpen, setDagDetailPanelOpen] = useState(true);
  const [dagModal, setDagModal] = useState<
    null | "delete" | "leaveEditConfirm" | "leaveEditBlock" | "leaveEditEmptyFields"
  >(null);
  const [dagNavAwayPending, setDagNavAwayPending] = useState<null | { target: AppView; replace: boolean }>(null);
  const [dagLeaveEditBlockMessage, setDagLeaveEditBlockMessage] = useState("");
  const [dagValidationHighlights, setDagValidationHighlights] = useState<null | {
    nodeIds: string[];
    edges: Array<{ parentId: string; childId: string }>;
  }>(null);
  const [dagInteractionMode, setDagInteractionMode] = useState<"view" | "edit">("view");
  const [dagLinkPick, setDagLinkPick] = useState<null | { mode: "parent"; childId: string } | { mode: "child"; parentId: string }>(
    null,
  );
  const [dagPendingManualPosition, setDagPendingManualPosition] = useState<null | { id: string; x: number; y: number }>(null);
  const [dagDialogMount, setDagDialogMount] = useState<HTMLElement>(() =>
    typeof document !== "undefined" ? document.body : (null as unknown as HTMLElement),
  );
  /** Cleared on story change; next non-empty `anchorTopoSig` bumps `dagLayoutEpoch` once (initial fit / reload). */
  const dagAnchorTopoSnapRef = useRef<string>("");
  const [flowStartedAt, setFlowStartedAt] = useState<number | null>(null);
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);
  const storyIdRef = useRef(storyId);
  const chapterIdRef = useRef(chapterId);
  const chapterHardRulesRef = useRef<HTMLTextAreaElement | null>(null);
  const toolbarImportInputRef = useRef<HTMLInputElement | null>(null);

  function navigateToViewPath(nextView: AppView, replace = false) {
    const targetPath = VIEW_PATH_MAP[nextView];
    if (location.pathname !== targetPath) {
      navigate(targetPath, { replace });
    }
  }

  function requestNavigateToView(nextView: AppView, replace = false) {
    if (dagInteractionMode === "edit" && view === "setup" && nextView !== "setup") {
      setDagNavAwayPending({ target: nextView, replace });
      return;
    }
    navigateToViewPath(nextView, replace);
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
      navigateToViewPath("library");
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

  const nextGeneratableChapterId = useMemo(() => computeNextGeneratableChapterId(chapters), [chapters]);

  useEffect(() => {
    if (!storyId || nextGeneratableChapterId < 1) {
      setChapterAlreadyCompleted(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const row = await fetchChapterIfExists(storyId, nextGeneratableChapterId);
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
  }, [storyId, nextGeneratableChapterId, chapters]);

  useEffect(() => {
    if (!storyId || nextGeneratableChapterId < 1) {
      setWritingPreamble(null);
      return;
    }
    let cancelled = false;
    setWritingPreamble(null);
    void (async () => {
      try {
        const p = await fetchWritingPreamble(storyId, nextGeneratableChapterId);
        if (!cancelled) setWritingPreamble(p);
      } catch {
        if (!cancelled) setWritingPreamble(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [storyId, nextGeneratableChapterId]);

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

  const selectedAnchorLockedParentIds = useMemo(() => {
    if (!macroData || !setupSelectedAnchorNode) return [];
    const byId = new Map((macroData.anchor_nodes ?? []).map((n) => [String(n.id), n]));
    const out: string[] = [];
    for (const pid of setupSelectedAnchorNode.depends_on ?? []) {
      const p = byId.get(String(pid));
      if (p && String(p.status ?? "LOCKED").toUpperCase() === "LOCKED") out.push(String(p.id));
    }
    return out;
  }, [macroData, setupSelectedAnchorNode]);

  const mainStorylineIds = useMemo(() => {
    const m = new Set<string>();
    for (const s of macroData?.storylines ?? []) {
      if (String(s.type).toUpperCase() === "MAIN") m.add(String(s.id));
    }
    return m;
  }, [macroData?.storylines]);

  const selectedIsMainline = useMemo(() => {
    if (!setupSelectedAnchorNode) return false;
    return (setupSelectedAnchorNode.storyline_ids ?? []).some(
      (sid) => mainStorylineIds.has(String(sid)) || String(sid).endsWith("_main"),
    );
  }, [setupSelectedAnchorNode, mainStorylineIds]);

  /** Only RESOLVED anchors block in-panel DAG edits; LOCKED / UNLOCKED remain editable. */
  const selectedResolved = useMemo(
    () => String(setupSelectedAnchorNode?.status ?? "").toUpperCase() === "RESOLVED",
    [setupSelectedAnchorNode],
  );

  const dagFieldsEditable = !selectedResolved && dagInteractionMode === "edit";

  const anchorTopoSig = useMemo(
    () =>
      [...setupAnchorNodes]
        .map((n) => `${String(n.id)}|${(n.depends_on ?? []).join(",")}`)
        .sort()
        .join(";"),
    [setupAnchorNodes],
  );

  useEffect(() => {
    dagAnchorTopoSnapRef.current = "";
    setDagNavAwayPending(null);
    setDagInteractionMode("view");
  }, [storyId]);

  useEffect(() => {
    setDagDetailPanelOpen(true);
  }, [storyId]);

  useEffect(() => {
    if (!dagModal && !dagNavAwayPending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (dagNavAwayPending) {
        setDagNavAwayPending(null);
        return;
      }
      setDagLeaveEditBlockMessage("");
      setDagValidationHighlights(null);
      setDagModal(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dagModal, dagNavAwayPending]);

  useEffect(() => {
    const sync = () => {
      setDagDialogMount(((document.fullscreenElement as HTMLElement) ?? document.body) as HTMLElement);
    };
    sync();
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  useEffect(() => {
    const sig = anchorTopoSig;
    if (!sig) {
      dagAnchorTopoSnapRef.current = "";
      return;
    }
    if (dagAnchorTopoSnapRef.current === sig) return;
    const firstNonEmptyAfterClear = dagAnchorTopoSnapRef.current === "";
    dagAnchorTopoSnapRef.current = sig;
    if (firstNonEmptyAfterClear) setDagLayoutEpoch((x) => x + 1);
  }, [anchorTopoSig]);

  useEffect(() => {
    if (!anchorDagFullscreen) {
      setDagGraphHeight(420);
      return;
    }
    const upd = () => setDagGraphHeight(Math.max(280, window.innerHeight - 132));
    upd();
    window.addEventListener("resize", upd);
    return () => window.removeEventListener("resize", upd);
  }, [anchorDagFullscreen]);

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

  const autoNextAnchorTitles = useMemo(() => {
    const nodes = macroData?.anchor_nodes ?? [];
    const byId = new Map(nodes.map((n) => [String(n.id), String(n.title ?? "").trim() || String(n.id)]));
    return autoNextAnchorIds.map((id) => byId.get(id) ?? id);
  }, [macroData?.anchor_nodes, autoNextAnchorIds]);

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
    if (!macroData) return t("app.setup.summaryNotCompiled");
    const volumes = macroData.volumes ?? [];
    const anchors = (macroData.anchor_nodes ?? []).length > 0 ? macroData.anchor_nodes ?? [] : macroData.anchors ?? [];
    const cast = macroData.cast ?? [];
    const castPart =
      cast.length > 0 ? t("app.setup.summaryCastPart", undefined, { castCount: cast.length }) : "";
    return t("app.setup.summaryLine", undefined, {
      volumes: volumes.length,
      anchors: anchors.length,
      castPart,
    });
  }, [macroData, t]);

  const preambleHasNonLlmSummary = useMemo(() => {
    if (!writingPreamble || nextGeneratableChapterId <= 1) return false;
    const prev = writingPreamble.plot_progress.previous_chapter;
    if (plotSummarySourceNeedsRegenerate(prev.plot_summary_source)) {
      return true;
    }
    return writingPreamble.plot_progress.recent_summaries.some((r) => plotSummarySourceNeedsRegenerate(r.plot_summary_source));
  }, [writingPreamble, nextGeneratableChapterId]);

  async function handleRegenerateChapterSummary(targetChapterId: number) {
    if (!storyId) return;
    setRegenSummaryBusyChapter(targetChapterId);
    setError("");
    try {
      await regenerateChapterSummary(storyId, targetChapterId);
      const p = await fetchWritingPreamble(storyId, nextGeneratableChapterId);
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
      navigateToViewPath("setup");
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
    setHasExportedChapter(false);
    setHasExportedProject(false);
    setNavCount(0);
    setFlowStartedAt(null);
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
    setConfigVersion((v) => v + 1);
    setError("");
    navigateToViewPath("setup");
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
    setHasExportedChapter(false);
    setHasExportedProject(false);
    setNavCount(0);
    setFlowStartedAt(null);
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0, export: 0 });
    setConfigVersion((v) => v + 1);
    setError("");
    requestNavigateToView("library");
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
      navigateToViewPath("setup");
    } catch (err) {
      reportApiError(err, "errors.loadStoryFailed");
    } finally {
      setBusy(false);
    }
  }

  async function runMacroCompileAfterSettingsSaved() {
    if (!storyId) return;
    try {
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

  async function handleMacroCompile() {
    if (!storyId) return;
    setBusy(true);
    setCompileInProgress(true);
    setCompileProgress({ status: "QUEUED", percent: 5, message: "Macro compile queued..." });
    setError("");
    setNotice("");
    if (isStoryConfigDirty(storyConfigSnapshot, persistedStoryConfig) && storyConfigSnapshot) {
      setCompileSaveModalOpen(true);
      return;
    }
    await runMacroCompileAfterSettingsSaved();
  }

  async function handleCompileSaveModalConfirm() {
    if (!storyId || !storyConfigSnapshot) {
      setCompileSaveModalOpen(false);
      setCompileInProgress(false);
      setCompileProgress(null);
      setBusy(false);
      return;
    }
    setCompileSaveModalOpen(false);
    setError("");
    try {
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
    } catch (err) {
      reportApiError(err, "errors.saveSettingsFailed");
      setCompileInProgress(false);
      setCompileProgress(null);
      setBusy(false);
      return;
    }
    await runMacroCompileAfterSettingsSaved();
  }

  function handleCompileSaveModalCancel() {
    setCompileSaveModalOpen(false);
    setNotice(t("setup.compileCancelledNotice"));
    setCompileInProgress(false);
    setCompileProgress(null);
    setBusy(false);
  }

  async function handleSaveStorySettings(payload: StoryInput) {
    if (!storyId) return;
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
        navigateToViewPath("review");
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
        const resolvedChapterId =
          typeof wf.run.chapter_id === "number" && Number.isFinite(wf.run.chapter_id)
            ? wf.run.chapter_id
            : chapterIdRef.current;
        try {
          setSelectedChapter(await fetchChapter(sid, resolvedChapterId));
        } catch {
          /* missing */
        }
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
      setError(t("app.write.manualAnchorRequired"));
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
      const initial = await runChapter(storyId, nextGeneratableChapterId, {
        ...runOptions,
      });
      setWorkflow(initial);
      try {
        const detail = await fetchStoryDetail(storyId);
        const nextConfig = storyDetailToInput(detail, storyConfigSnapshot?.output_language ?? "zh-Hant");
        setStoryConfigSnapshot(nextConfig);
        setPersistedStoryConfig(nextConfig);
      } catch {
        /* optional refresh */
      }
      setConfigVersion((v) => v + 1);
      const runId = initial.run.run_id;
      navigateToViewPath("write");
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

  function buildImportBundlePreviewLines(jsonText: string): { storyLine: string; macroLine: string } {
    const { story: parsedStory, macro_plan: parsedMacroRaw } = parseProjectBundleJson(jsonText);
    const parsedMacro = parsedMacroRaw ? namespaceMacroPlanIdsForStory(parsedMacroRaw, storyId) : undefined;
    const storyLine = parsedStory
      ? t("app.import.storyWithTitle", undefined, { title: parsedStory.title })
      : t("app.import.storyEmpty");
    const nodeCount = (parsedMacro?.anchor_nodes ?? []).length;
    const slCount = (parsedMacro?.storylines ?? []).length;
    const macroLine = parsedMacro
      ? t("app.import.macroWithCounts", undefined, {
          volumes: parsedMacro.volumes.length,
          nodes: nodeCount,
          storylines: slCount,
          cast: parsedMacro.cast.length,
        })
      : t("app.import.macroEmpty");
    return { storyLine, macroLine };
  }

  async function applyImportProjectBundle(jsonText: string, mode: ImportMergeMode) {
    if (!storyId) return;
    const { story: parsedStory, macro_plan: parsedMacroRaw } = parseProjectBundleJson(jsonText);
    const parsedMacro = parsedMacroRaw ? namespaceMacroPlanIdsForStory(parsedMacroRaw, storyId) : undefined;
    const modeLabel = mode === "replace" ? t("app.confirm.importReplace") : t("app.confirm.importMerge");

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
      setNotice(t("app.import.doneNotice", undefined, { modeLabel }));
    }
  }

  function openToolbarImportConfirm(mode: ImportMergeMode) {
    const text = toolbarPendingImportTextRef.current;
    if (!text) return;
    try {
      const { storyLine, macroLine } = buildImportBundlePreviewLines(text);
      setToolbarImportPreview({ mode, storyLine, macroLine });
      setToolbarImportModeOpen(false);
      setToolbarImportConfirmOpen(true);
    } catch (err) {
      reportApiError(err, "errors.importJsonFailed");
      toolbarPendingImportTextRef.current = null;
      setToolbarImportModeOpen(false);
    }
  }

  function cancelToolbarImportFlow() {
    toolbarPendingImportTextRef.current = null;
    setToolbarImportModeOpen(false);
    setToolbarImportConfirmOpen(false);
    setToolbarImportPreview(null);
  }

  async function handleToolbarImportProjectBundle(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !storyId) return;
    setError("");
    try {
      const text = await file.text();
      toolbarPendingImportTextRef.current = text;
      setToolbarImportModeOpen(true);
    } catch (err) {
      reportApiError(err, "errors.importJsonFailed");
    }
  }

  async function handleToolbarImportConfirmed() {
    const text = toolbarPendingImportTextRef.current;
    const prev = toolbarImportPreview;
    if (!text || !prev) return;
    setToolbarImportConfirmOpen(false);
    setToolbarImportPreview(null);
    toolbarPendingImportTextRef.current = null;
    setBusy(true);
    setError("");
    try {
      await applyImportProjectBundle(text, prev.mode);
    } catch (err) {
      reportApiError(err, "errors.importJsonFailed");
    } finally {
      setBusy(false);
    }
  }

  function patchSetupAnchorNode(patch: Partial<NonNullable<MacroCompileData["anchor_nodes"]>[number]>) {
    if (!macroData || !setupSelectedAnchorNode) return;
    if (dagInteractionMode !== "edit") return;
    if (String(setupSelectedAnchorNode.status ?? "").toUpperCase() === "RESOLVED") return;
    const nextNodes = (macroData.anchor_nodes ?? []).map((n) =>
      String(n.id) === String(setupSelectedAnchorNode.id) ? { ...n, ...patch } : n,
    );
    setMacroData({
      ...macroData,
      anchor_nodes: coerceAnchorsLockedWhenParentLocked(nextNodes),
    });
  }

  function userEditStorylineId(): string | null {
    if (!storyId) return null;
    return idUnderStoryPrefix(storyId, "user_edit");
  }

  function requestDeleteSetupAnchorNode() {
    if (!macroData || !setupSelectedAnchorNode) return;
    if (String(setupSelectedAnchorNode.status ?? "").toUpperCase() === "RESOLVED") return;
    if (selectedIsMainline) return;
    setDagModal("delete");
  }

  function executeDeleteSetupAnchorNode() {
    setDagModal(null);
    if (!macroData || !setupSelectedAnchorNode) return;
    if (String(setupSelectedAnchorNode.status ?? "").toUpperCase() === "RESOLVED") return;
    if (selectedIsMainline) return;
    deleteAnchorNodeById(String(setupSelectedAnchorNode.id));
  }

  function addDependencyEdge(parentId: string, childId: string) {
    if (!macroData || parentId === childId) return;
    const next = (macroData.anchor_nodes ?? []).map((n) => {
      if (String(n.id) !== childId) return n;
      const deps = new Set([...(n.depends_on ?? [])]);
      deps.add(parentId);
      return { ...n, depends_on: [...deps] };
    });
    setMacroData({
      ...macroData,
      anchor_nodes: coerceAnchorsLockedWhenParentLocked(next),
    });
  }

  function removeDependencyEdge(parentId: string, childId: string) {
    if (!macroData) return;
    const next = (macroData.anchor_nodes ?? []).map((n) => {
      if (String(n.id) !== String(childId)) return n;
      return {
        ...n,
        depends_on: [...(n.depends_on ?? []).filter((d) => String(d) !== String(parentId))],
      };
    });
    setMacroData({
      ...macroData,
      anchor_nodes: coerceAnchorsLockedWhenParentLocked(next),
    });
  }

  function deleteAnchorNodeById(nodeId: string) {
    if (!macroData) return;
    const idRemoved = String(nodeId);
    const next = coerceAnchorsLockedWhenParentLocked(
      (macroData.anchor_nodes ?? [])
        .filter((n) => String(n.id) !== idRemoved)
        .map((n) => ({
          ...n,
          depends_on: [...(n.depends_on ?? []).filter((d) => String(d) !== idRemoved)],
        })),
    );
    setMacroData({ ...macroData, anchor_nodes: next });
    setSetupSelectedAnchorNodeId((prev) => {
      if (String(prev) !== idRemoved) return prev;
      return next[0]?.id ? String(next[0].id) : null;
    });
  }

  function createAnchorNodeAtGraphPosition(canvasX: number, canvasY: number) {
    if (!macroData || !storyId || dagInteractionMode !== "edit") return;
    const ueId = userEditStorylineId();
    if (!ueId) return;
    let storylines = [...(macroData.storylines ?? [])];
    if (!storylines.some((s) => s.id === ueId)) {
      storylines.push({
        id: ueId,
        type: "USER_EDIT",
        title: t("app.dag.userEditStorylineTitle"),
        overall_goal: "",
        involved_entities: [],
      });
    }
    const vol =
      String(setupSelectedAnchorNode?.volume_id ?? "").trim() ||
      String(macroData.volumes?.[0]?.volume_id ?? "").trim();
    if (!vol) return;
    const newId = `${storyId}_ua_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    const newNode: NonNullable<MacroCompileData["anchor_nodes"]>[number] = {
      id: newId,
      storyline_ids: [ueId],
      volume_id: vol,
      node_kind: "NORMAL",
      title: t("app.dag.newNodeTitle"),
      description: "",
      depends_on: [],
      status: "LOCKED",
      estimated_chapter: null,
    };
    setMacroData({
      ...macroData,
      storylines,
      anchor_nodes: coerceAnchorsLockedWhenParentLocked([...(macroData.anchor_nodes ?? []), newNode]),
    });
    setSetupSelectedAnchorNodeId(newId);
    setDagPendingManualPosition({ id: newId, x: canvasX, y: canvasY });
  }

  function resolveDagLinkPick(pickedNodeId: string) {
    if (pickedNodeId === "__cancel__") {
      setDagLinkPick(null);
      return;
    }
    if (!dagLinkPick) return;
    if (dagLinkPick.mode === "parent") {
      addDependencyEdge(pickedNodeId, dagLinkPick.childId);
    } else {
      addDependencyEdge(dagLinkPick.parentId, pickedNodeId);
    }
    setDagLinkPick(null);
  }

  function requestDeleteSetupAnchorNodeFromGraph(nodeId: string) {
    if (!macroData) return;
    const n = macroData.anchor_nodes?.find((x) => String(x.id) === String(nodeId));
    if (!n) return;
    if (String(n.status ?? "").toUpperCase() === "RESOLVED") {
      setError(t("app.dag.errorResolvedNoDelete"));
      return;
    }
    const isMl = (n.storyline_ids ?? []).some(
      (sid) => mainStorylineIds.has(String(sid)) || String(sid).endsWith("_main"),
    );
    if (isMl) {
      setError(t("app.dag.errorMainlineNoDelete"));
      return;
    }
    setSetupSelectedAnchorNodeId(String(nodeId));
    setDagModal("delete");
  }

  function applyMacroPutResult(updated: Awaited<ReturnType<typeof putMacroPlan>>) {
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
  }

  async function persistLeaveEditAfterValidation(warnings: AnchorDagValidationIssue[]) {
    if (!storyId || !macroData) return;
    setBusy(true);
    setError("");
    try {
      const payload = buildMacroPutBody(macroData);
      const updated = await putMacroPlan(storyId, payload);
      applyMacroPutResult(updated);
      const base = t("app.dag.savedLeavingEdit");
      const loc = locale as DagValidateLocale;
      const noticeText =
        warnings.length > 0 ? [base, ...warnings.map((w) => formatAnchorDagValidationIssue(w, loc))].join("\n") : base;
      setNotice(noticeText);
      setDagInteractionMode("view");
      setDagModal(null);
      setDagLeaveEditBlockMessage("");
      setDagValidationHighlights(null);
    } catch (err) {
      reportApiError(err, "errors.saveDagFailed");
    } finally {
      setBusy(false);
    }
  }

  /** Runs after user confirms "save and exit" — empty fields / DAG blocking → dialogs + graph highlights; else PUT. */
  function confirmLeaveEditModeFromDialog() {
    setDagLinkPick(null);
    if (!storyId || !macroData) {
      setDagInteractionMode("view");
      setDagModal(null);
      setDagValidationHighlights(null);
      return;
    }
    const anchors = macroData.anchor_nodes ?? [];
    const emptyIds = findAnchorNodesWithEmptyTitleOrDescription(
      anchors.map((n) => ({
        id: String(n.id),
        title: String(n.title ?? ""),
        description: String(n.description ?? ""),
      })),
    );
    if (emptyIds.length > 0) {
      const detail = emptyIds.map((id) => `· ${id}`).join("\n");
      setDagLeaveEditBlockMessage(t("app.dag.emptyAnchorsDetail", undefined, { detail }));
      setDagValidationHighlights({ nodeIds: emptyIds, edges: [] });
      setDagModal("leaveEditEmptyFields");
      return;
    }
    const nodes = anchors.map((n) => ({
      id: String(n.id),
      storyline_ids: [...(n.storyline_ids ?? [])],
      node_kind: n.node_kind,
      depends_on: [...(n.depends_on ?? [])],
    }));
    const storylinesLite = (macroData.storylines ?? []).map((s) => ({
      id: String(s.id),
      type: String(s.type),
    }));
    const r = validateAnchorDagComprehensive(nodes, storylinesLite);
    if (r.blocking) {
      setDagValidationHighlights(computeDagBlockingHighlights(nodes, storylinesLite, r.blocking));
      setDagLeaveEditBlockMessage(formatAnchorDagValidationIssue(r.blocking, locale as DagValidateLocale));
      setDagModal("leaveEditBlock");
      return;
    }
    setDagValidationHighlights(null);
    void persistLeaveEditAfterValidation(r.warnings);
  }

  function handleDagInteractionModeChange(next: "view" | "edit") {
    if (next === "edit") {
      setDagInteractionMode("edit");
      return;
    }
    if (!storyId || !macroData) {
      setDagInteractionMode("view");
      return;
    }
    setDagLeaveEditBlockMessage("");
    setDagValidationHighlights(null);
    setDagModal("leaveEditConfirm");
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
    if (!workflow) return t("workflow.mini.notRun");
    const status = String(workflow.state.workflow_status ?? workflow.run.status ?? "");
    if (status === "WAITING_HITL") return t("workflow.mini.waitingHitl");
    if (status === "COMPLETED") return t("workflow.mini.completed");
    if (status === "FAILED") return t("workflow.mini.failed");
    return t("workflow.mini.running");
  }, [workflow, t]);
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
      setNotice(t("app.nav.selectStoryFirst"));
      requestNavigateToView("library");
      return;
    }
    if (nextView === "write" && !hasMacroCompiled) {
      setNotice(t("app.nav.finishMacroFirst"));
      requestNavigateToView("setup");
      return;
    }
    if ((nextView === "review" || nextView === "export") && !hasChapterRun) {
      setNotice(t("app.nav.needChapterRun"));
      requestNavigateToView("write");
      return;
    }
    if (dagInteractionMode === "edit" && view === "setup" && nextView !== "setup") {
      setDagNavAwayPending({ target: nextView, replace: false });
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
    navigateToViewPath(nextView);
  }

  function confirmDagNavAwayAndNavigate() {
    const pending = dagNavAwayPending;
    if (!pending) return;
    setDagNavAwayPending(null);
    setDagInteractionMode("view");
    setDagLinkPick(null);
    setDagValidationHighlights(null);
    setDagModal(null);
    const target = pending.target;
    const markStageVisit = (stage: TaskFlowStageId) => {
      setStageVisitCount((prev) => ({ ...prev, [stage]: prev[stage] + 1 }));
      setNavCount((prev) => prev + 1);
    };
    if (target === "setup") {
      markStageVisit(hasMacroCompiled ? "planStructure" : "projectSetup");
    } else if (target === "write") {
      markStageVisit("writeChapter");
    } else if (target === "review" || target === "graph") {
      markStageVisit("reviewFix");
    } else if (target === "export") {
      markStageVisit("export");
    }
    navigateToViewPath(target, pending.replace);
  }

  const anchorDagFsOverlay =
    view === "setup" && anchorDagFullscreen && (error || failureNotice || notice) ? (
      <div className="flex flex-col gap-2">
        {error ? (
          <div className="rounded-xl border border-error/40 bg-error/10 px-3 py-2 font-label text-xs text-error shadow-lg backdrop-blur-sm">
            {error}
          </div>
        ) : null}
        {failureNotice ? (
          <div className="rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 font-label text-xs text-on-surface shadow-lg backdrop-blur-sm">
            {failureNotice}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-xl border border-secondary/35 bg-secondary/10 px-3 py-2 font-label text-xs text-secondary shadow-lg backdrop-blur-sm">
            {notice}
          </div>
        ) : null}
      </div>
    ) : null;

  const hideTopAlertsForAnchorFs = view === "setup" && anchorDagFullscreen;

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
        {!hideTopAlertsForAnchorFs && error ? (
          <div className="rounded-xl border border-error/40 bg-error/10 px-4 py-3 font-label text-sm text-error">{error}</div>
        ) : null}
        {!hideTopAlertsForAnchorFs && !error && failureNotice ? (
          <div className="mt-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 font-label text-sm text-on-surface">
            {failureNotice}
          </div>
        ) : null}
        {!hideTopAlertsForAnchorFs && !error && notice ? (
          <div className="rounded-xl border border-secondary/35 bg-secondary/10 px-4 py-3 font-label text-sm text-secondary">{notice}</div>
        ) : null}
      </div>
      {!error && alignmentRulesPromptActive && view !== "setup" && view !== "library" ? (
        <div className="mx-4 mt-4 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 font-label text-sm text-on-surface">
          {t("app.alignmentRules.banner")}
          <button type="button" className="btn-secondary ml-3" onClick={() => requestNavigateToView("setup")}>
            {t("app.alignmentRules.goSetup")}
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
              {t("app.setup.kicker")}
            </span>
            <h1 className="mb-3 font-headline text-4xl font-black tracking-tighter text-on-surface">
              {t("app.setup.title")}
            </h1>
            <p className="max-w-2xl font-body text-lg italic text-on-surface-variant">{t("app.setup.subtitle")}</p>
          </div>

          {storyId ? (
            <div className="mb-4 max-w-7xl rounded-xl border border-tertiary/25 bg-tertiary/5 px-4 py-3 font-body text-sm leading-relaxed text-on-surface">
              <span className="font-headline font-bold text-tertiary">{t("app.setup.rerunCompileTitle")}</span>
              {t("app.setup.rerunCompileBody")}
            </div>
          ) : null}

          <div className="mb-8 max-w-7xl rounded-xl border border-outline-variant/10 bg-surface-container-low/80 p-4 font-label shadow-glow">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-primary-gradient flex items-center gap-2 text-sm"
                onClick={handleMacroCompile}
                disabled={!storyId || busy || workflowConflictLocked}
              >
                <span className="material-symbols-outlined text-lg">auto_awesome</span>
                {t("app.setup.compileCta")}
              </button>
              <button type="button" className="btn-secondary" onClick={storyId ? exportProjectBundle : undefined} disabled={!storyId || busy}>
                {t("setup.exportProjectJson")}
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => toolbarImportInputRef.current?.click()}
                disabled={!storyId || busy}
              >
                {t("setup.importProjectJson")}
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
            <span className="text-secondary">{t("app.setup.storyIdLabel")}</span>{" "}
            {storyId || t("app.setup.storyIdMissing")} · {storySummary}
          </div>

          <div className="grid max-w-7xl grid-cols-1 items-start gap-8 lg:grid-cols-12">
            <div className="lg:col-span-5">
              <StorySetupForm
                resetKey={`${storyId || "new"}-${configVersion}`}
                initialValues={storyId ? storyConfigSnapshot : null}
                onValuesChange={storyId ? setStoryConfigSnapshot : undefined}
                onSubmit={handleCreateStory}
                onSaveSettings={storyId ? handleSaveStorySettings : undefined}
                showCreateButton={!storyId}
                onExportProjectBundle={storyId ? exportProjectBundle : undefined}
                onImportProjectBundle={storyId ? applyImportProjectBundle : undefined}
                getImportBundlePreview={storyId ? buildImportBundlePreviewLines : undefined}
                onBusy={setBusy}
                onError={setError}
                disabled={busy}
              />
            </div>
            <div className="lg:col-span-7">
              <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low/50 p-3">
                <div className="mb-3 px-1">
                  <h3 className="font-label text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                    {t("app.setup.worldEditorTitle")}
                  </h3>
                </div>
                <MacroPlanPanel
                  macroData={macroData}
                  storyId={storyId || null}
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
                  {t("app.setup.anchorDagTitle")}
                </h3>
              </div>
              {setupAnchorNodes.length > 0 ? (
                <AnchorDagSection
                  locale={locale}
                  fsOverlay={anchorDagFsOverlay}
                  detailOpen={dagDetailPanelOpen}
                  onDetailOpenChange={setDagDetailPanelOpen}
                  onFullscreenChange={setAnchorDagFullscreen}
                  toolbarExtras={
                    <span className="text-[10px] text-on-surface-variant">
                      {t("app.setup.anchorDagHint")}
                    </span>
                  }
                  graph={(dagFs) => (
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
                      height={dagGraphHeight}
                      layoutEpoch={dagLayoutEpoch}
                      detailPanelOpen={dagDetailPanelOpen}
                      onToggleDetailPanel={() => setDagDetailPanelOpen((o) => !o)}
                      fullscreen={dagFs}
                      interactionMode={dagInteractionMode}
                      onInteractionModeChange={handleDagInteractionModeChange}
                      linkPick={dagLinkPick}
                      onResolveLinkPick={resolveDagLinkPick}
                      onCanvasCreateNode={({ x, y }) => createAnchorNodeAtGraphPosition(x, y)}
                      onGraphDeleteNode={requestDeleteSetupAnchorNodeFromGraph}
                      onGraphStartLinkParent={(childId) => setDagLinkPick({ mode: "parent", childId })}
                      onGraphStartLinkChild={(parentId) => setDagLinkPick({ mode: "child", parentId })}
                      onRemoveDependency={removeDependencyEdge}
                      pendingManualPosition={dagPendingManualPosition}
                      onConsumePendingManualPosition={() => setDagPendingManualPosition(null)}
                      validationHighlights={dagValidationHighlights}
                    />
                  )}
                  detail={
                    <SetupAnchorDagDetailPanel
                      storyId={storyId.trim() ? storyId : null}
                      setupSelectedAnchorNode={setupSelectedAnchorNode}
                      selectedResolved={selectedResolved}
                      topologyLocked={Boolean(macroData?.topology_locked)}
                      dagFieldsEditable={dagFieldsEditable}
                      busy={busy}
                      selectedAnchorLockedParentIds={selectedAnchorLockedParentIds}
                      onPatchAnchor={patchSetupAnchorNode}
                    />
                  }
                />
              ) : (
                <div className="rounded-lg border border-outline-variant/20 bg-surface-container-low p-4 text-sm text-on-surface-variant">
                  {t("app.dagDetail.noMapYet")}
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
                  setNotice(t("app.chapter.notOnDisk"));
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
              <div className="flex min-w-0 flex-col gap-4 p-4">
                <WorkflowProgressTrack workflow={workflow} compact />
                <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-2">
                  <div
                    className="inline-flex rounded-md bg-surface-container-lowest/40 p-1"
                    role="tablist"
                    aria-label={t("workflow.sidePanel.ariaReview")}
                  >
                    <button
                      type="button"
                      id="review-tab-progress"
                      role="tab"
                      aria-controls="review-panel-progress"
                      aria-selected={reviewPanelTab === "progress"}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                        reviewPanelTab === "progress" ? "bg-primary/20 text-primary" : "text-on-surface-variant"
                      }`}
                      onClick={() => setReviewPanelTab("progress")}
                      aria-pressed={reviewPanelTab === "progress"}
                    >
                      {t("workflow.sidePanel.tabProgress")}
                    </button>
                    <button
                      type="button"
                      id="review-tab-logs"
                      role="tab"
                      aria-controls="review-panel-logs"
                      aria-selected={reviewPanelTab === "logs"}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                        reviewPanelTab === "logs" ? "bg-secondary/20 text-secondary" : "text-on-surface-variant"
                      }`}
                      onClick={() => setReviewPanelTab("logs")}
                      aria-pressed={reviewPanelTab === "logs"}
                    >
                      {t("workflow.sidePanel.tabLogs")}
                    </button>
                  </div>
                </section>
                {reviewPanelTab === "progress" ? (
                  <div
                    id="review-panel-progress"
                    role="tabpanel"
                    aria-labelledby="review-tab-progress"
                    className="flex min-w-0 flex-col gap-4"
                  >
                    <WorkflowMonitor workflow={workflow} variant="compact" />
                    <HitlDevDropdown workflow={workflow} setWorkflow={setWorkflow} variant="compact" />
                    <HitlPanel
                      workflow={workflow}
                      graph={graph}
                      storyId={storyId || null}
                      variant="compact"
                      busy={busy}
                      workflowError={workflowHitlActive ? error : ""}
                      {...hitlHandlers}
                    />
                  </div>
                ) : (
                  <div id="review-panel-logs" role="tabpanel" aria-labelledby="review-tab-logs" className="min-w-0">
                    <AgentOutputView workflow={workflow} variant="compact" />
                  </div>
                )}
              </div>
            }
          />
        </div>
      ) : null}

      {view === "graph" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background p-4 md:p-8">
          <div className="mb-4 flex items-center justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={() => requestNavigateToView("setup")}>
              {t("app.graph.backSetup")}
            </button>
            <span className="rounded-full border border-secondary/20 bg-secondary/10 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-secondary">
              {t("app.graph.readOnly")}
            </span>
          </div>
          <GraphView graph={graph} protagonistCharacterId={macroData?.protagonist_character_id} />
        </div>
      ) : null}

      {view === "write" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
            <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-4 shadow-glow">
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(180px,240px)_minmax(220px,280px)_auto] lg:items-end">
                <div className="flex flex-col gap-1.5">
                  <span className="font-label text-[10px] uppercase tracking-wider text-outline">
                    {t("app.write.chapterToWrite")}
                  </span>
                  <div
                    className="flex h-10 items-center rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 font-semibold text-on-surface"
                    title={t("app.write.chapterToWriteHint")}
                  >
                    {t("app.write.chapterN", undefined, { n: nextGeneratableChapterId })}
                  </div>
                </div>
                <label className="flex min-w-0 flex-col gap-1.5 font-body text-sm text-on-surface">
                  <span className="font-label text-[10px] uppercase tracking-wider text-outline">
                    {t("app.write.aiFreedom")}
                  </span>
                  <select
                    value={aiFreedomLevel}
                    onChange={(e) => setAiFreedomLevel(e.target.value as AiFreedomLevel)}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="auteur-input h-10 w-full text-sm"
                  >
                    <option value="strict">{t("app.write.aiFreedom.strict")}</option>
                    <option value="balanced">{t("app.write.aiFreedom.balanced")}</option>
                    <option value="wild">{t("app.write.aiFreedom.wild")}</option>
                  </select>
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    className="btn-primary-gradient h-10"
                    onClick={handleRunChapter}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                  >
                    {t("app.write.runChapter")}
                  </button>
                </div>
              </div>
              {chapterAlreadyCompleted ? (
                <div className="mt-3">
                  <span className="rounded-full border border-tertiary/30 bg-tertiary/10 px-2 py-1 text-xs text-tertiary">
                    {t("app.write.chapterCompleteBadge", undefined, { n: nextGeneratableChapterId })}
                  </span>
                </div>
              ) : null}
              {storyId ? (
                <div className="mt-3 overflow-hidden rounded-xl border border-outline-variant/15 bg-surface-container/90">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-surface-container-highest/50"
                    onClick={() => setPreamblePanelOpen((o) => !o)}
                  >
                    <span className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="font-label text-[11px] font-bold uppercase tracking-wider text-secondary">
                        {t("app.write.preambleToggle")}
                      </span>
                      <span className="truncate font-body text-sm text-on-surface-variant">
                        {t("app.write.preambleSummary", undefined, { n: Math.max(0, nextGeneratableChapterId - 1) })}
                      </span>
                    </span>
                    <span className="material-symbols-outlined shrink-0 text-on-surface-variant">
                      {preamblePanelOpen ? "expand_less" : "expand_more"}
                    </span>
                  </button>
                  {preamblePanelOpen && !writingPreamble ? (
                    <div className="border-t border-outline-variant/10 px-4 py-3 font-body text-sm text-on-surface-variant">
                      {t("app.write.preambleLoading")}
                    </div>
                  ) : null}
                  {preamblePanelOpen && writingPreamble ? (
                    <div className="space-y-2 border-t border-outline-variant/10 px-4 py-3 font-body text-sm text-on-surface-variant">
                      <p>
                        {t("app.write.preamblePrevChapter")}
                        {writingPreamble.plot_progress.previous_chapter.plot_summary || t("app.write.preambleNoSummary")}
                      </p>
                      {preambleHasNonLlmSummary ? (
                        <p className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-on-surface">
                          {t("app.write.preambleNonLlmWarn")}
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
                            ? t("app.write.regenProcessing")
                            : t("app.write.regenSummary")}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="mt-3 rounded-lg border border-outline-variant/15 bg-surface-container-high/30 p-3">
                <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">{t("app.write.milestonesTitle")}</p>
                <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low px-3 py-2">
                  <p className="text-xs text-on-surface-variant">{t("app.write.milestonesHint")}</p>
                  <button
                    type="button"
                    className="mt-2 rounded-md border border-secondary/35 px-3 py-1.5 text-xs font-semibold text-secondary"
                    onClick={() => setManualAnchorSelectionOpen((v) => !v)}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                  >
                    {manualAnchorSelectionOpen ? t("app.write.manualHide") : t("app.write.manualShow")}
                  </button>
                </div>
                {manualAnchorSelectionOpen ? (
                  chapterAnchorCandidates.length === 0 ? (
                    <p className="mt-2 text-xs text-on-surface-variant">{t("app.write.noMilestonesAvailable")}</p>
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
                            <span>{t("app.write.anchorPick")}</span>
                          </label>
                        </label>
                      ))}
                    </div>
                  )
                ) : null}
                {manualAnchorSelectionOpen ? (
                  <p className="mt-2 text-[11px] text-on-surface-variant">
                    {autoNextAnchorTitles.length > 0
                      ? t("app.write.anchorAutoHint", undefined, {
                          titles: autoNextAnchorTitles.join(t("app.write.listSep")),
                        })
                      : t("app.write.anchorAutoThinking")}
                  </p>
                ) : null}
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <div>
                  <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
                    {t("app.write.chapterDirection")}
                  </p>
                  <textarea
                    value={chapterOutline}
                    onChange={(e) => setChapterOutline(e.target.value)}
                    maxLength={2000}
                    rows={4}
                    placeholder={t("app.write.outlinePlaceholder")}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
                  />
                  {chapterOutline.trim().length > 0 && chapterOutline.trim().length < OUTLINE_FULL_BINDING_MIN_CHARS ? (
                    <p className="mt-2 font-body text-xs text-secondary">
                      {t("app.write.outlineShortHint", undefined, { min: OUTLINE_FULL_BINDING_MIN_CHARS })}
                    </p>
                  ) : null}
                </div>
                <div>
                  <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
                    {t("app.write.hardRules")}
                  </p>
                  <textarea
                    value={chapterHardRules}
                    onChange={(e) => setChapterHardRules(e.target.value)}
                    ref={chapterHardRulesRef}
                    maxLength={8000}
                    rows={4}
                    placeholder={t("app.write.hardRulesPlaceholder")}
                    disabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                    className="w-full resize-y rounded-lg border border-outline-variant/20 bg-surface-container-highest px-3 py-2 font-body text-sm text-on-surface placeholder:text-on-surface-variant/50"
                  />
                </div>
              </div>
            </section>

            <WorkflowProgressTrack workflow={workflow} />
            <section className="rounded-xl border border-outline-variant/15 bg-surface-container-low/70 p-2">
              <div
                className="inline-flex rounded-md bg-surface-container-lowest/40 p-1"
                role="tablist"
                aria-label={t("workflow.sidePanel.ariaWrite")}
              >
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
                  {t("workflow.sidePanel.tabProgress")}
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
                  {t("workflow.sidePanel.tabLogs")}
                </button>
              </div>
            </section>
            {writePanelTab === "progress" ? (
              <div id="write-panel-progress" role="tabpanel" aria-labelledby="write-tab-progress" className="grid grid-cols-1 gap-6">
                <div className="min-w-0">
                  <WorkflowMonitor workflow={workflow} />
                  <HitlDevDropdown workflow={workflow} setWorkflow={setWorkflow} />
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
      {dagModal === "delete" && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-delete-dialog-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) setDagModal(null);
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-red-400/25 bg-[#120808] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2 id="dag-delete-dialog-title" className="font-label text-sm font-bold uppercase tracking-wider text-red-200">
                  {t("app.dag.deleteTitle")}
                </h2>
                <p className="mt-3 font-body text-sm leading-relaxed text-red-100/85">{t("app.dag.deleteBody")}</p>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-white/5"
                    onClick={() => setDagModal(null)}
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-red-400/50 bg-red-950/60 px-4 py-2 text-xs font-semibold text-red-100 hover:bg-red-900/50"
                    onClick={executeDeleteSetupAnchorNode}
                  >
                    {t("app.dag.delete")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
      {dagModal === "leaveEditConfirm" && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-leave-edit-confirm-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) {
                  setDagModal(null);
                  setDagValidationHighlights(null);
                }
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-outline-variant/30 bg-surface-container-high p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2
                  id="dag-leave-edit-confirm-title"
                  className="font-label text-sm font-bold uppercase tracking-wider text-on-surface"
                >
                  {t("app.dag.leaveTitle")}
                </h2>
                <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("app.dag.leaveBody")}</p>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-low"
                    onClick={() => {
                      setDagModal(null);
                      setDagValidationHighlights(null);
                    }}
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-secondary/50 bg-secondary/15 px-4 py-2 text-xs font-semibold text-secondary hover:bg-secondary/25"
                    onClick={confirmLeaveEditModeFromDialog}
                  >
                    {t("common.confirm")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
      {dagModal === "leaveEditBlock" && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-leave-edit-block-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) {
                  setDagModal(null);
                  setDagLeaveEditBlockMessage("");
                  setDagValidationHighlights(null);
                }
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-amber-400/30 bg-[#120a06] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2
                  id="dag-leave-edit-block-title"
                  className="font-label text-sm font-bold uppercase tracking-wider text-amber-100"
                >
                  {t("app.dag.cannotSaveTitle")}
                </h2>
                <p className="mt-3 whitespace-pre-wrap font-body text-sm leading-relaxed text-amber-50/95">
                  {dagLeaveEditBlockMessage}
                </p>
                <p className="mt-3 font-body text-[11px] leading-relaxed text-amber-200/75">{t("app.dag.cannotSaveFooter")}</p>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-amber-400/40 bg-amber-950/50 px-4 py-2 text-xs font-semibold text-amber-50 hover:bg-amber-900/40"
                    onClick={() => {
                      setDagModal(null);
                      setDagLeaveEditBlockMessage("");
                      setDagValidationHighlights(null);
                    }}
                  >
                    {t("common.ok")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
      {dagModal === "leaveEditEmptyFields" && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-leave-edit-empty-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) {
                  setDagModal(null);
                  setDagLeaveEditBlockMessage("");
                  setDagValidationHighlights(null);
                }
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-red-400/30 bg-[#120808] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2
                  id="dag-leave-edit-empty-title"
                  className="font-label text-sm font-bold uppercase tracking-wider text-red-200"
                >
                  {t("app.dag.emptyFieldsTitle")}
                </h2>
                <p className="mt-3 whitespace-pre-wrap font-body text-sm leading-relaxed text-red-100/90">
                  {dagLeaveEditBlockMessage}
                </p>
                <p className="mt-3 font-body text-[11px] leading-relaxed text-red-200/75">{t("app.dag.emptyFieldsFooter")}</p>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-red-400/40 bg-red-950/50 px-4 py-2 text-xs font-semibold text-red-50 hover:bg-red-900/40"
                    onClick={() => {
                      setDagModal(null);
                      setDagLeaveEditBlockMessage("");
                      setDagValidationHighlights(null);
                    }}
                  >
                    {t("common.ok")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
      {dagNavAwayPending && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-nav-away-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) setDagNavAwayPending(null);
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-outline-variant/30 bg-surface-container-high p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2
                  id="dag-nav-away-title"
                  className="font-label text-sm font-bold uppercase tracking-wider text-on-surface"
                >
                  {t("app.dag.navAwayTitle")}
                </h2>
                <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("app.dag.navAwayBody")}</p>
                <p className="mt-2 font-body text-xs text-on-surface-variant/90">
                  {t("app.dag.navAwayGoingTo") + navTargetLabel(dagNavAwayPending.target, t)}
                </p>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-low"
                    onClick={() => setDagNavAwayPending(null)}
                  >
                    {t("app.dag.stayHere")}
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-secondary/50 bg-secondary/15 px-4 py-2 text-xs font-semibold text-secondary hover:bg-secondary/25"
                    onClick={confirmDagNavAwayAndNavigate}
                  >
                    {t("app.dag.exitEditSwitch")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={toolbarImportModeOpen}
        danger
        title={t("app.confirm.importModeTitle")}
        message={t("app.confirm.importModeBody")}
        cancelLabel={t("common.cancel")}
        secondaryLabel={t("app.confirm.importMerge")}
        onSecondary={() => openToolbarImportConfirm("merge")}
        confirmLabel={t("app.confirm.importReplace")}
        onConfirm={() => openToolbarImportConfirm("replace")}
        onCancel={cancelToolbarImportFlow}
      />
      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={toolbarImportConfirmOpen && toolbarImportPreview !== null}
        title={t("app.confirm.importProjectTitle")}
        message={
          toolbarImportPreview
            ? t("app.confirm.importProjectBody", undefined, {
                modeLabel:
                  toolbarImportPreview.mode === "replace"
                    ? t("app.confirm.importReplace")
                    : t("app.confirm.importMerge"),
                storyLine: toolbarImportPreview.storyLine,
                macroLine: toolbarImportPreview.macroLine,
              })
            : ""
        }
        confirmLabel={t("app.confirm.importProjectConfirm")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => void handleToolbarImportConfirmed()}
        onCancel={() => {
          setToolbarImportConfirmOpen(false);
          setToolbarImportModeOpen(true);
        }}
      />
      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={compileSaveModalOpen}
        title={t("app.confirm.compileDirtyTitle")}
        message={t("app.confirm.compileDirtyBody")}
        confirmLabel={t("app.confirm.saveAndCompile")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => void handleCompileSaveModalConfirm()}
        onCancel={handleCompileSaveModalCancel}
      />
    </AppShell>
  );
}
