import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

/** Align runtimeLocale + I18n with Traditional Chinese expectations in tests. */
beforeEach(() => {
  window.localStorage.setItem("nb.ui.locale", "zh-Hant");
});
