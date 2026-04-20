import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StorySetupForm } from "./StorySetupForm";

describe("StorySetupForm", () => {
  it("removes cast seed UI and submits cast_seed as empty array", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <StorySetupForm
        onSubmit={onSubmit}
        resetKey="test"
      />,
    );

    expect(screen.queryByText("核心角色種子（選填）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /建立故事/ }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        cast_seed: [],
        output_language: "zh-Hant",
      }),
    );
  });
});

