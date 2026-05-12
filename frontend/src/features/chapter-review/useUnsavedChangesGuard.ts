import { useEffect, useRef } from "react";
import { useBlocker, type Blocker } from "react-router-dom";

/**
 * Multi-layered defense against accidental data loss while the chapter-review
 * draft has unsubmitted edits:
 *
 *   1. **Browser layer** (F5, close tab, back button, OS close): native
 *      `beforeunload` listener. Most modern browsers ignore the custom string
 *      but still need `event.preventDefault()` + `returnValue = message` to
 *      trigger the prompt.
 *   2. **SPA layer** (in-app `react-router` navigation): `useBlocker` returns a
 *      blocker with `state === "blocked"`, which the consuming component is
 *      expected to surface as a modal (call `proceed()` to leave or `reset()`
 *      to stay).
 *
 * The `active` flag should track `edited && !submitting`: while submitting the
 * pending API call we expect the router to navigate away on success, so the
 * guard must be off to avoid self-blocking.
 */
export function useUnsavedChangesGuard(active: boolean, message: string): Blocker {
  // Snapshot `active` into a ref so the blocker callback (recreated by router
  // internals) always reads the freshest value without re-subscribing.
  const activeRef = useRef(active);
  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Required by Chrome/Firefox; modern browsers display their own copy.
      event.returnValue = message;
      return message;
    };
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("beforeunload", handler);
    };
  }, [active, message]);

  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!activeRef.current) return false;
    return currentLocation.pathname !== nextLocation.pathname;
  });

  return blocker;
}
