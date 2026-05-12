import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./app/App";
import "./index.css";
import { I18nProvider } from "./i18n/I18nProvider";
import { queryClient } from "./app/queryClient";

const router = createBrowserRouter([
  // Single catch-all route: App owns its own view switching based on pathname
  // (see pathToView in App.tsx). We use a data router (not BrowserRouter) so
  // useBlocker / useNavigation are available to ChapterReviewGate.
  { path: "*", element: <App /> },
]);

const rootElement = document.getElementById("root");
const isLocalDevHost =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname.endsWith(".local");

if (isLocalDevHost && "PerformanceObserver" in window) {
  let cls = 0;
  const clsObserver = new PerformanceObserver((entryList) => {
    for (const entry of entryList.getEntries()) {
      const shift = entry as PerformanceEntry & { hadRecentInput?: boolean; value?: number };
      if (shift.hadRecentInput) continue;
      cls += shift.value ?? 0;
    }
  });
  clsObserver.observe({ type: "layout-shift", buffered: true });

  window.addEventListener("load", () => {
    const paints = performance
      .getEntriesByType("paint")
      .map((entry) => `${entry.name}:${entry.startTime.toFixed(1)}ms`)
      .join(", ");
    // Baseline metrics to compare before/after anti-flicker changes.
    console.info(`[perf-baseline] CLS=${cls.toFixed(4)} paints=[${paints}]`);
    clsObserver.disconnect();
  });
}

ReactDOM.createRoot(rootElement!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);

requestAnimationFrame(() => {
  rootElement?.classList.add("app-ready");
});
