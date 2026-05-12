import { render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createMemoryRouter,
  RouterProvider,
  useNavigate,
  useLocation,
} from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

function mountWithDataRouter(node: ReactNode, initialEntries: string[] = ["/review"]) {
  const router = createMemoryRouter(
    [
      { path: "/review", element: <>{node}</> },
      { path: "/setup", element: <>{node}</> },
    ],
    { initialEntries },
  );
  return render(<RouterProvider router={router} />);
}

function wrapperFactory(initialEntries: string[] = ["/review"]) {
  // eslint-disable-next-line react/display-name
  return ({ children }: { children: ReactNode }) => {
    const router = createMemoryRouter(
      [
        { path: "/review", element: <>{children}</> },
        { path: "/setup", element: <>{children}</> },
      ],
      { initialEntries },
    );
    return <RouterProvider router={router} />;
  };
}

describe("useUnsavedChangesGuard", () => {
  // jsdom's `Event` exposes `returnValue` as a boolean (legacy cancel flag),
  // so we can't observe the string set inside the handler directly. Instead we
  // spy on add/removeEventListener to observe registration lifecycle, and we
  // invoke the handler manually to assert the side effects it performs.
  let addSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    addSpy = vi.spyOn(window, "addEventListener");
    removeSpy = vi.spyOn(window, "removeEventListener");
  });

  afterEach(() => {
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  function getBeforeUnloadHandler(): EventListener | undefined {
    const beforeunloadAdds = addSpy.mock.calls.filter(([type]) => type === "beforeunload");
    const beforeunloadRemoves = removeSpy.mock.calls.filter(([type]) => type === "beforeunload");
    // Latest add not yet removed.
    for (let i = beforeunloadAdds.length - 1; i >= 0; i -= 1) {
      const handler = beforeunloadAdds[i][1] as EventListener;
      const removed = beforeunloadRemoves.some(([, h]) => h === handler);
      if (!removed) return handler;
    }
    return undefined;
  }

  it("attaches a beforeunload handler that preventDefaults and writes returnValue when active", () => {
    renderHook(() => useUnsavedChangesGuard(true, "leaving will discard your edits"), {
      wrapper: wrapperFactory(),
    });

    expect(
      addSpy.mock.calls.some(([type]) => type === "beforeunload"),
    ).toBe(true);

    const handler = getBeforeUnloadHandler();
    expect(handler).toBeTypeOf("function");

    // Build a vanilla object so we can observe returnValue without jsdom's
    // boolean coercion on the legacy Event.returnValue setter.
    const fakeEvent = {
      defaultPrevented: false,
      returnValue: undefined as unknown,
      preventDefault() {
        this.defaultPrevented = true;
      },
    };
    const result = (handler as (e: typeof fakeEvent) => unknown)(fakeEvent);
    expect(fakeEvent.defaultPrevented).toBe(true);
    expect(fakeEvent.returnValue).toBe("leaving will discard your edits");
    expect(result).toBe("leaving will discard your edits");
  });

  it("removes the beforeunload handler after going inactive", () => {
    const { rerender } = renderHook(
      ({ active }: { active: boolean }) => useUnsavedChangesGuard(active, "msg"),
      { wrapper: wrapperFactory(), initialProps: { active: true } },
    );

    const handler = getBeforeUnloadHandler();
    expect(handler).toBeTypeOf("function");

    rerender({ active: false });

    expect(
      removeSpy.mock.calls.some(([type, h]) => type === "beforeunload" && h === handler),
    ).toBe(true);
    expect(getBeforeUnloadHandler()).toBeUndefined();
  });

  it("removes the beforeunload handler on unmount", () => {
    const { unmount } = renderHook(() => useUnsavedChangesGuard(true, "msg"), {
      wrapper: wrapperFactory(),
    });

    const handler = getBeforeUnloadHandler();
    expect(handler).toBeTypeOf("function");

    unmount();

    expect(
      removeSpy.mock.calls.some(([type, h]) => type === "beforeunload" && h === handler),
    ).toBe(true);
    expect(getBeforeUnloadHandler()).toBeUndefined();
  });

  it("blocks in-app navigation when active and can be reset to stay", async () => {
    function Harness() {
      const blocker = useUnsavedChangesGuard(true, "msg");
      const navigate = useNavigate();
      const location = useLocation();
      return (
        <div>
          <span data-testid="path">{location.pathname}</span>
          <span data-testid="state">{blocker.state}</span>
          <button onClick={() => navigate("/setup")}>go-setup</button>
          {blocker.state === "blocked" ? (
            <>
              <button onClick={() => blocker.proceed?.()}>leave</button>
              <button onClick={() => blocker.reset?.()}>stay</button>
            </>
          ) : null}
        </div>
      );
    }

    const user = userEvent.setup();
    mountWithDataRouter(<Harness />);

    expect(screen.getByTestId("path").textContent).toBe("/review");
    expect(screen.getByTestId("state").textContent).toBe("unblocked");

    await user.click(screen.getByText("go-setup"));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("blocked"));
    expect(screen.getByTestId("path").textContent).toBe("/review");

    await user.click(screen.getByText("stay"));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("unblocked"));
    expect(screen.getByTestId("path").textContent).toBe("/review");
  });

  it("allows navigation to proceed when the user confirms leaving", async () => {
    function Harness() {
      const blocker = useUnsavedChangesGuard(true, "msg");
      const navigate = useNavigate();
      const location = useLocation();
      return (
        <div>
          <span data-testid="path">{location.pathname}</span>
          <span data-testid="state">{blocker.state}</span>
          <button onClick={() => navigate("/setup")}>go-setup</button>
          {blocker.state === "blocked" ? (
            <button onClick={() => blocker.proceed?.()}>leave</button>
          ) : null}
        </div>
      );
    }

    const user = userEvent.setup();
    mountWithDataRouter(<Harness />);

    await user.click(screen.getByText("go-setup"));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("blocked"));

    await user.click(screen.getByText("leave"));
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("/setup"));
  });

  it("does not block navigation when inactive", async () => {
    function Harness() {
      const blocker = useUnsavedChangesGuard(false, "msg");
      const navigate = useNavigate();
      const location = useLocation();
      return (
        <div>
          <span data-testid="path">{location.pathname}</span>
          <span data-testid="state">{blocker.state}</span>
          <button onClick={() => navigate("/setup")}>go-setup</button>
        </div>
      );
    }

    const user = userEvent.setup();
    mountWithDataRouter(<Harness />);

    await user.click(screen.getByText("go-setup"));
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("/setup"));
    expect(screen.getByTestId("state").textContent).toBe("unblocked");
  });

  it("replaces (does not stack) the listener when the message changes", () => {
    const { rerender } = renderHook(
      ({ msg }: { msg: string }) => useUnsavedChangesGuard(true, msg),
      { wrapper: wrapperFactory(), initialProps: { msg: "first" } },
    );
    const firstHandler = getBeforeUnloadHandler();
    expect(firstHandler).toBeTypeOf("function");

    rerender({ msg: "second" });

    // The previous handler must have been removed and a fresh one installed
    // before any stale "first"-bound handler can run.
    expect(
      removeSpy.mock.calls.some(([type, h]) => type === "beforeunload" && h === firstHandler),
    ).toBe(true);
    const newHandler = getBeforeUnloadHandler();
    expect(newHandler).toBeTypeOf("function");
    expect(newHandler).not.toBe(firstHandler);

    const fakeEvent = {
      defaultPrevented: false,
      returnValue: undefined as unknown,
      preventDefault() {
        this.defaultPrevented = true;
      },
    };
    (newHandler as (e: typeof fakeEvent) => unknown)?.(fakeEvent);
    expect(fakeEvent.returnValue).toBe("second");
  });
});
