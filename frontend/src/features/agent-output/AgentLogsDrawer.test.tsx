import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import { AgentLogsDrawer } from "./AgentLogsDrawer";

function renderDrawer(node: React.ReactElement) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("AgentLogsDrawer", () => {
  it("does not render anything when closed", () => {
    const { container } = renderDrawer(
      <AgentLogsDrawer open={false} onClose={vi.fn()} workflow={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the drawer dialog when open", () => {
    renderDrawer(<AgentLogsDrawer open onClose={vi.fn()} workflow={null} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agent-logs-drawer-close")).toBeInTheDocument();
  });

  it("Esc closes the drawer", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDrawer(<AgentLogsDrawer open onClose={onClose} workflow={null} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("close button closes the drawer", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDrawer(<AgentLogsDrawer open onClose={onClose} workflow={null} />);
    await user.click(screen.getByTestId("agent-logs-drawer-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
