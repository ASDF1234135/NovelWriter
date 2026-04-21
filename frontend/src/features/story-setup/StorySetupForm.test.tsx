import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StorySetupForm } from "./StorySetupForm";
import { I18nProvider } from "../../i18n/I18nProvider";

describe("StorySetupForm", () => {
  it("removes cast seed UI and submits cast_seed as empty array", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <I18nProvider>
        <StorySetupForm
          onSubmit={onSubmit}
          resetKey="test"
        />
      </I18nProvider>,
    );

    expect(screen.queryByText("核心角色種子（選填）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Create Story|建立故事|创建故事/ }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        cast_seed: [],
        output_language: expect.stringMatching(/zh-Hant|zh-Hans|en/),
      }),
    );
  });
});

