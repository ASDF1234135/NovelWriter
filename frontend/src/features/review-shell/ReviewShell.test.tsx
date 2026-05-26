import { render, screen, waitFor } from "@testing-library/react";

import userEvent from "@testing-library/user-event";

import type { ReactNode } from "react";

import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChapterContent, ChapterSummary, WorkflowPayload } from "../../types";

import { I18nProvider } from "../../i18n/I18nProvider";

import { HitlFloatingDock } from "../hitl-panel/HitlFloatingDock";

import type { HitlChapterReviewPayload } from "../hitl-panel/HitlPanel";

import { ReviewShell, type ReviewShellProps } from "./ReviewShell";



// AgentOutputView calls scrollIntoView on mount; jsdom does not implement it.

// Stub before any test renders the logs drawer.

if (typeof window !== "undefined") {

  // eslint-disable-next-line @typescript-eslint/no-explicit-any

  (window as any).HTMLElement.prototype.scrollIntoView = vi.fn();

}



// Replace the lazy-loaded TipTap-backed editor inside ChapterReviewGate with

// a contenteditable surrogate so we don't depend on ProseMirror in jsdom.

vi.mock("../chapter-review/ChapterReviewEditor", () => ({

  default: ({

    initialDoc,

    busy,

    onChange,

  }: {

    initialDoc: string;

    busy?: boolean;

    onChange: (text: string) => void;

  }) => (

    <textarea

      data-testid="mock-editor"

      defaultValue={initialDoc}

      disabled={busy}

      onChange={(e) => onChange(e.target.value)}

    />

  ),

}));



const noopAsync = () => Promise.resolve(undefined);



const hitlDockHandlers = {

  onDecision: noopAsync,

  onOutlineEdit: noopAsync,

  onStateInjection: noopAsync,

  onDraftEdit: noopAsync,

  onDirectorPatch: noopAsync,

  onExtractionRemap: noopAsync,

  onAnchorResolution: noopAsync,

  onContextPrune: noopAsync,

};



const chapterReviewDockHandlers = {

  onApprove: noopAsync,

  onAbandon: noopAsync,

  onRerun: noopAsync,

};



function makeChapters(): ChapterSummary[] {

  return [

    {

      chapter_id: 1,

      chapter_key: "ch1",

      title: "Opening",

      status: "completed",

    } as ChapterSummary,

    {

      chapter_id: 2,

      chapter_key: "ch2",

      title: "Confrontation",

      status: "pending",

    } as ChapterSummary,

  ];

}



function makeChapterContent(): ChapterContent {

  return {

    chapter_id: 1,

    title: "Opening",

    content: "Once upon a time…",

    status: "completed",

  } as ChapterContent;

}



function makeWorkflow(

  overrides: { run?: Partial<WorkflowPayload["run"]>; state?: Record<string, unknown> } = {},

): WorkflowPayload {

  return {

    run: {

      run_id: "run-1",

      story_id: "story-1",

      chapter_id: 2,

      status: "RUNNING",

      requires_hitl: false,

      hitl_reason: "",

      hitl_decision_mode: "NONE",

      ...overrides.run,

    },

    state: { workflow_status: "RUNNING", ...overrides.state },

    steps: [],

  } as unknown as WorkflowPayload;

}



function buildShellProps(overrides: Partial<ReviewShellProps> = {}): ReviewShellProps {

  return {

    storyId: "story-1",

    chapterId: 1,

    chapters: makeChapters(),

    selectedChapter: makeChapterContent(),

    outputLanguage: "zh-Hant",

    busy: false,

    workflow: makeWorkflow(),

    setWorkflow: vi.fn(),

    workflowHitlActive: false,

    onSelectChapter: noopAsync,

    onDownloadChapter: noopAsync,

    onDownloadAllCompletedZip: noopAsync,

    completedChaptersZipCount: 1,

    onBackToChapterRun: noopAsync,

    ...overrides,

  };

}



function hitlChapterReviewPayload(

  active: boolean,

  workflow: WorkflowPayload | null,

): HitlChapterReviewPayload | null {

  return active && workflow

    ? {

        draft: String(workflow?.state?.current_draft ?? workflow?.state?.best_draft_content ?? ""),

        readerScore:

          typeof workflow?.state?.last_reader_score === "number"

            ? Number(workflow.state.last_reader_score)

            : null,

        onApprove: chapterReviewDockHandlers.onApprove,

        onAbandon: chapterReviewDockHandlers.onAbandon,

        onRerun: chapterReviewDockHandlers.onRerun,

      }

    : null;

}



function renderDockedWorkspace(node: ReactNode) {

  const router = createMemoryRouter([{ path: "*", element: <>{node}</> }], {

    initialEntries: ["/review"],

  });

  return render(

    <I18nProvider>

      <RouterProvider router={router} />

    </I18nProvider>,

  );

}



describe("ReviewShell", () => {

  beforeEach(() => {

    window.localStorage.clear();

    window.sessionStorage.clear();

    window.localStorage.setItem("nb.ui.locale", "zh-Hant");

  });



  // Scenario (a): idle reading — dock mounts from App glue in production; tests pair it explicitly.

  it("idle reading: beacon shows 'idle', dock is collapsed to a candle pill", () => {

    const shell = buildShellProps();

    renderDockedWorkspace(

      <>

        <ReviewShell {...shell} />

        <HitlFloatingDock

          workflow={shell.workflow}

          workflowHitlActive={shell.workflowHitlActive}

          graph={null}

          storyId={shell.storyId}

          busy={shell.busy}

          workflowError=""

          chapterReview={hitlChapterReviewPayload(false, shell.workflow)}

          {...hitlDockHandlers}

        />

      </>,

    );

    const beacon = screen.getByTestId("hitl-beacon");

    expect(beacon.getAttribute("data-state")).toBe("idle");

    expect(screen.getByTestId("hitl-dock-pill")).toBeInTheDocument();

    expect(screen.queryByTestId("hitl-floating-dock")).not.toBeInTheDocument();

  });



  // Scenario (b): workflow fires HITL mid-run

  it("HITL active: beacon shows 'awaiting' and dock auto-expands", async () => {

    const wf = makeWorkflow({

      run: {

        status: "WAITING_HITL",

        requires_hitl: true,

        hitl_reason: "Plan_Loop_Exceeded",

      },

      state: {

        workflow_status: "WAITING_HITL",

        pending_hitl_options: [{ id: "opt_a", label: "Option A" }],

        resume_from: "planner",

      },

    });

    renderDockedWorkspace(

      <>

        <ReviewShell

          {...buildShellProps({

            workflow: wf,

            workflowHitlActive: true,

          })}

        />

        <HitlFloatingDock

          workflow={wf}

          workflowHitlActive

          graph={null}

          storyId="story-1"

          busy={false}

          workflowError=""

          chapterReview={hitlChapterReviewPayload(false, wf)}

          {...hitlDockHandlers}

        />

      </>,

    );

    const beacon = screen.getByTestId("hitl-beacon");

    expect(beacon.getAttribute("data-state")).toBe("awaiting");

    await waitFor(() => expect(screen.getByTestId("hitl-floating-dock")).toBeInTheDocument());

  });



  // Scenario (c): chapter review HITL surfaces inside the dock panel

  it("chapterReviewActive: ChapterReviewGate renders inside the HITL dock", () => {

    const wf = makeWorkflow({

      run: {

        status: "WAITING_HITL",

        requires_hitl: true,

        hitl_reason: "Chapter_Draft_Review",

      },

      state: {

        workflow_status: "WAITING_HITL",

        current_draft: "Reviewer sees this draft body.",

      },

    });

    renderDockedWorkspace(

      <>

        <ReviewShell {...buildShellProps({ workflow: wf, workflowHitlActive: true })} />

        <HitlFloatingDock

          workflow={wf}

          workflowHitlActive

          graph={null}

          storyId="story-1"

          busy={false}

          workflowError=""

          chapterReview={hitlChapterReviewPayload(true, wf)}

          {...hitlDockHandlers}

        />

      </>,

    );

    expect(screen.getByTestId("chapter-review-gate")).toBeInTheDocument();

  });



  // Scenario (e): mobile fallback — dock sheet variant.

  it("small viewport: dock renders in bottom-sheet variant", async () => {

    const originalMM = window.matchMedia;

    window.matchMedia = ((query: string) => ({

      matches: false,

      media: query,

      onchange: null,

      addEventListener: vi.fn(),

      removeEventListener: vi.fn(),

      addListener: vi.fn(),

      removeListener: vi.fn(),

      dispatchEvent: vi.fn(),

    })) as unknown as typeof window.matchMedia;



    try {

      const wf = makeWorkflow({

        run: {

          status: "WAITING_HITL",

          requires_hitl: true,

          hitl_reason: "Plan_Loop_Exceeded",

        },

        state: {

          workflow_status: "WAITING_HITL",

          pending_hitl_options: [{ id: "opt_a", label: "Option A" }],

          resume_from: "planner",

        },

      });



      renderDockedWorkspace(

        <>

          <ReviewShell {...buildShellProps({ workflow: wf, workflowHitlActive: true })} />

          <HitlFloatingDock

            workflow={wf}

            workflowHitlActive

            graph={null}

            storyId="story-1"

            busy={false}

            workflowError=""

            chapterReview={hitlChapterReviewPayload(false, wf)}

            {...hitlDockHandlers}

          />

        </>,

      );

      const dock = await screen.findByTestId("hitl-floating-dock");

      expect(dock.getAttribute("data-variant")).toBe("sheet");

    } finally {

      window.matchMedia = originalMM;

    }

  });



  it("logs drawer is initially closed and opens via the ribbon toggle", async () => {

    const user = userEvent.setup();

    const shell = buildShellProps();

    renderDockedWorkspace(

      <>

        <ReviewShell {...shell} />

        <HitlFloatingDock

          workflow={shell.workflow}

          workflowHitlActive={shell.workflowHitlActive}

          graph={null}

          storyId={shell.storyId}

          busy={shell.busy}

          workflowError=""

          chapterReview={hitlChapterReviewPayload(false, shell.workflow)}

          {...hitlDockHandlers}

        />

      </>,

    );

    expect(screen.queryByTestId("agent-logs-drawer-close")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("review-ribbon-logs-toggle"));

    await waitFor(() =>

      expect(screen.getByTestId("agent-logs-drawer-close")).toBeInTheDocument(),

    );

  });

});

