import { createContext, useCallback, useMemo, useState, type ReactNode } from "react";
import { getInitialLocale, isLocale, LOCALE_STORAGE_KEY } from "./locale";
import { MESSAGES } from "./messages";
import type { Locale } from "./types";

type Params = Record<string, string | number>;

export type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, fallback?: string, params?: Params) => string;
};

export const I18nContext = createContext<I18nContextValue | null>(null);

function interpolate(input: string, params?: Params): string {
  if (!params) return input;
  return input.replace(/\{(\w+)\}/g, (_m, token: string) => String(params[token] ?? `{${token}}`));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => getInitialLocale());

  const setLocale = useCallback((next: Locale) => {
    if (!isLocale(next)) return;
    setLocaleState(next);
    localStorage.setItem(LOCALE_STORAGE_KEY, next);
  }, []);

  const t = useCallback(
    (key: string, fallback = key, params?: Params): string => {
      const dict = MESSAGES[locale];
      const value = dict[key] ?? MESSAGES["zh-Hant"][key] ?? fallback;
      return interpolate(value, params);
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
