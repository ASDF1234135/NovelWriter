import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MACRO_COMPILE_POLL_MS, macroCompile, waitForMacroCompileCompletion } from "./api";

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response;
}

describe("waitForMacroCompileCompletion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls until SUCCEEDED and returns macro data", async () => {
    const snapRunning = {
      story_id: "s1",
      macro_compile_status: "RUNNING",
      bible: {},
      macro_author_notes: "",
      cast_seed: [],
      volumes: [],
      cast: [],
      protagonist_character_id: "",
      storylines: [],
      anchor_nodes: [],
      macro_topology_mode: "fixed_fishbone",
      topology_locked: true,
      has_completed_chapter: false,
      macro_edit_locked: false,
      compiled: false,
    };
    const snapDone = {
      ...snapRunning,
      macro_compile_status: "SUCCEEDED",
      volumes: [{ volume_id: "v1", title: "V1", chapter_unit_words: 1000, chapter_count: 1 }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(snapRunning))
      .mockResolvedValueOnce(jsonResponse(snapDone));
    globalThis.fetch = fetchMock;

    const p = waitForMacroCompileCompletion("s1");
    await vi.advanceTimersByTimeAsync(MACRO_COMPILE_POLL_MS);
    const result = await p;
    expect(result.story_id).toBe("s1");
    expect(result.volumes).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/stories/s1/macro-snapshot");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws on FAILED", async () => {
    const snap = {
      story_id: "s1",
      macro_compile_status: "FAILED",
      macro_compile_error: "bad",
      bible: {},
      macro_author_notes: "",
      cast_seed: [],
      volumes: [],
      cast: [],
      protagonist_character_id: "",
      storylines: [],
      anchor_nodes: [],
      macro_topology_mode: "fixed_fishbone",
      topology_locked: true,
      has_completed_chapter: false,
      macro_edit_locked: false,
      compiled: false,
    };
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse(snap));
    await expect(waitForMacroCompileCompletion("s1")).rejects.toThrow("bad");
  });
});

describe("macroCompile POST 409", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("falls back to wait when compile already running", async () => {
    const snapDone = {
      story_id: "s2",
      macro_compile_status: "SUCCEEDED",
      bible: {},
      macro_author_notes: "",
      cast_seed: [],
      volumes: [],
      cast: [],
      protagonist_character_id: "",
      storylines: [],
      anchor_nodes: [],
      macro_topology_mode: "fixed_fishbone",
      topology_locked: true,
      has_completed_chapter: false,
      macro_edit_locked: false,
      compiled: true,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/macro-compile") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({}, false, 409));
      }
      return Promise.resolve(jsonResponse(snapDone));
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await macroCompile("s2");
    expect(result.story_id).toBe("s2");
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/macro-compile"))).toBe(true);
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/macro-snapshot"))).toBe(true);
  });
});
