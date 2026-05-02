import { NB_ERR_SSE_DISCONNECTED } from "../apiErrorCodes";
import type { I18nContextValue } from "./I18nProvider";

type TFn = I18nContextValue["t"];

/** Maps fixed API/client error strings to i18n keys. Backend `detail` text passes through unchanged. */
const KNOWN_MESSAGE_TO_KEY: Record<string, string> = {
  [NB_ERR_SSE_DISCONNECTED]: "errors.sseDisconnected",
  "與伺服器的即時連線中斷，請重新整理或再試一次": "errors.sseDisconnected",
  "Macro compile was not accepted": "errors.macroCompileNotAccepted",
  "Macro compile failed": "errors.macroCompileFailedGeneric",
  "Macro compile timed out waiting for completion": "errors.macroCompileTimeout",
  "Request failed": "errors.requestFailed",
  "Download failed": "errors.downloadFailed",
};

/**
 * If `message` matches a known client/API token, returns the translated string; otherwise returns `message`.
 */
export function localizeUserFacingError(message: string, t: TFn): string {
  const trimmed = String(message ?? "").trim();
  if (!trimmed) return "";
  const key = KNOWN_MESSAGE_TO_KEY[trimmed];
  if (key) return t(key);
  return trimmed;
}
