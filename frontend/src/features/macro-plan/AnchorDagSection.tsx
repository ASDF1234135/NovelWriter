import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

/** Passed into `graph` render prop — fullscreen targets this section’s shell element. */
export type AnchorDagFullscreenApi = {
  active: boolean;
  toggle: () => void;
  label: string;
};

type Props = {
  graph: ReactNode | ((fullscreen: AnchorDagFullscreenApi) => ReactNode);
  detail: ReactNode;
  /** Shown above the graph inside the shell so alerts stay visible in fullscreen (pointer-events on inner content). */
  fsOverlay?: ReactNode;
  toolbarExtras?: ReactNode;
  locale: string;
  /** Fires when fullscreen state changes so parent can resize the graph. */
  onFullscreenChange?: (fullscreen: boolean) => void;
  /** When the detail panel is expanded/collapsed (for parent layout if needed). */
  onDetailOpenChange?: (open: boolean) => void;
  /** Controlled detail visibility (e.g. toggle lives in graph toolbar). Omit for internal-only state. */
  detailOpen?: boolean;
};

/** Wrapper with HTML5 fullscreen; children stay inside the fullscreen element (no body-level drawer portal). */
export function AnchorDagSection({
  graph,
  detail,
  fsOverlay,
  toolbarExtras,
  locale,
  onFullscreenChange,
  onDetailOpenChange,
  detailOpen: detailOpenControlled,
}: Props) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [fullscreen, setFullscreen] = useState(false);

  const detailOpen = detailOpenControlled !== undefined ? Boolean(detailOpenControlled) : true;

  useEffect(() => {
    onFullscreenChange?.(fullscreen);
  }, [fullscreen, onFullscreenChange]);

  useEffect(() => {
    onDetailOpenChange?.(detailOpen);
  }, [detailOpen, onDetailOpenChange]);

  useEffect(() => {
    const onFs = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.fullscreenElement && shellRef.current && document.fullscreenElement === shellRef.current) {
        void document.exitFullscreen().catch(() => {});
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const enterFs = useCallback(async () => {
    const el = shellRef.current;
    if (!el) return;
    try {
      await el.requestFullscreen();
    } catch {
      setFullscreen(true);
    }
  }, []);

  const exitFs = useCallback(async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
    } catch {
      /* noop */
    }
    setFullscreen(false);
  }, []);

  const fsLabel =
    locale === "en"
      ? fullscreen
        ? "Exit fullscreen"
        : "Fullscreen"
      : locale === "zh-Hans"
        ? fullscreen
          ? "退出全屏"
          : "全屏"
        : fullscreen
          ? "離開全螢幕"
          : "全螢幕";

  const fullscreenApi: AnchorDagFullscreenApi = {
    active: fullscreen,
    toggle: () => void (fullscreen ? exitFs() : enterFs()),
    label: fsLabel,
  };

  const graphContent = typeof graph === "function" ? graph(fullscreenApi) : graph;

  return (
    <div
      ref={shellRef}
      className={
        fullscreen
          ? "relative flex max-h-[100dvh] min-h-0 flex-col gap-2 bg-background p-2"
          : "relative flex min-h-0 flex-col gap-2"
      }
    >
      {fsOverlay ? (
        <div className="pointer-events-none absolute inset-x-0 top-2 z-[60000] flex justify-center px-3">
          <div className="pointer-events-auto relative z-[60001] w-full max-w-2xl">{fsOverlay}</div>
        </div>
      ) : null}
      {toolbarExtras ? (
        <div className="flex flex-wrap items-center gap-2">
          {toolbarExtras}
        </div>
      ) : null}
      <div
        className={`relative flex min-h-0 flex-1 flex-col gap-0 lg:flex-row lg:items-stretch lg:gap-0 ${fullscreen ? "min-h-0 flex-1 overflow-hidden" : ""}`}
      >
        <div
          className={`relative min-h-0 min-w-0 flex-1 ${fullscreen ? "flex min-h-0 flex-1 flex-col overflow-hidden" : ""}`}
        >
          {graphContent}
        </div>
        {detailOpen ? (
          <aside className="relative flex max-h-[min(70vh,540px)] w-full max-w-[min(100vw,392px)] shrink-0 flex-col overflow-hidden rounded-xl border border-outline-variant/25 bg-surface-container-low shadow-[inset_1px_0_0_rgba(255,255,255,0.04)] lg:max-h-none lg:h-auto lg:w-[392px]">
            {detail}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
