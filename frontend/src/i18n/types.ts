export const SUPPORTED_LOCALES = ["zh-Hant", "zh-Hans", "en"] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export type Messages = Record<string, string>;
