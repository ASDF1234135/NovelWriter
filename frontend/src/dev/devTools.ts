/** True when `VITE_ENABLE_DEV_TOOLS=1` or `true` (local preview / QA only). */
export function isDevToolsEnabled(): boolean {
  const flag = String(import.meta.env.VITE_ENABLE_DEV_TOOLS ?? "").trim();
  return flag === "1" || flag.toLowerCase() === "true";
}
