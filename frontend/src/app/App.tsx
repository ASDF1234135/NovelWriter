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
  MacroCompileData,
  StoryDetailResponse,
  StoryInput,
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
  const [chapterAlreadyCompleted, setChapterAlreadyCompleted] = useState(false);
  const [storyConfigSnapshot, setStoryConfigSnapshot] = useState<StoryInput | null>(null);
  const [configurationLocked, setConfigurationLocked] = useState(false);
  const [configVersion, setConfigVersion] = useState(0);
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);
  const storyIdRef = useRef(storyId);
  const chapterIdRef = useRef(chapterId);

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
        setError(err.message);
        setBusy(false);
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
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    setBusy(true);
    try {
      const initial = await runChapter(storyId, chapterId);
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
        setSelectedChapter(await fetchChapter(storyId, selectedChapter.chapter_id));
      }
      try {
        const probe = await fetchChapterIfExists(storyId, chapterId);
        setChapterAlreadyCompleted(probe?.status === "completed");
      } catch {
        setChapterAlreadyCompleted(false);
      }
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

          <div className="mb-8 flex max-w-7xl flex-wrap items-center gap-3 rounded-xl border border-outline-variant/10 bg-surface-container-low/80 p-4 font-label shadow-glow">
            <button
              type="button"
              className="btn-primary-gradient flex items-center gap-2 text-sm"
              onClick={handleMacroCompile}
              disabled={!storyId || busy || workflowConflictLocked}
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
                className="w-20 rounded-lg border-none bg-surface-container-highest px-2 py-2 text-on-surface"
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
            {chapterAlreadyCompleted ? (
              <span className="text-xs text-tertiary">第 {chapterId} 章已完成（無法重跑）</span>
            ) : null}
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
                disabled={busy}
              />
            </div>
            <div className="lg:col-span-7">
              <MacroPlanPanel macroData={macroData} />
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
                setError(err instanceof Error ? err.message : "無法載入章節");
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
