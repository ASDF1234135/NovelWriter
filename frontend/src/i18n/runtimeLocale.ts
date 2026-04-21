import { detectLocaleFromNavigator, isLocale, LOCALE_STORAGE_KEY } from "./locale";
import type { Locale } from "./types";

export function getRuntimeLocale(): Locale {
  if (typeof window === "undefined") return "zh-Hant";
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (isLocale(stored)) return stored;
  return detectLocaleFromNavigator();
}
