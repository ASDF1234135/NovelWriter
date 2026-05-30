import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";
import type { GraphSnapshot, WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { HitlPanel, type HitlChapterReviewPayload } from "./HitlPanel";
import { HITL_REASON } from "./hitlCopy";

type HitlHandlers = {
  onDecision: (optionId: string) => Promise<void>;
  onOutlineEdit: (payload: {
    ground_truth_events: Array<Record<string, unknown>>;
    narrative_script?: string;
  }) => Promise<void>;
  onStateInjection: (payload: {
    mutations: Array<Record<string, unknown>>;
    chapter_hard_rules?: string;
    resume_from?: string;
    reason?: string;
    this_chapter_pacing_limit?: string;
    future_anchor_title?: string;
    future_anchor_description?: string;
    chapters_to_delay?: number | null;
  }) => Promise<void>;
  onDraftEdit: (payload: {
    chapter_content: string;
    resume_from?: string;
    merge_extraction_hints?: boolean;
  }) => Promise<void>;
  onDirectorPatch?: (payload: {
    chapter_type?: string;
    b_story_directive?: string | null;
    b_story_type?: string | null;
    new_elements_to_introduce?: string[];
    narrative_directive?: string;
    reason?: string;
  }) => Promise<void>;
  onExtractionRemap?: (payload: {
    entity_remaps: Array<{ from_node_id: string; to_node_id: string }>;
    waive_mandatory_node_ids?: string[];
    reason?: string;
  }) => Promise<void>;
  onAnchorResolution?: (payload: {
    action: "force_resolve" | "rewrite" | "delay_anchor" | "continue_unresolved";
    resolved_anchor_ids?: string[];
    delayed_anchor_ids?: string[];
    reject_resume_from?: string;
    reason?: string;
  }) => Promise<void>;
  onContextPrune?: (payload: { graph_rag_context_tier: number; reason?: string }) => Promise<void>;
};

type Props = HitlHandlers & {
  workflow: WorkflowPayload | null;
  workflowHitlActive: boolean;
  graph?: GraphSnapshot | null;
  storyId?: string | null;
  busy?: boolean;
  /** Surfaced inside the panel when HITL is active. */
  workflowError?: string;
  /** Chapter_Draft_Review UI (embedded in panel instead of manuscript overlay). */
  chapterReview?: HitlChapterReviewPayload | null;
};

const STORAGE_KEY = "review.hitlDock.v1";
const SESSION_DISMISSED_KEY = "review.hitlDock.dismissedRuns.v1";

type DockGeom = {
  width: number;
  height: number;
  right: number;
  bottom: number;
  minimized: boolean;
};

const DEFAULT_GEOM: DockGeom = {
  width: 520,
  height: 640,
  right: 24,
  bottom: 24,
  // Default to a candle pill in the corner. The dock auto-expands when
  // workflowHitlActive transitions to true for a fresh run_id.
  minimized: true,
};

const MIN_WIDTH = 380;
const MAX_WIDTH = 820;
const MIN_HEIGHT = 320;

function clampGeom(next: DockGeom): DockGeom {
  if (typeof window === "undefined") return next;
  const maxRight = Math.max(0, window.innerWidth - MIN_WIDTH - 16);
  const maxBottom = Math.max(0, window.innerHeight - MIN_HEIGHT - 16);
  const maxHeight = Math.max(MIN_HEIGHT, Math.round(window.innerHeight * 0.9));
  return {
    minimized: next.minimized,
    width: Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(next.width))),
    height: Math.max(MIN_HEIGHT, Math.min(maxHeight, Math.round(next.height))),
    right: Math.max(0, Math.min(maxRight, Math.round(next.right))),
    bottom: Math.max(0, Math.min(maxBottom, Math.round(next.bottom))),
  };
}

function loadGeom(): DockGeom {
  if (typeof window === "undefined") return DEFAULT_GEOM;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_GEOM;
    const parsed = JSON.parse(raw) as Partial<DockGeom>;
    return clampGeom({ ...DEFAULT_GEOM, ...parsed });
  } catch {
    return DEFAULT_GEOM;
  }
}

function saveGeom(geom: DockGeom): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(geom));
  } catch {
    /* no-op */
  }
}

function readDismissedRunIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.sessionStorage.getItem(SESSION_DISMISSED_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.map((x) => String(x)));
  } catch {
    return new Set();
  }
}

function writeDismissedRunIds(set: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      SESSION_DISMISSED_KEY,
      JSON.stringify(Array.from(set)),
    );
  } catch {
    /* no-op */
  }
}

/**
 * Short reason code shown on the minimized candle pill. Falls back to a
 * generic "HITL" when no specific reason is active.
 */
function shortReasonCode(reason: string): string {
  switch (reason) {
    case HITL_REASON.PLAN_LOOP:
    case HITL_REASON.RESOLUTION_TACTIC:
    case HITL_REASON.ENDING_VIBE:
    case HITL_REASON.B_STORY_COOLDOWN:
      return "PLAN";
    case HITL_REASON.DRAFT_LOOP:
      return "DRAFT";
    case HITL_REASON.EXTRACTION_GATE:
      return "REMAP";
    case HITL_REASON.B_STORY:
    case HITL_REASON.ANCHOR_RESOLVE:
      return "ANCHOR";
    case HITL_REASON.CONTEXT:
      return "CTX";
    case HITL_REASON.ALIGNMENT_RULES_REQUIRED:
      return "RULES";
    case HITL_REASON.OUTPUT_LANGUAGE:
      return "LANG";
    case HITL_REASON.CHAPTER_DRAFT_REVIEW:
      return "REVIEW";
    default:
      return "HITL";
  }
}

/**
 * Floating, draggable, resizable, minimizable panel that hosts the full
 * {@link HitlPanel} variant="default". Sits in the bottom-right of the
 * review-shell stage.
 *
 * Auto-open contract:
 *  - When `workflowHitlActive` transitions from false to true for a new run_id
 *    (one not yet present in the session-scoped dismissed set), the dock
 *    expands automatically.
 *  - If the user explicitly minimizes the dock for that run_id, the run_id is
 *    recorded in sessionStorage so subsequent re-renders of the same run do
 *    not pop the dock open again.
 *  - When HITL is not active and the user hasn't pinned the dock open, the
 *    dock collapses to a small candle pill in the corner.
 */
function isLargeViewport(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia?.("(min-width: 1024px)").matches ?? true;
}

export function HitlFloatingDock(props: Props) {
  const {
    workflow,
    workflowHitlActive,
    graph = null,
    storyId = null,
    busy = false,
    workflowError = "",
    chapterReview = null,
    ...handlers
  } = props;
  const { t } = useI18n();
  const [geom, setGeom] = useState<DockGeom>(() => loadGeom());
  const [isLarge, setIsLarge] = useState<boolean>(() => isLargeViewport());
  const [dragState, setDragState] = useState<null | { kind: "drag" | "resize"; startX: number; startY: number; startGeom: DockGeom }>(null);
  const [expanded, setExpanded] = useState(false);
  const dismissedRef = useRef<Set<string>>(readDismissedRunIds());
  const prevRunIdRef = useRef<string | null>(null);
  const prevHitlActiveRef = useRef<boolean>(false);

  const runId = workflow?.run.run_id ?? null;
  const reason = String(workflow?.state?.hitl_reason ?? workflow?.run?.hitl_reason ?? "");
  const minimized = geom.minimized;

  useEffect(() => {
    saveGeom(geom);
  }, [geom]);

  // Auto-expand on HITL activation for a fresh run_id.
  useEffect(() => {
    const becameActive = workflowHitlActive && !prevHitlActiveRef.current;
    const runChanged = runId !== prevRunIdRef.current;
    prevHitlActiveRef.current = workflowHitlActive;
    prevRunIdRef.current = runId;
    if (!workflowHitlActive) return;
    if (!runId) return;
    if (!becameActive && !runChanged) return;
    if (dismissedRef.current.has(runId)) return;
    if (!minimized) return;
    setGeom((prev) => ({ ...prev, minimized: false }));
  }, [workflowHitlActive, runId, minimized]);

  useEffect(() => {
    if (!geom.minimized) return;
    setExpanded(false);
  }, [geom.minimized]);

  // Esc: exit expanded overlay first, otherwise minimize dock pill.
  useEffect(() => {
    if (minimized) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (expanded) {
          setExpanded(false);
          return;
        }
        setGeom((prev) => ({ ...prev, minimized: true }));
        if (runId) {
          const next = new Set(dismissedRef.current);
          next.add(runId);
          dismissedRef.current = next;
          writeDismissedRunIds(next);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [minimized, runId, expanded]);

  // Clamp geometry when the viewport resizes (so dock stays on-screen).
  // Also keep `isLarge` in sync so the dock can flip into a full-width
  // bottom-sheet on small screens without remount.
  useEffect(() => {
    function onResize() {
      setGeom((prev) => clampGeom(prev));
      setIsLarge(isLargeViewport());
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const beginDrag = useCallback(
    (e: ReactPointerEvent<HTMLElement>, kind: "drag" | "resize") => {
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      setDragState({
        kind,
        startX: e.clientX,
        startY: e.clientY,
        startGeom: geom,
      });
    },
    [geom],
  );

  useEffect(() => {
    if (!dragState) return;
    function onMove(e: PointerEvent) {
      if (!dragState) return;
      const dx = e.clientX - dragState.startX;
      const dy = e.clientY - dragState.startY;
      if (dragState.kind === "drag") {
        setGeom((_prev) =>
          clampGeom({
            ...dragState.startGeom,
            right: dragState.startGeom.right - dx,
            bottom: dragState.startGeom.bottom - dy,
          }),
        );
      } else {
        setGeom((_prev) =>
          clampGeom({
            ...dragState.startGeom,
            width: dragState.startGeom.width - dx,
            height: dragState.startGeom.height - dy,
          }),
        );
      }
    }
    function onUp() {
      setDragState(null);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    window.addEventListener("pointercancel", onUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragState]);

  const handleMinimize = useCallback(() => {
    setExpanded(false);
    setGeom((prev) => ({ ...prev, minimized: true }));
    if (runId) {
      const next = new Set(dismissedRef.current);
      next.add(runId);
      dismissedRef.current = next;
      writeDismissedRunIds(next);
    }
  }, [runId]);

  const handleExpand = useCallback(() => {
    setExpanded(false);
    setGeom((prev) => ({ ...prev, minimized: false }));
    if (runId) {
      const next = new Set(dismissedRef.current);
      next.delete(runId);
      dismissedRef.current = next;
      writeDismissedRunIds(next);
    }
  }, [runId]);

  const mount = typeof document !== "undefined" ? document.body : null;
  if (!mount) return null;

  const shortCode = shortReasonCode(reason);
  const beaconLabel = workflowHitlActive
    ? t("reviewShell.ribbon.hitlBeacon.awaiting")
    : t("reviewShell.ribbon.hitlBeacon.idle");

  if (minimized) {
    return createPortal(
      <button
        type="button"
        onClick={handleExpand}
        className={`fixed bottom-6 right-6 z-[70] inline-flex items-center gap-2 rounded-full border px-4 py-2 font-label text-[11px] font-bold uppercase tracking-[0.22em] backdrop-blur transition-transform hover:-translate-y-0.5 ${
          workflowHitlActive
            ? "atelier-candle-strong border-tertiary/55 bg-tertiary/15 text-tertiary"
            : "atelier-candle-pulse border-secondary/40 bg-surface-container-low/80 text-secondary"
        }`}
        aria-label={`${t("reviewShell.dock.openHint")} (${beaconLabel})`}
        data-testid="hitl-dock-pill"
      >
        <span
          className="material-symbols-outlined text-base"
          aria-hidden
          style={
            workflowHitlActive
              ? { filter: "drop-shadow(0 0 12px rgba(255,183,131,0.92)) drop-shadow(0 0 22px rgba(233,195,73,0.35))" }
              : { filter: "drop-shadow(0 0 6px rgba(233,195,73,0.28))" }
          }
        >
          local_fire_department
        </span>
        <span className="font-mono text-[10px] tracking-widest">{shortCode}</span>
        <span className="hidden text-on-surface-variant sm:inline">·</span>
        <span className="hidden text-on-surface-variant sm:inline">{beaconLabel}</span>
      </button>,
      mount,
    );
  }

  const hitlPanelEl = (
    <HitlPanel
      workflow={workflow}
      graph={graph}
      storyId={storyId || null}
      variant="default"
      busy={busy}
      workflowError={workflowError}
      chapterReview={chapterReview}
      {...handlers}
    />
  );

  if (expanded) {
    return createPortal(
      <div className="fixed inset-0 z-[75] flex items-start justify-center px-3 pt-10 md:px-6 md:pt-14">
        <button
          type="button"
          className="absolute inset-0 cursor-default bg-black/55 backdrop-blur-[2px]"
          aria-label={t("reviewShell.dock.shrinkFromWindow")}
          onClick={() => setExpanded(false)}
        />
        <section
          className="nb-panel relative z-[76] flex max-h-[min(920px,calc(100vh-5rem))] w-full max-w-4xl flex-col overflow-hidden rounded-2xl shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="hitl-dock-expanded-title"
          data-testid="hitl-floating-dock-expanded"
          onClick={(e) => e.stopPropagation()}
        >
          <header className="flex shrink-0 items-center gap-2 border-b border-outline-variant/15 bg-surface-container-low/90 px-4 py-3">
            <span className="material-symbols-outlined text-base text-tertiary" aria-hidden>
              local_fire_department
            </span>
            <h2 id="hitl-dock-expanded-title" className="min-w-0 flex-1 font-headline text-sm font-bold uppercase tracking-[0.2em] text-secondary">
              {workflowHitlActive ? t("reviewShell.dock.title") : t("reviewShell.dock.idleTitle")}
            </h2>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="inline-flex h-8 items-center justify-center rounded-md border border-outline-variant/25 px-2 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
              aria-label={t("reviewShell.dock.shrinkFromWindow")}
            >
              <span className="material-symbols-outlined text-base" aria-hidden>
                dock_to_right
              </span>
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-auto p-3">{hitlPanelEl}</div>
        </section>
      </div>,
      mount,
    );
  }

  // On small screens the dock collapses into a full-width bottom-sheet
  // anchored at the bottom of the viewport. Drag/resize are disabled
  // because there is nowhere meaningful to drag to.
  const sheetStyle: CSSProperties = isLarge
    ? {
        right: geom.right,
        bottom: geom.bottom,
        width: `min(${geom.width}px, calc(100vw - 32px))`,
        height: `min(${geom.height}px, calc(100vh - 96px))`,
      }
    : {
        left: 0,
        right: 0,
        bottom: 0,
        width: "100vw",
        maxHeight: "78vh",
        height: "auto",
        borderBottomLeftRadius: 0,
        borderBottomRightRadius: 0,
      };
  const sheetClass = isLarge
    ? "atelier-dock-enter atelier-brass-glow fixed z-[70] flex max-h-[90vh] flex-col rounded-2xl border border-secondary/30 bg-surface-container-low/95 backdrop-blur lg:rounded-2xl"
    : "atelier-drawer-enter atelier-brass-glow fixed z-[70] flex max-h-[78vh] flex-col rounded-t-2xl border border-secondary/30 bg-surface-container-low/95 backdrop-blur";

  return createPortal(
    <section
      className={sheetClass}
      style={sheetStyle}
      role="dialog"
      aria-modal="false"
      aria-labelledby="hitl-dock-title"
      data-testid="hitl-floating-dock"
      data-variant={isLarge ? "floating" : "sheet"}
    >
      <header
        className={`flex shrink-0 select-none items-center gap-2 border-b border-secondary/20 bg-surface-container-low/80 px-3 py-2 ${
          isLarge ? "cursor-move" : ""
        }`}
        onPointerDown={isLarge ? (e) => beginDrag(e, "drag") : undefined}
        role="toolbar"
        aria-label={t("reviewShell.dock.dragHandle")}
      >
        <span
          className="material-symbols-outlined text-base text-tertiary"
          aria-hidden
          style={{ filter: "drop-shadow(0 0 4px rgba(255,183,131,0.5))" }}
        >
          local_fire_department
        </span>
        <h2
          id="hitl-dock-title"
          className="min-w-0 flex-1 truncate font-headline text-[11px] font-bold uppercase tracking-[0.24em] text-secondary"
        >
          {workflowHitlActive ? t("reviewShell.dock.title") : t("reviewShell.dock.idleTitle")}
        </h2>
        {busy ? (
          <span
            className="inline-block h-2 w-2 animate-pulse rounded-full bg-secondary"
            aria-hidden
          />
        ) : null}
        <span className="hidden font-mono text-[10px] text-on-surface-variant sm:inline">
          {shortCode}
        </span>
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="ml-1 inline-flex h-7 w-7 items-center justify-center rounded-md text-on-surface-variant hover:bg-surface-container-high hover:text-secondary"
          aria-label={t("reviewShell.dock.expandToWindow")}
          data-testid="hitl-dock-expand"
        >
          <span className="material-symbols-outlined text-base" aria-hidden>
            open_in_full
          </span>
        </button>
        <button
          type="button"
          onClick={handleMinimize}
          className="ml-1 inline-flex h-7 w-7 items-center justify-center rounded-md text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
          aria-label={t("reviewShell.dock.minimize")}
          data-testid="hitl-dock-minimize"
        >
          <span className="material-symbols-outlined text-base" aria-hidden>
            remove
          </span>
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3">{hitlPanelEl}</div>
      <button
        type="button"
        onPointerDown={(e) => beginDrag(e, "resize")}
        aria-label={t("reviewShell.dock.resizeHandle")}
        className="absolute left-0 top-0 hidden h-5 w-5 cursor-nwse-resize items-center justify-center rounded-tl-2xl text-secondary/70 hover:text-secondary lg:flex"
        style={{
          background:
            "linear-gradient(135deg, rgba(233,195,73,0.45) 0%, rgba(233,195,73,0) 60%)",
        }}
        data-testid="hitl-dock-resize"
      >
        <span aria-hidden className="block h-2 w-2 -translate-x-0.5 -translate-y-0.5">
          <svg viewBox="0 0 8 8" className="h-full w-full">
            <path
              d="M0 6 L6 0 M0 2 L2 0 M0 4 L4 0"
              stroke="currentColor"
              strokeWidth="1"
              fill="none"
            />
          </svg>
        </span>
      </button>
    </section>,
    mount,
  );
}

export const __HITL_DOCK_TEST_HOOKS__ = {
  STORAGE_KEY,
  SESSION_DISMISSED_KEY,
  DEFAULT_GEOM,
  shortReasonCode,
};
