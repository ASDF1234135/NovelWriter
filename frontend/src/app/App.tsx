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
  fetchLatestActiveWorkflow,
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
  waitForMacroCompileCompletion,
  type MacroCompileProgress,
} from "../api";
import { GraphView } from "../features/graph-view/GraphView";
import { HitlDevPanel } from "../features/hitl-panel/HitlDevPanel";
import { HitlFloatingDock } from "../features/hitl-panel/HitlFloatingDock";
import type { HitlChapterReviewPayload } from "../features/hitl-panel/HitlPanel";
import { ReviewShell } from "../features/review-shell/ReviewShell";
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
import { MacroBibleSummary } from "../features/macro-plan/MacroBibleSummary";
import { ChapterRunRail } from "../features/chapter-run/ChapterRunRail";
import { ChapterRunComposer } from "../features/chapter-run/ChapterRunComposer";
import { StoryLibrary } from "../features/story-library/StoryLibrary";
import { StorySetupForm } from "../features/story-setup/StorySetupForm";
import { WorkflowProgressTrack } from "../features/workflow-monitor/WorkflowProgressTrack";
import { StoryWorkflowDetailsDrawer } from "../features/workflow-monitor/StoryWorkflowDetailsDrawer";
import { LandingPage } from "../features/landing/LandingPage";
import type {
  AiFreedomLevel,
  ChapterContent,
  ChapterSummary,
  GraphSnapshot,
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
  buildMacroPutBodyForExport,
  idUnderStoryPrefix,
  namespaceMacroPlanIdsForStory,
  parseMacroImportJson,
} from "./macroPlanBundle";
import { refreshStoriesListCache, upsertStoriesListCacheItem } from "../lib/storiesListCache";
import { queryClient } from "./queryClient";
import { ProjectBundleFileActions } from "../features/story-setup/ProjectBundleFileActions";
import { localizeUserFacingError } from "../i18n/userFacingError";
import { useI18n } from "../i18n/useI18n";
import { downloadCompletedChaptersZip } from "../lib/chapterBulkDownload";

/** Same heuristic as backend OUTLINE_MIN_CHARS_FOR_FULL_BINDING — UX hint only. */
const OUTLINE_FULL_BINDING_MIN_CHARS = 100;

const CHAPTER_SUMMARIZER_LLM_SOURCE = "CHAPTER_SUMMARIZER_LLM";

const VIEW_PATH_MAP: Record<AppView, string> = {
  home: "/",
  library: "/library",
  setup: "/setup",
  write: "/write",
  review: "/review",
  graph: "/graph",
};

function pathToView(pathname: string): AppView {
  const cleaned = pathname.replace(/\/+$/, "") || "/";
  switch (cleaned) {
    case "/":
      return "home";
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
    case "/workflow-metrics":
      return "write";
    case "/export":
      return "library";
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
    home: "app.navTarget.home",
    library: "app.navTarget.library",
    setup: "app.navTarget.setup",
    write: "app.navTarget.write",
    review: "app.navTarget.review",
    graph: "app.navTarget.graph",
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
    require_chapter_review: Boolean(d.require_chapter_review),
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

  const branchRaw = candidate.branch_count_override;
  const branch_count_override =
    branchRaw === null || branchRaw === undefined
      ? null
      : Number.isFinite(Number(branchRaw))
        ? Number(branchRaw)
        : null;

  return {
    title,
    premise,
    bible: isObjectRecord(candidate.bible) ? candidate.bible : {},
    macro_author_notes: String(candidate.macro_author_notes ?? ""),
    cast_seed,
    target_total_words,
    branch_count_override,
    plan_retry_limit,
    draft_loop_retry_limit,
    output_language: normalizeOutputLanguage(candidate.output_language),
    require_chapter_review: Boolean(candidate.require_chapter_review),
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

async function persistStoryInput(storyId: string, input: StoryInput): Promise<StoryDetailResponse> {
  return patchStory(storyId, {
    title: input.title,
    premise: input.premise,
    target_total_words: input.target_total_words,
    branch_count_override: input.branch_count_override ?? null,
    plan_retry_limit: input.plan_retry_limit,
    draft_loop_retry_limit: input.draft_loop_retry_limit,
    macro_author_notes: input.macro_author_notes ?? "",
    cast_seed: input.cast_seed ?? [],
    output_language: normalizeOutputLanguage(input.output_language),
  });
}

function macroDataFromSnapshot(snap: Awaited<ReturnType<typeof fetchMacroSnapshot>>): MacroCompileData {
  return {
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
    has_completed_chapter: snap.has_completed_chapter,
    macro_edit_locked: snap.macro_edit_locked,
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
  const { locale, setLocale, t } = useI18n();
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
  /** Per-run chapter review choice; reset when the run-confirm modal opens. */
  const [runConfirmReviewChoice, setRunConfirmReviewChoice] = useState<boolean | null>(null);
  const [selectedAnchorIds, setSelectedAnchorIds] = useState<string[]>([]);
  const [writingPreamble, setWritingPreamble] = useState<WritingPreambleResponse | null>(null);
  /** Toggles the full Bible editor drawer on the chapter-run page; rail keeps a read-only summary by default. */
  const [bibleDrawerOpen, setBibleDrawerOpen] = useState(false);
  /** Mobile / narrow viewports: rail collapses to a top accordion. */
  // (former) mobile rail accordion state — reference is now Step 2 in composer.
  const [railOpenMobile] = useState(false);
  /** Run-chapter confirm modal: collects the per-run review opt-in before kicking off the pipeline. */
  const [runConfirmOpen, setRunConfirmOpen] = useState(false);
  const [compileSaveModalOpen, setCompileSaveModalOpen] = useState(false);
  const [compileInProgress, setCompileInProgress] = useState(false);
  const [compileProgress, setCompileProgress] = useState<MacroCompileProgress | null>(null);
  const [regenSummaryBusyChapter, setRegenSummaryBusyChapter] = useState<number | null>(null);
  const [configVersion, setConfigVersion] = useState(0);
  const [stageVisitCount, setStageVisitCount] = useState<Record<TaskFlowStageId, number>>({
    projectSetup: 0,
    planStructure: 0,
    writeChapter: 0,
    reviewFix: 0,
  });
  const [workflowDetailsOpen, setWorkflowDetailsOpen] = useState(false);
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
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);
  const storyIdRef = useRef(storyId);
  const chapterIdRef = useRef(chapterId);
  const chapterHardRulesRef = useRef<HTMLTextAreaElement | null>(null);

  function navigateToViewPath(nextView: AppView, replace = false) {
    const targetPath = VIEW_PATH_MAP[nextView];
    if (location.pathname !== targetPath) {
      navigate(targetPath, { replace });
    }
  }

  function exitStoryToLibrary() {
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
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0 });
    setConfigVersion((v) => v + 1);
    setError("");
    setNotice("");
    setBibleDrawerOpen(false);
    setCompileInProgress(false);
    setCompileProgress(null);
    setWorkflowDetailsOpen(false);
    navigate("/library");
  }

  function handleBrandClick() {
    if (storyId) {
      exitStoryToLibrary();
    } else {
      navigateToViewPath("home");
    }
  }

  function requestNavigateToView(nextView: AppView, replace = false) {
    if (dagInteractionMode === "edit" && view === "write" && nextView !== "write") {
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
    if (!storyId && (view === "write" || view === "review" || view === "graph")) {
      navigateToViewPath("library");
    }
  }, [storyId, view]);

  /** Legacy URLs from older builds → canonical routes + optional workflow details drawer. */
  useEffect(() => {
    const cleaned = location.pathname.replace(/\/+$/, "") || "/";
    if (cleaned === "/workflow-metrics") {
      setWorkflowDetailsOpen(true);
      navigate("/write", { replace: true });
    } else if (cleaned === "/export") {
      navigate("/library", { replace: true });
    }
  }, [location.pathname, navigate]);

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

  const chapterReviewActive = useMemo(() => {
    const reason = String(workflow?.state?.hitl_reason ?? workflow?.run?.hitl_reason ?? "");
    const waiting =
      workflow?.run?.requires_hitl === true || String(workflow?.state?.workflow_status ?? "") === "WAITING_HITL";
    return waiting && reason === "Chapter_Draft_Review";
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
    if (st === "COMPLETED" || st === "FAILED" || st === "CANCELLED") return false;
    if (workflow.run.requires_hitl === true || st === "WAITING_HITL") return false;
    return true;
  }, [workflow]);

  const chapterAnchorCandidates = useMemo(() => {
    const nodes = macroData?.anchor_nodes ?? [];
    return nodes.filter((n) => {
      const kind = String(n.node_kind ?? "").toUpperCase();
      return n.status === "UNLOCKED" && kind !== "CHECKPOINT" && kind !== "ENDING";
    });
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
    let newStoryId: string | null = null;
    try {
      const story = await createStory(payload);
      newStoryId = String(story.story_id);
      setStoryId(newStoryId);
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
      setStageVisitCount({ projectSetup: 1, planStructure: 0, writeChapter: 0, reviewFix: 0 });
      navigateToViewPath("setup");
    } catch (err) {
      reportApiError(err, "errors.createStoryFailed");
      setBusy(false);
      return;
    }
    // Chain straight into the first macro compile — the user clicked
    // "Create & start generating", so we don't bounce them back to phase 1
    // just to click "Compile" again. The StorySetupForm preserves the current
    // phase across this re-hydration via its justSubmittedRef.
    setCompileInProgress(true);
    setCompileProgress({ status: "QUEUED", percent: 5, message: t("compile.progress.queued") });
    try {
      const result = await macroCompile(newStoryId, (progress) => {
        setCompileProgress(progress);
      });
      setMacroData(result);
      try {
        setGraph(await fetchGraph(newStoryId));
      } catch {
        /* optional */
      }
      try {
        const detail = await fetchStoryDetail(newStoryId);
        const nextConfig = storyDetailToInput(detail, payload.output_language ?? "zh-Hant");
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
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0 });
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
    setStageVisitCount({ projectSetup: 0, planStructure: 0, writeChapter: 0, reviewFix: 0 });
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
    let macroCompileWasRunning = false;
    try {
      const detail = await fetchStoryDetail(selectedId);
      const nextConfig = storyDetailToInput(detail, storyConfigSnapshot?.output_language ?? "zh-Hant");
      setStoryConfigSnapshot(nextConfig);
      setPersistedStoryConfig(nextConfig);
      setConfigVersion((v) => v + 1);
      const snap = await fetchMacroSnapshot(selectedId);
      macroCompileWasRunning = (snap.macro_compile_status ?? "IDLE") === "RUNNING";
      setStoryId(selectedId);
      setStoryTitle(detail.title || title?.trim() || "");
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
      setStageVisitCount({ projectSetup: 1, planStructure: 0, writeChapter: 0, reviewFix: 0 });

      let postLoadView: AppView = "setup";
      let skipDefaultNavigate = false;
      try {
        const active = await fetchLatestActiveWorkflow(selectedId);
        if (active) {
          const wf = await fetchWorkflow(active.run_id);
          setWorkflow(wf);
          const st = String(wf.state.workflow_status ?? "");
          const terminal = st === "COMPLETED" || st === "FAILED" || st === "CANCELLED";
          const waitingHitl = wf.run.requires_hitl === true || st === "WAITING_HITL";
          if (terminal) {
            await finalizeWorkflowRunUi(active.run_id);
            skipDefaultNavigate = st === "COMPLETED" || st === "CANCELLED";
          } else if (waitingHitl) {
            /* HITL actions live in HitlFloatingDock on any view — do not force navigation. */
          } else {
            attachWorkflowEventStream(active.run_id);
            postLoadView = "write";
          }
        } else {
          setWorkflow(null);
        }
      } catch {
        setWorkflow(null);
      }
      if (!skipDefaultNavigate) {
        navigateToViewPath(postLoadView);
      }
    } catch (err) {
      reportApiError(err, "errors.loadStoryFailed");
    } finally {
      setBusy(false);
    }
    if (macroCompileWasRunning && storyIdRef.current === selectedId) {
      setCompileInProgress(true);
      setCompileProgress({
        status: "RUNNING",
        percent: 45,
        message: t("compile.progress.resuming"),
      });
      void (async () => {
        try {
          const result = await waitForMacroCompileCompletion(selectedId, (progress) => {
            setCompileProgress(progress);
          });
          if (storyIdRef.current !== selectedId) return;
          setMacroData(result);
          try {
            setGraph(await fetchGraph(selectedId));
          } catch {
            /* optional */
          }
          try {
            const detailAfter = await fetchStoryDetail(selectedId);
            const nextCfg = storyDetailToInput(detailAfter, storyConfigSnapshot?.output_language ?? "zh-Hant");
            setStoryConfigSnapshot(nextCfg);
            setPersistedStoryConfig(nextCfg);
          } catch {
            /* optional */
          }
        } catch (err) {
          if (storyIdRef.current === selectedId) {
            reportApiError(err, "errors.macroCompileFailed");
          }
        } finally {
          if (storyIdRef.current === selectedId) {
            setCompileInProgress(false);
            setCompileProgress(null);
          }
        }
      })();
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
    if (hasCompletedChapter) {
      setError(t("app.setup.macroLockedShortNotice"));
      return;
    }
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

  async function finalizeWorkflowRunUi(runId: string) {
    try {
      const wf = await fetchWorkflow(runId);
      setWorkflow(wf);
      const status = String(wf.state.workflow_status ?? "");
      if (status === "COMPLETED") {
        navigateToViewPath("review");
      } else if (status === "CANCELLED") {
        // Stay on the write view and surface a notice; chapter was abandoned by the user.
        setNotice(t("chapterReview.cancelledNotice"));
        navigateToViewPath("write");
      }
      const sid = storyIdRef.current;
      if (sid) {
        setGraph(await fetchGraph(sid));
        setChapters(await fetchChapters(sid));
        try {
          const snap = await fetchMacroSnapshot(sid);
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
            has_completed_chapter: snap.has_completed_chapter,
            macro_edit_locked: snap.macro_edit_locked,
          });
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
            const terminal = status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
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
    const terminal = st === "COMPLETED" || st === "FAILED" || st === "CANCELLED";
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

  /**
   * Pre-flight before opening the confirm modal: same guards `handleRunChapter` would surface,
   * just hoisted so the modal never opens for an invalid state.
   */
  function openRunConfirm() {
    if (!storyId) return;
    setRunConfirmReviewChoice(null);
    setRunConfirmOpen(true);
  }

  async function handleRunChapter(reviewAfterDraft: boolean) {
    if (!storyId) return;
    setError("");
    setNotice("");
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    setWorkflow(null);
    setSelectedChapter(null);
    setBusy(true);
    try {
      const useManualAnchors = selectedAnchorIds.length >= 1;
      const runOptions = {
        chapterOutline,
        chapterHardRules,
        aiFreedomLevel,
        selectedAnchorIds: useManualAnchors ? selectedAnchorIds : undefined,
        nextAnchorIds: useManualAnchors ? autoNextAnchorIds : undefined,
        requireChapterReview: reviewAfterDraft,
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
      payload.macro_plan = buildMacroPutBodyForExport(macroData);
    }
    downloadJsonFile(`${storyId}-project.json`, payload);
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

  async function applyImportProjectBundle(jsonText: string) {
    if (!storyId) return;
    const { story: parsedStory, macro_plan: parsedMacroRaw } = parseProjectBundleJson(jsonText);
    const parsedMacro = parsedMacroRaw ? namespaceMacroPlanIdsForStory(parsedMacroRaw, storyId) : undefined;

    let detail: StoryDetailResponse | null = null;
    if (parsedStory) {
      const storyToSave = { ...parsedStory };
      if (
        parsedMacro &&
        (!storyToSave.bible || Object.keys(storyToSave.bible).length === 0) &&
        isObjectRecord(parsedMacro.bible)
      ) {
        storyToSave.bible = parsedMacro.bible as Record<string, unknown>;
      }
      detail = await persistStoryInput(storyId, storyToSave);
    }

    if (parsedMacro) {
      await putMacroPlan(storyId, parsedMacro);
    }

    if (!parsedStory && !parsedMacro) return;

    const fallbackLang = storyConfigSnapshot?.output_language ?? "zh-Hant";
    detail = await fetchStoryDetail(storyId);
    const fromServer = storyDetailToInput(detail, fallbackLang);
    setStoryConfigSnapshot(fromServer);
    setPersistedStoryConfig(fromServer);
    setStoryTitle(detail.title);

    if (parsedMacro) {
      const snap = await fetchMacroSnapshot(storyId);
      setMacroData(macroDataFromSnapshot(snap));
    }

    upsertStoriesListCacheItem(queryClient, detail);
    await refreshStoriesListCache(queryClient);
    setConfigVersion((v) => v + 1);
    setNotice(t("app.import.doneNotice"));
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

  /** Chapter-review HITL actions used by HitlPanel ChapterReviewGate. */
  const chapterReviewHandlers = {
    onApprove: async (content: string, edited: boolean) => {
      if (edited) {
        await runHitlAction(
          sendDraftEdit,
          { chapter_content: content, resume_from: "chunker" },
          "errors.applyDraftFailed",
        );
      } else {
        await runHitlAction(sendHitlDecision, "APPROVE_DRAFT", "errors.sendChoiceFailed");
      }
    },
    onRerun: async () =>
      runHitlAction(sendHitlDecision, "RERUN_KEEP_DIRECTOR", "errors.sendChoiceFailed"),
    onAbandon: async () =>
      runHitlAction(sendHitlDecision, "ABANDON_CHAPTER", "errors.sendChoiceFailed"),
  };

  async function handleDownloadAllCompletedZip() {
    if (!storyId) return;
    setBusy(true);
    setError("");
    try {
      await downloadCompletedChaptersZip(storyId, chapters);
    } catch (err) {
      reportApiError(err, "errors.downloadZipFailed");
    } finally {
      setBusy(false);
    }
  }

  const { onAnchorDelay: _omitHitlAnchorDelay, ...hitlDockHandlers } = hitlHandlers;
  void _omitHitlAnchorDelay;
  const hitlChapterReviewForDock: HitlChapterReviewPayload | null =
    chapterReviewActive && workflow
      ? {
          draft: String(workflow.state?.current_draft ?? workflow.state?.best_draft_content ?? ""),
          readerScore:
            typeof workflow.state?.last_reader_score === "number" ? Number(workflow.state.last_reader_score) : null,
          onApprove: chapterReviewHandlers.onApprove,
          onAbandon: chapterReviewHandlers.onAbandon,
          onRerun: chapterReviewHandlers.onRerun,
        }
      : null;

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
  /**
   * True iff at least one chapter for the active story has status `completed`. Combines
   * server-side flags from macro snapshot with the locally cached chapters list so the
   * UI reacts immediately after a chapter run finishes (before the snapshot is refetched).
   */
  const hasCompletedChapter = useMemo(() => {
    if (macroData?.has_completed_chapter || macroData?.macro_edit_locked) return true;
    return chapters.some((c) => String(c.status ?? "").toLowerCase() === "completed");
  }, [macroData?.has_completed_chapter, macroData?.macro_edit_locked, chapters]);
  const hasAnyCompletedChapter = useMemo(
    () => macroData?.has_completed_chapter === true || chapters.some((c) => String(c.status ?? "").toLowerCase() === "completed"),
    [macroData?.has_completed_chapter, chapters],
  );
  const hasChapterRun = Boolean(workflow || chapters.length > 0);
  const chapterRunContextHeadline = storyTitle.trim() || (hasMacroCompiled ? storySummary : "");
  const completedChaptersZipCount = useMemo(
    () => chapters.filter((c) => String(c.status ?? "").toLowerCase() === "completed").length,
    [chapters],
  );
  const workflowMiniStatus = useMemo(() => {
    if (!workflow) return t("workflow.mini.notRun");
    const status = String(workflow.state.workflow_status ?? workflow.run.status ?? "");
    if (status === "WAITING_HITL") return t("workflow.mini.waitingHitl");
    if (status === "COMPLETED") return t("workflow.mini.completed");
    if (status === "FAILED") return t("workflow.mini.failed");
    if (status === "CANCELLED") return t("workflow.mini.cancelled");
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
    };
    if (!storyId && nextView !== "library" && nextView !== "setup" && nextView !== "home") {
      setNotice(t("app.nav.selectStoryFirst"));
      requestNavigateToView("library");
      return;
    }
    if (nextView === "write" && !hasMacroCompiled) {
      setNotice(t("app.nav.finishMacroFirst"));
      requestNavigateToView("setup");
      return;
    }
    if (nextView === "review" && !hasChapterRun) {
      setNotice(t("app.nav.needChapterRun"));
      requestNavigateToView("write");
      return;
    }
    if (dagInteractionMode === "edit" && view === "write" && nextView !== "write") {
      setDagNavAwayPending({ target: nextView, replace: false });
      return;
    }
    if (nextView === "setup") {
      markStageVisit(hasMacroCompiled ? "planStructure" : "projectSetup");
    } else if (nextView === "write") {
      markStageVisit("writeChapter");
    } else if (nextView === "review" || nextView === "graph") {
      markStageVisit("reviewFix");
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
    };
    if (target === "setup") {
      markStageVisit(hasMacroCompiled ? "planStructure" : "projectSetup");
    } else if (target === "write") {
      markStageVisit("writeChapter");
    } else if (target === "review" || target === "graph") {
      markStageVisit("reviewFix");
    }
    navigateToViewPath(target, pending.replace);
  }

  const anchorDagFsOverlay =
    view === "write" && anchorDagFullscreen && (error || failureNotice || notice) ? (
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

  const hideTopAlertsForAnchorFs = view === "write" && anchorDagFullscreen;

  const workspaceToolbarActions =
    storyId && (view === "setup" || view === "write" || view === "review" || view === "graph") ? (
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-full border border-outline-variant/30 bg-surface-container-high/70 px-3 py-1.5 font-label text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant transition-colors hover:border-secondary/40 hover:text-secondary"
        onClick={() => setWorkflowDetailsOpen(true)}
      >
        <span className="material-symbols-outlined text-sm" aria-hidden>
          info
        </span>
        <span className="hidden sm:inline">{t("workspace.details.title")}</span>
      </button>
    ) : null;

  if (view === "home") {
    return (
      <div className="relative min-h-screen bg-background text-on-surface">
        <div className="pointer-events-none fixed inset-0 -z-10 opacity-30">
          <div className="absolute right-[10%] top-[20%] h-[500px] w-[500px] rounded-full bg-primary/5 blur-[120px]" />
          <div className="absolute bottom-[10%] left-[5%] h-[400px] w-[400px] rounded-full bg-secondary/5 blur-[100px]" />
        </div>
        <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-outline-variant/10 bg-[#161d2f] px-6 font-headline text-sm tracking-tight md:px-8">
          <div className="text-xl font-bold uppercase tracking-widest text-primary">{t("app.brand.wordmark")}</div>
          <div className="flex items-center gap-3">
            <button type="button" className="btn-secondary text-xs font-label uppercase tracking-wider" onClick={() => navigate("/library")}>
              {t("landing.ctaPrimary")}
            </button>
            <select
              aria-label="UI language selector"
              className="rounded border border-outline-variant/30 bg-surface-container-low px-2 py-1 text-xs text-on-surface"
              value={locale}
              onChange={(e) => setLocale(e.target.value as typeof locale)}
            >
              <option value="zh-Hant">{t("lang.zhHant")}</option>
              <option value="zh-Hans">{t("lang.zhHans")}</option>
              <option value="en">{t("lang.en")}</option>
            </select>
          </div>
        </header>
        <LandingPage />
        <footer className="border-t border-outline-variant/10 py-6 text-center font-label text-xs uppercase tracking-widest text-outline">
          {locale === "en" ? "Auteur AI · Narrative Assistant" : locale === "zh-Hans" ? "Auteur AI · 叙事辅助" : "Auteur AI · 敘事輔助"}
        </footer>
      </div>
    );
  }

  return (
    <AppShell
      activeView={view}
      onViewChange={handleViewChange}
      hasSelectedStory={Boolean(storyId)}
      showStorySection={showStorySection}
      storySectionLabel={storySectionLabel}
      workflowMiniStatus={workflowMiniStatus}
      onBrandClick={handleBrandClick}
      workspaceToolbarActions={workspaceToolbarActions}
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
        <div className="min-h-[calc(100vh-12rem)] px-4 pb-16 pt-10 md:px-10 lg:px-12">
          <div className="mx-auto max-w-5xl">
            <div className="mb-10 grid grid-cols-1 gap-6 md:grid-cols-[1fr_auto] md:items-end">
              <div>
                <span className="mb-2 block font-label text-xs font-semibold uppercase tracking-[0.32em] text-secondary">
                  {t("app.setup.kicker")}
                </span>
                <h1 className="mb-3 font-headline text-5xl font-black tracking-tighter text-on-surface md:text-6xl">
                  {t("app.setup.title")}
                </h1>
                <p className="max-w-2xl font-body text-lg italic leading-relaxed text-on-surface-variant">
                  {t("app.setup.subtitle")}
                </p>
              </div>
              <div className="hidden md:block">
                <div className="rounded-full border border-outline-variant/20 bg-surface-container-low px-4 py-2 font-label text-[10px] font-semibold uppercase tracking-[0.3em] text-on-surface-variant">
                  <span className="text-secondary">{t("app.setup.storyIdLabel")}：</span>
                  <span className="ml-1 font-mono normal-case tracking-normal text-on-surface">
                    {storyId || t("app.setup.storyIdMissing")}
                  </span>
                </div>
              </div>
            </div>

            {storyId && !hasAnyCompletedChapter ? (
              <div className="mb-4 rounded-xl border border-tertiary/25 bg-tertiary/5 px-4 py-3 font-body text-sm leading-relaxed text-on-surface">
                <span className="font-headline font-bold text-tertiary">{t("app.setup.rerunCompileTitle")}</span>
                {t("app.setup.rerunCompileBody")}
              </div>
            ) : null}

            {storyId && hasAnyCompletedChapter ? (
              <div className="mb-4 rounded-xl border border-warning/35 bg-warning/10 px-4 py-3 font-body text-sm leading-relaxed text-on-surface">
                <span className="mr-2 font-headline font-bold text-warning">{t("app.setup.macroLockedTitle")}</span>
                {t("app.setup.macroLockedBody")}
              </div>
            ) : null}

            <div className="mb-6 rounded-xl border border-outline-variant/10 bg-surface-container-low/70 px-5 py-3 font-body text-sm text-on-surface-variant md:hidden">
              <span className="font-label text-[10px] uppercase tracking-[0.28em] text-secondary">
                {t("app.setup.storyIdLabel")}
              </span>
              <span className="ml-2 font-mono text-on-surface">
                {storyId || t("app.setup.storyIdMissing")}
              </span>
              <span className="ml-2">· {storySummary}</span>
            </div>

            {storyId && hasAnyCompletedChapter ? (
              <div className="rounded-2xl border border-outline-variant/15 bg-surface-container-low/60 p-5">
                <p className="mb-3 font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">
                  {t("app.setup.compiledResultsKicker")}
                </p>
                <div className="grid gap-5">
                  <section className="rounded-xl border border-outline-variant/15 bg-surface-container/40 p-4">
                    <MacroPlanPanel
                      macroData={macroData}
                      storyId={storyId || null}
                      onMacroDataUpdate={setMacroData}
                      onBusy={setBusy}
                      onError={setError}
                      editLocked
                    />
                  </section>

                  <section className="rounded-xl border border-outline-variant/15 bg-surface-container/40 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">
                        {t("chapterRail.window.dagTitle")}
                      </p>
                      <span className="rounded-full border border-outline-variant/25 bg-surface-container-high px-2 py-0.5 font-label text-[10px] font-semibold tabular-nums text-on-surface-variant">
                        {t("chapterRail.dagNodeCount", undefined, { n: setupAnchorNodes.length })}
                      </span>
                    </div>
                    <p className="mt-2 font-body text-xs leading-relaxed text-on-surface-variant">
                      {t("chapterRail.dagEditableHint")}
                    </p>
                    <div className="mt-3 overflow-hidden rounded-xl border border-outline-variant/12">
                      {setupAnchorNodes.length > 0 ? (
                        <AnchorDagSection
                          locale={locale}
                          detailOpen={false}
                          onFullscreenChange={setAnchorDagFullscreen}
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
                              onSelect={() => {}}
                              height={dagFs.active ? dagGraphHeight : 520}
                              layoutEpoch={dagLayoutEpoch}
                              detailPanelOpen={false}
                              onToggleDetailPanel={() => {}}
                              fullscreen={dagFs}
                              interactionMode="view"
                              onInteractionModeChange={() => {}}
                              linkPick={null}
                              onResolveLinkPick={() => {}}
                              onCanvasCreateNode={() => {}}
                              onGraphDeleteNode={() => {}}
                              onGraphStartLinkParent={() => {}}
                              onGraphStartLinkChild={() => {}}
                              onRemoveDependency={() => {}}
                              pendingManualPosition={null}
                              onConsumePendingManualPosition={() => {}}
                              validationHighlights={null}
                              readOnly
                            />
                          )}
                          detail={null}
                        />
                      ) : (
                        <div className="px-3 py-10 text-center font-body text-xs text-on-surface-variant">
                          {t("chapterRail.dagEmpty")}
                        </div>
                      )}
                    </div>
                  </section>
                </div>
                <ProjectBundleFileActions
                  className="mt-6 border-t border-outline-variant/10 pt-6"
                  onExportProjectBundle={hasMacroCompiled ? exportProjectBundle : undefined}
                  disabled={busy}
                  onError={setError}
                />
              </div>
            ) : (
              <StorySetupForm
                resetKey={`${storyId || "new"}-${configVersion}`}
                initialValues={storyId ? storyConfigSnapshot : null}
                onValuesChange={storyId ? setStoryConfigSnapshot : undefined}
                onSubmit={handleCreateStory}
                onCompile={storyId && !hasAnyCompletedChapter ? handleMacroCompile : undefined}
                compileBusy={compileInProgress}
                showCreateButton={!storyId}
                onExportProjectBundle={storyId && hasMacroCompiled ? exportProjectBundle : undefined}
                onImportProjectBundle={storyId && !hasAnyCompletedChapter ? applyImportProjectBundle : undefined}
                getImportBundlePreview={storyId && !hasAnyCompletedChapter ? buildImportBundlePreviewLines : undefined}
                onBusy={setBusy}
                onError={setError}
                disabled={busy}
                compiledResultsSlot={
                  storyId && hasMacroCompiled && !hasAnyCompletedChapter ? (
                    <ChapterRunRail
                      showCompiledBadge
                      anchorNodeCount={setupAnchorNodes.length}
                      bibleSlot={
                        <MacroPlanPanel
                          macroData={macroData}
                          storyId={storyId || null}
                          onMacroDataUpdate={setMacroData}
                          onBusy={setBusy}
                          onError={setError}
                          editLocked={false}
                        />
                      }
                      dagSlot={
                        setupAnchorNodes.length > 0 ? (
                          <AnchorDagSection
                            locale={locale}
                            detailOpen={dagDetailPanelOpen}
                            onDetailOpenChange={setDagDetailPanelOpen}
                            onFullscreenChange={setAnchorDagFullscreen}
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
                                height={dagFs.active ? dagGraphHeight : 480}
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
                                readOnly={false}
                              />
                            )}
                            detail={
                              <SetupAnchorDagDetailPanel
                                storyId={storyId.trim() ? storyId : null}
                                setupSelectedAnchorNode={setupSelectedAnchorNode}
                                selectedResolved={selectedResolved}
                                topologyLocked={Boolean(macroData?.topology_locked)}
                                dagFieldsEditable={dagFieldsEditable}
                                selectedAnchorLockedParentIds={selectedAnchorLockedParentIds}
                                onPatchAnchor={patchSetupAnchorNode}
                                onRequestDelete={requestDeleteSetupAnchorNode}
                              />
                            }
                          />
                        ) : (
                          <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low/60 px-3 py-10 text-center font-body text-xs text-on-surface-variant">
                            {t("chapterRail.dagEmpty")}
                          </div>
                        )
                      }
                    />
                  ) : undefined
                }
              />
            )}

            {storyId && hasMacroCompiled && !hasChapterRun ? (
              <div className="mt-6 flex flex-col gap-2 rounded-xl border border-secondary/25 bg-secondary/8 px-4 py-4 md:flex-row md:items-center md:justify-between">
                <p className="font-body text-sm leading-relaxed text-on-surface">{t("app.setup.ctaMacroReadyHint")}</p>
                <button type="button" className="btn-primary-gradient shrink-0" onClick={() => handleViewChange("write")}>
                  {t("app.setup.ctaGotoChapterRun")} →
                </button>
              </div>
            ) : null}

            {storyId && hasCompletedChapter && hasChapterRun ? (
              <div className="mt-6 flex flex-col gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-low/60 px-4 py-4">
                <p className="font-body text-sm text-on-surface-variant">{t("app.setup.ctaLockedHint")}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn-secondary" onClick={() => handleViewChange("review")}>
                    {t("app.setup.ctaGotoReview")} →
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => handleViewChange("graph")}>
                    {t("app.setup.ctaGotoGraph")} →
                  </button>
                </div>
              </div>
            ) : null}

            {compileInProgress ? (
              <div className="mt-4 rounded-xl border border-secondary/30 bg-secondary/8 px-3 py-2">
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
        </div>
      ) : null}

      {view === "review" ? (
        <ReviewShell
          storyId={storyId}
          chapterId={chapterId}
          chapters={chapters}
          selectedChapter={selectedChapter}
          outputLanguage={normalizeOutputLanguage(storyConfigSnapshot?.output_language ?? "zh-Hant")}
          busy={busy}
          workflow={workflow}
          setWorkflow={setWorkflow}
          workflowHitlActive={workflowHitlActive}
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
            } catch (err) {
              reportApiError(err, "errors.downloadChapterFailed");
            } finally {
              setBusy(false);
            }
          }}
          onDownloadAllCompletedZip={handleDownloadAllCompletedZip}
          completedChaptersZipCount={completedChaptersZipCount}
          onBackToChapterRun={() => handleViewChange("write")}
        />
      ) : null}

      {view === "graph" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background p-4 md:p-8">
          <div className="mb-6 flex flex-col gap-4 border-b border-outline-variant/10 pb-6 md:flex-row md:items-start md:justify-between">
            <div className="max-w-xl">
              <h1 className="font-headline text-xl font-bold tracking-tight text-on-surface md:text-2xl">{t("common.graph")}</h1>
              <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{t("app.graph.pageHint")}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3 md:shrink-0">
              <button type="button" className="btn-secondary" onClick={() => handleViewChange("write")}>
                {t("app.graph.backWrite")}
              </button>
              <button type="button" className="btn-secondary" onClick={() => handleViewChange("setup")}>
                {t("app.graph.backSetup")}
              </button>
              <span className="rounded-full border border-outline-variant/25 bg-surface-container-high px-3 py-1.5 text-xs font-medium text-on-surface-variant">
                {t("app.graph.readOnly")}
              </span>
            </div>
          </div>
          <GraphView graph={graph} protagonistCharacterId={macroData?.protagonist_character_id} readOnly />
        </div>
      ) : null}

      {view === "write" ? (
        <div className="min-h-[calc(100vh-12rem)] bg-background px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
            {bibleDrawerOpen ? (
              <section className="flex flex-col gap-4">
                <header className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <span className="mb-1 block font-label text-[10px] font-semibold uppercase tracking-[0.3em] text-secondary">
                      {t("app.write.compileResultKicker")}
                    </span>
                    <h2 className="font-headline text-2xl font-bold tracking-tight text-on-surface">
                      {t("chapterRail.bibleDrawerTitle")}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setBibleDrawerOpen(false)}
                  >
                    <span className="material-symbols-outlined text-base">arrow_back</span>
                    {t("chapterRail.closeBibleDrawer")}
                  </button>
                </header>
                <MacroPlanPanel
                  macroData={macroData}
                  storyId={storyId || null}
                  onMacroDataUpdate={setMacroData}
                  onBusy={setBusy}
                  onError={setError}
                  editLocked={hasCompletedChapter}
                />
              </section>
            ) : (
              <>
                <header className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="mb-1 block font-label text-[10px] font-semibold uppercase tracking-[0.3em] text-secondary">
                      {t("app.write.pageKicker")}
                    </span>
                    <h1 className="font-headline text-3xl font-black tracking-tight text-on-surface md:text-4xl">
                      {t("app.write.pageTitle", undefined, { n: nextGeneratableChapterId })}
                    </h1>
                  </div>
                  {!hasMacroCompiled ? (
                    <span className="rounded-full border border-tertiary/30 bg-tertiary/10 px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-tertiary">
                      {t("app.write.compileResultEmpty")}
                    </span>
                  ) : null}
                </header>

                <ChapterRunComposer
                  nextChapterId={nextGeneratableChapterId}
                  chapterAlreadyCompleted={chapterAlreadyCompleted}
                  formDisabled={!storyId || busy || workflowConflictLocked || chapterAlreadyCompleted}
                  referenceSlot={
                    <ChapterRunRail
                      bibleSlot={
                        <MacroPlanPanel
                          macroData={macroData}
                          storyId={storyId || null}
                          onMacroDataUpdate={setMacroData}
                          onBusy={setBusy}
                          onError={setError}
                          editLocked={hasCompletedChapter}
                        />
                      }
                      dagSlot={
                        setupAnchorNodes.length > 0 ? (
                          <AnchorDagSection
                            locale={locale}
                            fsOverlay={anchorDagFsOverlay}
                            detailOpen={anchorDagFullscreen && dagDetailPanelOpen}
                            onDetailOpenChange={setDagDetailPanelOpen}
                            onFullscreenChange={setAnchorDagFullscreen}
                            graph={(dagFs) => {
                              const railReadOnly = !dagFs.active;
                              return (
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
                                  height={dagFs.active ? dagGraphHeight : 220}
                                  layoutEpoch={dagLayoutEpoch}
                                  detailPanelOpen={dagFs.active ? dagDetailPanelOpen : false}
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
                                  readOnly={railReadOnly}
                                />
                              );
                            }}
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
                        ) : null
                      }
                      anchorNodeCount={setupAnchorNodes.length}
                      disabled={!storyId}
                    />
                  }
                  chapterOutline={chapterOutline}
                  setChapterOutline={setChapterOutline}
                  chapterHardRules={chapterHardRules}
                  setChapterHardRules={setChapterHardRules}
                  chapterHardRulesRef={chapterHardRulesRef}
                  writingPreamble={writingPreamble}
                  preambleHasNonLlmSummary={preambleHasNonLlmSummary}
                  preamblePrevChapterId={writingPreamble?.plot_progress.previous_chapter.chapter_id ?? null}
                  preamblePrevSourceNeedsRegenerate={
                    writingPreamble
                      ? plotSummarySourceNeedsRegenerate(writingPreamble.plot_progress.previous_chapter.plot_summary_source)
                      : false
                  }
                  regenSummaryBusyChapter={regenSummaryBusyChapter}
                  onRegeneratePreviousSummary={(cid) => void handleRegenerateChapterSummary(cid)}
                  chapterAnchorCandidates={chapterAnchorCandidates.map((n) => ({
                    id: String(n.id),
                    title: String(n.title ?? ""),
                    description: String(n.description ?? ""),
                  }))}
                  selectedAnchorIds={selectedAnchorIds}
                  setSelectedAnchorIds={setSelectedAnchorIds}
                  autoNextAnchorTitles={autoNextAnchorTitles}
                  aiFreedomLevel={aiFreedomLevel}
                  setAiFreedomLevel={setAiFreedomLevel}
                  onRequestRunChapter={openRunConfirm}
                  workflowProgressSlot={
                    <WorkflowProgressTrack
                      workflow={workflow}
                      compact
                      embedded
                      starting={busy}
                      headerActions={
                        storyId && (workflow || hasChapterRun) ? (
                          <>
                            <button
                              type="button"
                              disabled={!hasChapterRun || busy}
                              className={`inline-flex items-center gap-1 rounded-md border border-outline-variant/30 px-2 py-0.5 font-label text-[10px] font-semibold uppercase tracking-wider ${
                                !hasChapterRun || busy
                                  ? "cursor-not-allowed opacity-40"
                                  : "text-on-surface-variant hover:border-secondary/40 hover:text-secondary"
                              }`}
                              onClick={() => handleViewChange("review")}
                              title={
                                !hasChapterRun ? t("app.nav.needChapterRun") : t("app.write.goReviewHitl")
                              }
                            >
                              <span className="material-symbols-outlined text-sm" aria-hidden>
                                fact_check
                              </span>
                              <span className="hidden md:inline">{t("app.write.goReviewHitl")}</span>
                              <span className="md:hidden">{t("common.reviewFix")}</span>
                            </button>
                            <button
                              type="button"
                              disabled={!hasChapterRun || busy}
                              className={`inline-flex items-center gap-1 rounded-md border border-outline-variant/30 px-2 py-0.5 font-label text-[10px] font-semibold uppercase tracking-wider ${
                                !hasChapterRun || busy
                                  ? "cursor-not-allowed opacity-40"
                                  : "text-on-surface-variant hover:border-secondary/40 hover:text-secondary"
                              }`}
                              onClick={() => handleViewChange("graph")}
                              title={!hasChapterRun ? t("app.nav.needChapterRun") : t("app.write.goGraph")}
                            >
                              <span className="material-symbols-outlined text-sm" aria-hidden>
                                hub
                              </span>
                              <span className="hidden md:inline">{t("app.write.goGraph")}</span>
                              <span className="md:hidden">{t("common.graph")}</span>
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              className="inline-flex items-center gap-1 rounded-md border border-outline-variant/30 px-2 py-0.5 font-label text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant hover:border-secondary/40 hover:text-secondary disabled:cursor-not-allowed disabled:opacity-40"
                              onClick={() => setWorkflowDetailsOpen(true)}
                              title={t("workspace.details.title")}
                            >
                              <span className="material-symbols-outlined text-sm" aria-hidden>
                                monitoring
                              </span>
                              <span className="hidden md:inline">{t("workspace.details.title")}</span>
                              <span className="md:hidden">{t("workspace.details.title")}</span>
                            </button>
                          </>
                        ) : null
                      }
                    />
                  }
                />
              </>
            )}
          </div>
        </div>
      ) : null}
      {storyId ? (
        <StoryWorkflowDetailsDrawer
          open={workflowDetailsOpen}
          onClose={() => setWorkflowDetailsOpen(false)}
          storyId={storyId}
          chapters={chapters}
          workflow={workflow}
        />
      ) : null}
      {storyId && (view === "setup" || view === "write" || view === "review" || view === "graph") ? (
        <div className="pointer-events-none fixed bottom-6 left-6 z-[60] max-w-sm">
          <div className="pointer-events-auto">
            <HitlDevPanel
              workflow={workflow}
              setWorkflow={setWorkflow}
              setGraph={setGraph}
              onNavigateReview={() => navigateToViewPath("review")}
              variant="compact"
            />
          </div>
        </div>
      ) : null}
      {storyId && (view === "setup" || view === "write" || view === "review" || view === "graph") ? (
        <HitlFloatingDock
          workflow={workflow}
          workflowHitlActive={workflowHitlActive}
          graph={graph}
          storyId={storyId}
          busy={busy}
          workflowError={workflowHitlActive ? error : ""}
          chapterReview={hitlChapterReviewForDock}
          {...hitlDockHandlers}
        />
      ) : null}
      {runConfirmOpen && dagDialogMount
        ? createPortal(
            <div
              className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="run-confirm-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) setRunConfirmOpen(false);
              }}
            >
              <div
                className="max-w-md rounded-2xl border border-outline-variant/30 bg-surface-container-high p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <h2
                  id="run-confirm-title"
                  className="font-headline text-xl font-bold tracking-tight text-on-surface"
                >
                  {t("chapterRun.runConfirm.title", undefined, { n: nextGeneratableChapterId })}
                </h2>
                <p className="mt-2 font-body text-sm leading-relaxed text-on-surface-variant">
                  {t("chapterRun.runConfirm.body")}
                </p>
                {!hasAnyCompletedChapter ? (
                  <p className="mt-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 font-body text-xs leading-relaxed text-on-surface">
                    {t("chapterRun.runConfirm.compileLockWarn")}
                  </p>
                ) : null}
                <fieldset className="mt-4 rounded-xl border border-outline-variant/20 bg-surface-container px-3 py-3">
                  <legend className="px-1 font-label text-[11px] font-bold uppercase tracking-wider text-secondary">
                    {t("chapterRun.runConfirm.reviewQuestion")}
                  </legend>
                  <p id="run-confirm-review-hint" className="mt-1 font-body text-xs leading-relaxed text-on-surface-variant">
                    {t("chapterRun.runConfirm.reviewHint")}
                  </p>
                  <div className="mt-3 flex flex-col gap-2">
                    <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-outline-variant/15 bg-surface-container-high/60 px-3 py-2.5 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/8">
                      <input
                        type="radio"
                        name="run-confirm-review"
                        className="mt-0.5 h-4 w-4 accent-primary"
                        checked={runConfirmReviewChoice === true}
                        onChange={() => setRunConfirmReviewChoice(true)}
                      />
                      <span className="font-body text-sm text-on-surface">{t("chapterRun.runConfirm.reviewYes")}</span>
                    </label>
                    <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-outline-variant/15 bg-surface-container-high/60 px-3 py-2.5 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/8">
                      <input
                        type="radio"
                        name="run-confirm-review"
                        className="mt-0.5 h-4 w-4 accent-primary"
                        checked={runConfirmReviewChoice === false}
                        onChange={() => setRunConfirmReviewChoice(false)}
                      />
                      <span className="font-body text-sm text-on-surface">{t("chapterRun.runConfirm.reviewNo")}</span>
                    </label>
                  </div>
                </fieldset>
                <div className="mt-5 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-white/5"
                    onClick={() => setRunConfirmOpen(false)}
                    disabled={busy}
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="btn-primary-gradient h-10 min-w-[8rem] px-5 text-sm"
                    onClick={() => {
                      if (runConfirmReviewChoice === null) return;
                      const reviewAfterDraft = runConfirmReviewChoice;
                      setRunConfirmOpen(false);
                      void handleRunChapter(reviewAfterDraft);
                    }}
                    disabled={busy || runConfirmReviewChoice === null}
                  >
                    <span className="material-symbols-outlined text-base" aria-hidden>
                      auto_awesome
                    </span>
                    {t("chapterRun.runConfirm.confirm")}
                  </button>
                </div>
              </div>
            </div>,
            dagDialogMount,
          )
        : null}
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
