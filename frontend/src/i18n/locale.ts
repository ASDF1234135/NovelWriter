import type { Locale } from "./types";

export const LOCALE_STORAGE_KEY = "nb.ui.locale";

const NAV_MAP: Array<{ prefix: string; locale: Locale }> = [
  { prefix: "zh-tw", locale: "zh-Hant" },
  { prefix: "zh-hk", locale: "zh-Hant" },
  { prefix: "zh-mo", locale: "zh-Hant" },
  { prefix: "zh-hant", locale: "zh-Hant" },
  { prefix: "zh-cn", locale: "zh-Hans" },
  { prefix: "zh-sg", locale: "zh-Hans" },
  { prefix: "zh-hans", locale: "zh-Hans" },
  { prefix: "en", locale: "en" },
];

export function isLocale(value: unknown): value is Locale {
  return value === "zh-Hant" || value === "zh-Hans" || value === "en";
}

export function detectLocaleFromNavigator(): Locale {
  const lang = String(navigator.language ?? "").trim().toLowerCase();
  for (const row of NAV_MAP) {
    if (lang.startsWith(row.prefix)) return row.locale;
  }
  if (lang.startsWith("zh")) return "zh-Hant";
  return "zh-Hant";
}

export function getInitialLocale(): Locale {
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
  if (isLocale(stored)) return stored;
  return detectLocaleFromNavigator();
}
