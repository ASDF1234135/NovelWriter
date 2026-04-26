import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { MacroPlanPanel } from "./MacroPlanPanel";
import { putMacroPlan } from "../../api";

function renderMacro(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

vi.mock("../../api", () => ({
  putMacroPlan: vi.fn().mockResolvedValue({
    story_id: "s1",
    bible: {},
    volumes: [],
    anchors: [],
    anchor_nodes: [],
    cast: [],
    cast_seed: [],
    protagonist_character_id: "",
    compiled: true,
  }),
}));

describe("MacroPlanPanel", () => {
  it("shows read mode by default and enters bible edit mode", async () => {
    renderMacro(
      <MacroPlanPanel
        macroData={{
          story_id: "s1",
          bible: { story_genre: "奇幻", tone: "沉穩", world_rules: ["rule"], factions: ["f"], themes: ["t"], writing_note: ["w"] },
          volumes: [{ volume_id: "v1", title: "卷一", summary: "摘要", chapter_start: 1, chapter_end: 3 }],
          anchors: [{ anchor_id: "a1", volume_id: "v1", title: "錨點", description: "描述", chapter_target: 2, target_state: {}, priority: 2 }],
          anchor_nodes: [
            {
              id: "n1",
              storyline_ids: ["s_main"],
              volume_id: "v1",
              node_kind: "NORMAL",
              title: "N1",
              description: "D1",
              depends_on: [],
              status: "UNLOCKED",
            },
          ],
          cast: [{ node_id: "char_1", canonical_name: "主角", role: "protagonist" }],
        }}
        storyId="s1"
        configurationLocked={false}
        onMacroDataUpdate={vi.fn()}
        onBusy={vi.fn()}
        onError={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "編輯世界觀總表" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "儲存" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "編輯世界觀總表" }));
    expect(screen.getByRole("button", { name: "儲存" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("奇幻")).toBeInTheDocument();
  });

  it("shows validation error when required bible fields are empty", async () => {
    renderMacro(
      <MacroPlanPanel
        macroData={{
          story_id: "s1",
          bible: {},
          volumes: [{ volume_id: "v1", title: "卷一", summary: "摘要", chapter_start: 1, chapter_end: 3 }],
          anchors: [
            {
              anchor_id: "a1",
              volume_id: "v1",
              title: "錨點",
              description: "描述",
              chapter_target: 2,
              target_state: { goal: "前進" },
              priority: 1,
            },
          ],
          anchor_nodes: [
            {
              id: "n1",
              storyline_ids: ["s_main"],
              volume_id: "v1",
              node_kind: "NORMAL",
              title: "N1",
              description: "D1",
              depends_on: [],
              status: "UNLOCKED",
            },
          ],
          cast: [{ node_id: "char_1", canonical_name: "主角", role: "protagonist" }],
        }}
        storyId="s1"
        configurationLocked={false}
        onMacroDataUpdate={vi.fn()}
        onBusy={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "編輯世界觀總表" }));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect(await screen.findByText(/請填寫「故事類型」/)).toBeInTheDocument();
  });

  it("saves with extra list and optional empty target_state", async () => {
    const onMacroDataUpdate = vi.fn();
    renderMacro(
      <MacroPlanPanel
        macroData={{
          story_id: "s1",
          bible: { story_genre: "科幻", tone: "冷峻", world_rules: ["rule"], factions: ["f"], themes: ["t"], writing_note: ["w"], tags: ["A", "B"] },
          volumes: [{ volume_id: "v1", title: "卷一", summary: "摘要", chapter_start: 1, chapter_end: 3, target_volume_words: 12000 }],
          anchors: [{ anchor_id: "a1", volume_id: "v1", title: "錨點", description: "描述", chapter_target: 2, target_state: { ready: true }, priority: 2 }],
          anchor_nodes: [
            {
              id: "n1",
              storyline_ids: ["s_main"],
              volume_id: "v1",
              node_kind: "NORMAL",
              title: "N1",
              description: "D1",
              depends_on: [],
              status: "UNLOCKED",
            },
          ],
          cast: [{ node_id: "char_1", canonical_name: "主角", role: "protagonist" }],
        }}
        storyId="s1"
        configurationLocked={false}
        onMacroDataUpdate={onMacroDataUpdate}
        onBusy={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "編輯世界觀總表" }));
    const toneInput = screen.getByDisplayValue("冷峻");
    fireEvent.change(toneInput, { target: { value: "冷峻且克制" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await screen.findByRole("button", { name: "編輯世界觀總表" });

    expect(putMacroPlan).toHaveBeenCalled();
    const calls = vi.mocked(putMacroPlan).mock.calls;
    const payload = calls[calls.length - 1]?.[1];
    expect(payload?.bible.genre).toBe("科幻");
    expect((payload?.bible as { extra?: { tags?: string[] } }).extra?.tags).toEqual(["A", "B"]);
    expect(Array.isArray(payload?.anchor_nodes)).toBe(true);
  });

  it("shows volume id as non-input readout in volume edit mode", () => {
    renderMacro(
      <MacroPlanPanel
        macroData={{
          story_id: "s1",
          bible: { genre: "奇幻", tone: "沉穩", world_rules: ["rule"], factions: ["f"], themes: ["t"], writing_note: ["w"] },
          volumes: [{ volume_id: "v1", title: "卷一", summary: "摘要", chapter_start: 1, chapter_end: 3 }],
          anchors: [{ anchor_id: "a1", volume_id: "v1", title: "錨點", description: "描述", chapter_target: 2, target_state: {}, priority: 1 }],
          anchor_nodes: [
            {
              id: "n1",
              storyline_ids: ["s_main"],
              volume_id: "v1",
              node_kind: "NORMAL",
              title: "N1",
              description: "D1",
              depends_on: [],
              status: "UNLOCKED",
            },
          ],
          cast: [{ node_id: "char_1", canonical_name: "主角", role: "protagonist" }],
        }}
        storyId="s1"
        configurationLocked={false}
        onMacroDataUpdate={vi.fn()}
        onBusy={vi.fn()}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "分卷" }));
    fireEvent.click(screen.getByRole("button", { name: "編輯" }));
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /volume-id/ })).not.toBeInTheDocument();
  });

  it("does not expose anchors tab entry anymore", () => {
    renderMacro(
      <MacroPlanPanel
        macroData={{
          story_id: "s1",
          bible: { genre: "奇幻", tone: "沉穩", world_rules: ["rule"], factions: ["f"], themes: ["t"], writing_note: ["w"] },
          volumes: [{ volume_id: "v1", title: "卷一", summary: "摘要", chapter_start: 1, chapter_end: 3 }],
          anchors: [{ anchor_id: "a1", volume_id: "v1", title: "錨點", description: "描述", chapter_target: 2, target_state: {}, priority: 1 }],
          anchor_nodes: [
            {
              id: "n1",
              storyline_ids: ["s_main"],
              volume_id: "v1",
              node_kind: "NORMAL",
              title: "N1",
              description: "D1",
              depends_on: [],
              status: "UNLOCKED",
            },
          ],
          cast: [{ node_id: "char_1", canonical_name: "主角", role: "protagonist" }],
        }}
        storyId="s1"
        configurationLocked={false}
        onMacroDataUpdate={vi.fn()}
        onBusy={vi.fn()}
        onError={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "情節節點" })).not.toBeInTheDocument();
  });
});
