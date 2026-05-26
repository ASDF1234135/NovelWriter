import { useEffect, useState } from "react";
import { fetchChapterWorkflowMetrics, fetchStoryWorkflowMetrics } from "../../api";
import type { ChapterSummary, WorkflowMetricsResponse, WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { WorkflowRunDetails } from "../workflow-monitor/WorkflowRunDetails";

type Props = {
  storyId: string;
  chapters: ChapterSummary[];
  workflow: WorkflowPayload | null;
  /** Hide page-level hero (e.g. inside a drawer that already has a title). */
  embedded?: boolean;
};

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtMs(v: number | null | undefined): string {
  if (v == null || v <= 0) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(1)} s`;
}

function shortRunId(id: string): string {
  if (id.length <= 14) return id;
  return `${id.slice(0, 10)}…`;
}

export function WorkflowMetricsDashboard({ storyId, chapters, workflow, embedded = false }: Props) {
  const { locale, t } = useI18n();
  const [scope, setScope] = useState<"story" | "chapter">("story");
  const [chapterId, setChapterId] = useState<number>(() => chapters[0]?.chapter_id ?? 1);
  const [data, setData] = useState<WorkflowMetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (chapters.length && !chapters.some((c) => c.chapter_id === chapterId)) {
      setChapterId(chapters[0].chapter_id);
    }
  }, [chapters, chapterId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const payload =
          scope === "story"
            ? await fetchStoryWorkflowMetrics(storyId)
            : await fetchChapterWorkflowMetrics(storyId, chapterId);
        if (!cancelled) setData(payload);
      } catch (e) {
        if (!cancelled) {
          setData(null);
          setError(e instanceof Error ? e.message : t("metrics.page.loadFailed"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [storyId, scope, chapterId, t]);

  const rollup = data?.rollup;

  const statTile = (label: string, value: string) => (
    <div className="rounded-xl border border-outline-variant/15 bg-surface-container-low/90 px-4 py-3 shadow-glow">
      <div className="font-label text-[10px] uppercase tracking-wider text-outline">{label}</div>
      <div className="mt-1 font-headline text-lg font-bold text-on-surface">{value}</div>
    </div>
  );

  return (
    <div className={`mx-auto max-w-7xl ${embedded ? "px-4 py-2" : ""}`}>
      {!embedded ? (
        <div className="mb-8">
          <span className="mb-2 block font-label text-xs font-semibold uppercase tracking-[0.3em] text-secondary">
            {t("common.workflowMetrics")}
          </span>
          <h1 className="mb-2 font-headline text-3xl font-black tracking-tight text-on-surface">{t("metrics.page.title")}</h1>
          <p className="max-w-3xl font-body text-sm leading-relaxed text-on-surface-variant">{t("metrics.page.subtitle")}</p>
        </div>
      ) : null}

      <div className="mb-8">
        <WorkflowRunDetails workflow={workflow} />
      </div>

      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="flex gap-2 rounded-lg border border-outline-variant/20 bg-surface-container-highest/40 p-1">
          <button
            type="button"
            className={`rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
              scope === "story" ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"
            }`}
            onClick={() => setScope("story")}
          >
            {t("metrics.page.scopeStory")}
          </button>
          <button
            type="button"
            className={`rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
              scope === "chapter" ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"
            }`}
            onClick={() => setScope("chapter")}
          >
            {t("metrics.page.scopeChapter")}
          </button>
        </div>

        {scope === "chapter" ? (
          <label className="flex flex-col gap-1 font-label text-xs text-on-surface-variant">
            {t("metrics.page.chapterLabel")}
            <select
              className="rounded-lg border border-outline-variant/25 bg-surface-container-low px-3 py-2 text-sm text-on-surface"
              value={chapterId}
              onChange={(e) => setChapterId(Number(e.target.value))}
            >
              {chapters.map((c) => (
                <option key={c.chapter_key} value={c.chapter_id}>
                  {locale === "en" ? `Chapter ${c.chapter_id}` : `第 ${c.chapter_id} 章`} — {c.title || c.status}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {error ? (
        <div className="mb-6 rounded-xl border border-error/35 bg-error/10 px-4 py-3 font-body text-sm text-error">{error}</div>
      ) : null}

      {loading ? (
        <div className="rounded-xl border border-outline-variant/15 bg-surface-container-low/80 px-4 py-8 text-center font-body text-sm text-on-surface-variant">
          {t("metrics.page.loading")}
        </div>
      ) : null}

      {!loading && data && rollup ? (
        <>
          {rollup.runs_included === 0 ? (
            <p className="rounded-xl border border-outline-variant/15 bg-surface-container-low/60 px-4 py-6 font-body text-sm text-on-surface-variant">
              {t("metrics.page.emptyRuns")}
            </p>
          ) : (
            <>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {statTile(t("metrics.page.runsIncluded"), String(rollup.runs_included))}
                {statTile(t("metrics.page.timeouts"), String(rollup.timeouts_count))}
                {statTile(t("metrics.page.completed"), String(rollup.completed_count))}
                {statTile(t("metrics.page.failed"), String(rollup.failed_count))}
              </div>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {statTile(t("metrics.page.waitingHitl"), String(rollup.waiting_hitl_count))}
                {statTile(t("metrics.page.running"), String(rollup.running_count))}
                {statTile(t("metrics.page.sumWallClock"), fmtMs(rollup.sum_wall_clock_ms))}
                {statTile(t("metrics.page.sumStepsLatency"), fmtMs(rollup.sum_steps_latency_ms))}
              </div>
              <div className="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {statTile(t("metrics.page.sumPlanRetry"), String(rollup.sum_plan_retry_count))}
                {statTile(t("metrics.page.sumDraftRetry"), String(rollup.sum_draft_retry_count))}
                {statTile(t("metrics.page.sumReaderRetry"), String(rollup.sum_reader_retry_count))}
                {statTile(t("metrics.page.hitlActions"), String(rollup.sum_hitl_actions))}
              </div>
              <div className="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {statTile(t("metrics.page.alignRetries"), String(rollup.sum_align_retry_attempts))}
                {statTile(t("metrics.page.extractionRuns"), String(rollup.sum_extraction_gate_invocations))}
                {statTile(t("metrics.page.avgEntityKept"), fmtPct(rollup.avg_entity_kept_ratio ?? null))}
                {statTile(t("metrics.page.avgRelationKept"), fmtPct(rollup.avg_relation_kept_ratio ?? null))}
              </div>

              <h2 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-primary">{t("metrics.page.tableTitle")}</h2>
              <div className="overflow-x-auto rounded-xl border border-outline-variant/15 bg-surface-container-low/90 shadow-glow">
                <table className="min-w-full border-collapse text-left text-xs md:text-sm">
                  <thead>
                    <tr className="border-b border-outline-variant/20 font-label uppercase tracking-wider text-outline">
                      <th className="px-3 py-2">{t("metrics.page.colRun")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colChapter")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colStatus")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colWall")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colPlan")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colDraft")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colReader")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colAuthorSteps")}</th>
                      <th className="px-3 py-2">{t("metrics.page.colHitl")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.runs.map((r) => (
                      <tr key={r.run_id} className="border-b border-outline-variant/10 font-body text-on-surface">
                        <td className="max-w-[120px] truncate px-3 py-2 font-mono text-[11px]" title={r.run_id}>
                          {shortRunId(r.run_id)}
                        </td>
                        <td className="px-3 py-2">{r.chapter_id}</td>
                        <td className="px-3 py-2">{r.status}</td>
                        <td className="px-3 py-2">{fmtMs(r.wall_clock_ms)}</td>
                        <td className="px-3 py-2">{r.plan_retry_count}</td>
                        <td className="px-3 py-2">{r.draft_retry_count}</td>
                        <td className="px-3 py-2">{r.reader_retry_count}</td>
                        <td className="px-3 py-2">{r.author_step_count}</td>
                        <td className="px-3 py-2">{r.hitl_actions_total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}
