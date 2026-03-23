import { useEffect, useMemo, useRef, useState } from "react";
import {
  createStory,
  downloadChapterTxt,
  fetchChapter,
  fetchChapterIfExists,
  fetchChapters,
  fetchGraph,
  fetchWorkflow,
  macroCompile,
  runChapter,
  subscribeWorkflowEvents,
  sendDraftEdit,
  sendHitlDecision,
  sendOutlineEdit,
  sendStateInjection,
} from "../api";
import { AgentOutputView } from "../features/agent-output/AgentOutputView";
import { ChapterReader } from "../features/chapter-reader/ChapterReader";
import { GraphView } from "../features/graph-view/GraphView";
import { HitlPanel } from "../features/hitl-panel/HitlPanel";
import { MacroPlanPanel } from "../features/macro-plan/MacroPlanPanel";
import { StorySetupForm } from "../features/story-setup/StorySetupForm";
import { WorkflowMonitor } from "../features/workflow-monitor/WorkflowMonitor";
import type { ChapterContent, ChapterSummary, GraphSnapshot, MacroCompileData, StoryInput, WorkflowPayload } from "../types";

export default function App() {
  const [storyId, setStoryId] = useState<string>("");
  const [chapterId, setChapterId] = useState<number>(1);
  const [macroData, setMacroData] = useState<MacroCompileData | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowPayload | null>(null);
  const [graph, setGraph] = useState<GraphSnapshot | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<ChapterContent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [chapterAlreadyCompleted, setChapterAlreadyCompleted] = useState(false);
  const workflowEventsUnsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      workflowEventsUnsubRef.current?.();
      workflowEventsUnsubRef.current = null;
    };
  }, []);

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

  const storySummary = useMemo(() => {
    if (!macroData) {
      return "尚未完成 macro compile。";
    }
    const volumes = macroData.volumes ?? [];
    const anchors = macroData.anchors ?? [];
    const cast = macroData.cast ?? [];
    const castPart = cast.length > 0 ? ` | Cast: ${cast.length}` : "";
    return `Volumes: ${volumes.length} | Anchors: ${anchors.length}${castPart}`;
  }, [macroData]);

  async function handleCreateStory(payload: StoryInput) {
    setBusy(true);
    setError("");
    try {
      const story = await createStory(payload);
      setStoryId(String(story.story_id));
      setWorkflow(null);
      setMacroData(null);
      setGraph(null);
      setChapters([]);
      setSelectedChapter(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create story");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to macro compile");
    } finally {
      setBusy(false);
    }
  }

  async function handleRunChapter() {
    if (!storyId) return;
    setBusy(true);
    setError("");
    workflowEventsUnsubRef.current?.();
    workflowEventsUnsubRef.current = null;
    try {
      const initial = await runChapter(storyId, chapterId);
      setWorkflow(initial);
      const runId = initial.run.run_id;

      workflowEventsUnsubRef.current = subscribeWorkflowEvents(runId, {
        onProgress: async () => {
          try {
            setWorkflow(await fetchWorkflow(runId));
            if (storyId) {
              try {
                setGraph(await fetchGraph(storyId));
              } catch {
                /* graph optional during run */
              }
            }
          } catch {
            /* ignore transient fetch errors */
          }
        },
        onEnd: async () => {
          workflowEventsUnsubRef.current = null;
          try {
            setWorkflow(await fetchWorkflow(runId));
            if (storyId) {
              setGraph(await fetchGraph(storyId));
              setChapters(await fetchChapters(storyId));
              try {
                setSelectedChapter(await fetchChapter(storyId, chapterId));
              } catch {
                /* chapter row may be missing on hard failure */
              }
              const probe = await fetchChapterIfExists(storyId, chapterId);
              setChapterAlreadyCompleted(probe?.status === "completed");
            }
          } catch (err) {
            setError(err instanceof Error ? err.message : "Workflow 結束後更新失敗");
          } finally {
            setBusy(false);
          }
        },
        onError: (err) => {
          workflowEventsUnsubRef.current = null;
          setError(err.message);
          setBusy(false);
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run chapter");
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

  return (
    <main className="layout">
      <header className="hero">
        <div>
          <h1>NovelBuilder AI Dashboard</h1>
          <p>混合驅動、多 Agent、可觀測與可介入的小說工作流中控台。</p>
        </div>
        <div className="hero-actions">
          <button onClick={handleMacroCompile} disabled={!storyId || busy}>
            1. Macro Compile
          </button>
          <input type="number" value={chapterId} onChange={(event) => setChapterId(Number(event.target.value))} min={1} />
          <button onClick={handleRunChapter} disabled={!storyId || busy || chapterAlreadyCompleted} title={chapterAlreadyCompleted ? "本章已完整生成並入庫，無法再次執行" : undefined}>
            2. Run Chapter
          </button>
          {chapterAlreadyCompleted ? <span className="muted">（第 {chapterId} 章已完成，無法重跑流程）</span> : null}
          <button onClick={refreshWorkflow} disabled={!workflow || busy}>
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <StorySetupForm onSubmit={handleCreateStory} disabled={busy} />

      <section className="panel">
        <h2>故事狀態</h2>
        <p>Story ID: {storyId || "未建立"}</p>
        <p>{storySummary}</p>
      </section>

      <MacroPlanPanel macroData={macroData} />
      <WorkflowMonitor workflow={workflow} />
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
            setError(err instanceof Error ? err.message : "Failed to load chapter");
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
            setError(err instanceof Error ? err.message : "Failed to download chapter");
          } finally {
            setBusy(false);
          }
        }}
      />
      <AgentOutputView workflow={workflow} />
      <GraphView graph={graph} />
      <HitlPanel
        workflow={workflow}
        onDecision={async (optionId) => {
          if (!workflow) return;
          setWorkflow(await sendHitlDecision(workflow.run.run_id, optionId));
        }}
        onOutlineEdit={async (payload) => {
          if (!workflow) return;
          setWorkflow(await sendOutlineEdit(workflow.run.run_id, payload));
        }}
        onDraftEdit={async (payload) => {
          if (!workflow) return;
          setBusy(true);
          setError("");
          try {
            setWorkflow(await sendDraftEdit(workflow.run.run_id, payload));
            if (storyId) {
              setGraph(await fetchGraph(storyId));
              setChapters(await fetchChapters(storyId));
            }
          } catch (err) {
            setError(err instanceof Error ? err.message : "Draft edit failed");
          } finally {
            setBusy(false);
          }
        }}
        onStateInjection={async (payload) => {
          if (!workflow) return;
          setWorkflow(await sendStateInjection(workflow.run.run_id, payload));
          if (storyId) {
            setGraph(await fetchGraph(storyId));
          }
        }}
      />
    </main>
  );
}
