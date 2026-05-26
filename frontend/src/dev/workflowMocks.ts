import type { GraphSnapshot, WorkflowPayload } from "../types";
import { buildHitlDevPayloadBySlug, HITL_DEV_MOCK_SLUGS } from "./hitlDevMocks";

export type WorkflowMockEntry = {
  workflow: WorkflowPayload;
  graph?: GraphSnapshot;
};

function entryForSlug(slug: string): WorkflowMockEntry | null {
  const built = buildHitlDevPayloadBySlug(slug, null);
  if (!built) return null;
  return { workflow: built.workflow, graph: built.graph };
}

/** Console helpers (`__NB_SET_WORKFLOW_MOCK`) — one slug per HITL reason. */
export const WORKFLOW_MOCKS: Record<string, WorkflowMockEntry> = Object.fromEntries(
  Object.keys(HITL_DEV_MOCK_SLUGS)
    .map((slug) => {
      const entry = entryForSlug(slug);
      return entry ? ([slug, entry] as const) : null;
    })
    .filter((row): row is [string, WorkflowMockEntry] => row != null),
);

