/** Aligns with backend `NodeType` enum; unknown types use default. */

export type NodeTypeStyle = { fill: string; stroke: string };

export const NODE_TYPE_STYLES: Record<string, NodeTypeStyle> = {
  CHARACTER: { fill: "#5b8def", stroke: "#9ec5ff" },
  PERSONA: { fill: "#a855f7", stroke: "#d8b4fe" },
  EPOCH: { fill: "#f59e0b", stroke: "#fcd34d" },
  LOCATION: { fill: "#34d399", stroke: "#a7f3d0" },
  ITEM: { fill: "#f472b6", stroke: "#fbcfe8" },
  EVENT: { fill: "#f87171", stroke: "#fecaca" },
  CONCEPT: { fill: "#94a3b8", stroke: "#e2e8f0" },
};

const DEFAULT_STYLE: NodeTypeStyle = { fill: "#64748b", stroke: "#cbd5e1" };

export function styleForNodeType(nodeType: string): NodeTypeStyle {
  const key = String(nodeType || "").trim().toUpperCase();
  return NODE_TYPE_STYLES[key] ?? DEFAULT_STYLE;
}

/** Stable order for legend (known types first, then any extras from data). */
export const LEGEND_NODE_TYPES = [
  "CHARACTER",
  "PERSONA",
  "EPOCH",
  "LOCATION",
  "ITEM",
  "EVENT",
  "CONCEPT",
] as const;
