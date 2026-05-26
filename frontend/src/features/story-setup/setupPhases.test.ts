import { describe, expect, it } from "vitest";
import {
  autoChapterCount,
  autoVolumeCount,
  clampTotalWords,
  composeNotes,
  createSubplotEntry,
  decomposeNotes,
  getDefaultTotalWords,
  MAX_TOTAL_WORDS,
  MIN_TOTAL_WORDS,
  resolveVolumeCount,
  seedDefaultSubplots,
  subplotCountRange,
  suggestNextSubplotVolume,
  suggestSubplotCounts,
} from "./setupPhases";

describe("setupPhases", () => {
  it("treats legacy notes (no markers) as Phase 2 world content", () => {
    const decomposed = decomposeNotes("Some free-form notes about the world.");
    expect(decomposed.world).toBe("Some free-form notes about the world.");
    expect(decomposed.characters).toBe("");
    expect(decomposed.style).toBe("");
    expect(decomposed.volumeGoals).toEqual([]);
    expect(decomposed.subplots).toEqual([]);
    expect(decomposed.hasStructuredMarkers).toBe(false);
  });

  it("round-trips world / characters / style sections", () => {
    const composed = composeNotes(
      {
        world: "Ancient kingdom under siege.",
        characters: "Renegade knight; cunning princess.",
        style: "Cinematic prose with brisk dialogue.",
        volumeGoals: [],
        subplots: [],
        hasStructuredMarkers: true,
      },
      null,
    );
    const decomposed = decomposeNotes(composed);
    expect(decomposed.world).toBe("Ancient kingdom under siege.");
    expect(decomposed.characters).toBe("Renegade knight; cunning princess.");
    expect(decomposed.style).toBe("Cinematic prose with brisk dialogue.");
    expect(decomposed.hasStructuredMarkers).toBe(true);
  });

  it("round-trips volume goals and prunes empty + out-of-range entries", () => {
    const composed = composeNotes(
      {
        world: "",
        characters: "",
        style: "",
        volumeGoals: [
          { volume: 1, goal: "揭露案發現場" },
          { volume: 2, goal: "" }, // empty -> dropped
          { volume: 3, goal: "突破皇室封鎖" },
          { volume: 5, goal: "orphan beyond cap" }, // beyond cap -> dropped
        ],
        subplots: [],
        hasStructuredMarkers: true,
      },
      3,
    );

    expect(composed).toContain("[[VOLUME_GOALS]]");
    expect(composed).toContain("第 1 卷｜揭露案發現場");
    expect(composed).toContain("第 3 卷｜突破皇室封鎖");
    expect(composed).not.toContain("orphan beyond cap");

    const back = decomposeNotes(composed);
    expect(back.volumeGoals).toEqual([
      { volume: 1, goal: "揭露案發現場" },
      { volume: 3, goal: "突破皇室封鎖" },
    ]);
  });

  it("round-trips subplot entries grouped by tier (volume-less legacy form)", () => {
    const composed = composeNotes(
      {
        world: "",
        characters: "",
        style: "",
        volumeGoals: [],
        subplots: [
          createSubplotEntry("A", { title: "王城密謀", goal: "宰相秘密" }),
          createSubplotEntry("B", { title: "市井傳聞", goal: "流言扩散" }),
          createSubplotEntry("S", { title: "羈絆守護者", goal: "童年友人真實身份" }),
          // empty row dropped on compose
          createSubplotEntry("B", { title: "", goal: "" }),
        ],
        hasStructuredMarkers: true,
      },
      null,
    );

    expect(composed).toContain("[[SUBPLOTS]]");
    const subplotsSection = composed.split("[[SUBPLOTS]]")[1] ?? "";
    // Tier ordering: S, then A, then B
    expect(subplotsSection.indexOf("[S]")).toBeLessThan(subplotsSection.indexOf("[A]"));
    expect(subplotsSection.indexOf("[A]")).toBeLessThan(subplotsSection.indexOf("[B]"));
    // Without a pinned volume, A/B emit the legacy bare tier tag.
    expect(subplotsSection).toContain("[A]｜王城密謀");
    expect(subplotsSection).toContain("[B]｜市井傳聞");

    const back = decomposeNotes(composed);
    expect(back.subplots).toHaveLength(3);
    expect(
      back.subplots.map((s) => ({ tier: s.tier, title: s.title, goal: s.goal, volume: s.volume })),
    ).toEqual([
      { tier: "S", title: "羈絆守護者", goal: "童年友人真實身份", volume: null },
      { tier: "A", title: "王城密謀", goal: "宰相秘密", volume: null },
      { tier: "B", title: "市井傳聞", goal: "流言扩散", volume: null },
    ]);
  });

  it("emits and parses [A:N] / [B:N] volume tags for pinned A/B subplots", () => {
    const composed = composeNotes(
      {
        world: "",
        characters: "",
        style: "",
        volumeGoals: [],
        subplots: [
          createSubplotEntry("A", { title: "王城密謀", goal: "宰相秘密", volume: 2 }),
          createSubplotEntry("A", { title: "邊境告急", goal: "北方部族集結", volume: 3 }),
          createSubplotEntry("B", { title: "市井傳聞", goal: "流言扩散", volume: 1 }),
          // S never carries a volume even if one is supplied; coerced to null.
          createSubplotEntry("S", { title: "羈絆守護者", goal: "童年友人", volume: 99 }),
        ],
        hasStructuredMarkers: true,
      },
      null,
    );
    const subplotsSection = composed.split("[[SUBPLOTS]]")[1] ?? "";
    // S row drops the volume entirely; A/B carry their tag and are sorted by volume.
    expect(subplotsSection).toContain("[S]｜羈絆守護者");
    expect(subplotsSection).not.toMatch(/\[S:\d+\]/);
    expect(subplotsSection.indexOf("[A:2]｜王城密謀")).toBeGreaterThan(-1);
    expect(subplotsSection.indexOf("[A:2]")).toBeLessThan(subplotsSection.indexOf("[A:3]"));
    expect(subplotsSection).toContain("[B:1]｜市井傳聞");

    const back = decomposeNotes(composed);
    expect(
      back.subplots.map((s) => ({ tier: s.tier, title: s.title, volume: s.volume })),
    ).toEqual([
      { tier: "S", title: "羈絆守護者", volume: null },
      { tier: "A", title: "王城密謀", volume: 2 },
      { tier: "A", title: "邊境告急", volume: 3 },
      { tier: "B", title: "市井傳聞", volume: 1 },
    ]);
  });

  it("emits empty string when nothing meaningful is provided", () => {
    expect(
      composeNotes(
        {
          world: "",
          characters: "",
          style: "",
          volumeGoals: [],
          subplots: [],
          hasStructuredMarkers: true,
        },
        null,
      ),
    ).toBe("");
  });

  it("suggestSubplotCounts uses lower bound aligned with backend compile rules", () => {
    expect(suggestSubplotCounts(null)).toEqual({ S: 1, A: 1, B: 1 });
    expect(suggestSubplotCounts(3)).toEqual({ S: 1, A: 3, B: 3 });
    expect(suggestSubplotCounts(0)).toEqual({ S: 1, A: 1, B: 1 });
    expect(suggestSubplotCounts(50)).toEqual({ S: 1, A: 32, B: 32 });
  });

  it("subplotCountRange exposes per-tier min/max from compile rules", () => {
    expect(subplotCountRange("S", 4)).toEqual({ min: 1, max: 2 });
    expect(subplotCountRange("A", 4)).toEqual({ min: 4, max: 8 });
    expect(subplotCountRange("B", 4)).toEqual({ min: 4, max: 12 });
    expect(subplotCountRange("A", null)).toEqual({ min: 1, max: 2 });
  });

  it("suggestNextSubplotVolume balances new A/B rows across volumes and returns null for S", () => {
    const empty: ReturnType<typeof seedDefaultSubplots> = [];
    expect(suggestNextSubplotVolume("S", 4, empty)).toBeNull();
    expect(suggestNextSubplotVolume("A", 4, empty)).toBe(1);

    const skewed = [
      createSubplotEntry("A", { volume: 1 }),
      createSubplotEntry("A", { volume: 1 }),
      createSubplotEntry("A", { volume: 2 }),
    ];
    // vol3 (and vol4) are empty -> first empty volume wins.
    expect(suggestNextSubplotVolume("A", 4, skewed)).toBe(3);

    const fullPlate = [
      createSubplotEntry("B", { volume: 1 }),
      createSubplotEntry("B", { volume: 2 }),
      createSubplotEntry("B", { volume: 3 }),
    ];
    // Every volume already has one; first-with-the-fewest wins ties.
    expect(suggestNextSubplotVolume("B", 3, fullPlate)).toBe(1);
  });

  it("seedDefaultSubplots pre-seeds blank entries in tier order with per-volume binding", () => {
    const seeded = seedDefaultSubplots(2);
    const tiers = seeded.map((e) => e.tier);
    expect(tiers).toEqual(["S", "A", "A", "B", "B"]);
    expect(seeded.every((e) => e.id.startsWith("sp_"))).toBe(true);
    expect(seeded.every((e) => e.title === "" && e.goal === "")).toBe(true);
    // S has no volume binding; A/B are round-robin'd across the 2 volumes.
    expect(seeded.map((e) => e.volume)).toEqual([null, 1, 2, 1, 2]);
  });

  it("auto-derives volume count using language-specific word density", () => {
    expect(autoVolumeCount(100000, "zh-Hant")).toBe(4); // 100000 / 25000
    expect(autoVolumeCount(100000, "zh-Hans")).toBe(4);
    expect(autoVolumeCount(72000, "en")).toBe(4); // 72000 / 18000
    expect(autoVolumeCount(0, "en")).toBe(1);
    expect(autoVolumeCount(-50, "zh-Hant")).toBe(1);
  });

  it("auto-derives chapter count using per-chapter density", () => {
    expect(autoChapterCount(100000, "zh-Hant")).toBe(40); // 100000 / 2500
    expect(autoChapterCount(72000, "en")).toBe(40); // 72000 / 1800
    expect(autoChapterCount(0, "zh-Hans")).toBe(1);
  });

  it("getDefaultTotalWords exposes language baselines", () => {
    expect(getDefaultTotalWords("zh-Hant")).toBe(100000);
    expect(getDefaultTotalWords("zh-Hans")).toBe(100000);
    expect(getDefaultTotalWords("en")).toBe(72000);
  });

  it("resolveVolumeCount prefers manual override but falls back to auto", () => {
    expect(resolveVolumeCount(5, 200000, "zh-Hant")).toBe(5);
    expect(resolveVolumeCount(null, 200000, "zh-Hant")).toBe(8); // 200000 / 25000
    expect(resolveVolumeCount(0, 72000, "en")).toBe(4); // 0 = auto; 72000 / 18000
  });

  it("clampTotalWords keeps values within the supported 50k~1M range", () => {
    expect(MIN_TOTAL_WORDS).toBe(50_000);
    expect(MAX_TOTAL_WORDS).toBe(1_000_000);

    // Inside the range — passes through (with floor for sub-1 fractions).
    expect(clampTotalWords(80_000, "en")).toBe(80_000);
    expect(clampTotalWords(123_456.7, "zh-Hant")).toBe(123_456);

    // Below the floor — clamps up.
    expect(clampTotalWords(30_000, "zh-Hant")).toBe(50_000);
    expect(clampTotalWords(1, "en")).toBe(50_000);

    // Above the ceiling — clamps down.
    expect(clampTotalWords(2_500_000, "zh-Hans")).toBe(1_000_000);

    // Nonsensical inputs fall back to the language default.
    expect(clampTotalWords(0, "zh-Hant")).toBe(100_000);
    expect(clampTotalWords(-1, "en")).toBe(72_000);
    expect(clampTotalWords(Number.NaN, "zh-Hans")).toBe(100_000);
  });

  it("parsing tolerates ASCII pipe separators too", () => {
    const raw = `[[WORLD]]\nworld\n\n[[VOLUME_GOALS]]\nV1 | first goal\nVolume 2 | second goal\n\n[[SUBPLOTS]]\n[S] | spine | hold the line\n[A] | side | turn the tide\n[B:3] | quiet beat | sharpen the silence`;
    const back = decomposeNotes(raw);
    expect(back.volumeGoals).toEqual([
      { volume: 1, goal: "first goal" },
      { volume: 2, goal: "second goal" },
    ]);
    expect(
      back.subplots.map((s) => ({ tier: s.tier, title: s.title, goal: s.goal, volume: s.volume })),
    ).toEqual([
      { tier: "S", title: "spine", goal: "hold the line", volume: null },
      { tier: "A", title: "side", goal: "turn the tide", volume: null },
      { tier: "B", title: "quiet beat", goal: "sharpen the silence", volume: 3 },
    ]);
  });
});
