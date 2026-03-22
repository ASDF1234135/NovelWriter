import { useState } from "react";
import type { StoryInput } from "../../types";

type Props = {
  onSubmit: (payload: StoryInput) => Promise<void>;
  disabled?: boolean;
};

/** Keys merged from separated inputs on submit (overrides same keys in JSON Bible if both set). */
const SEPARATED_BIBLE_KEYS = ["story_genre", "writing_style", "narrative_pov", "tone"] as const;

type SeparatedBibleFields = Record<(typeof SEPARATED_BIBLE_KEYS)[number], string>;

/** 預設 JSON Bible（world_rules、factions 等）。類型／風格／視角／基調請用表單上方欄位，送出時合併為 story_genre、writing_style、narrative_pov、tone。 */
const defaultBible = {
  world_rules: ["魔法代價必須被支付", "王都與北境交通受季節影響"],
  factions: ["王室", "邊境軍", "黑巷情報網"],
};

function emptySeparatedFields(): SeparatedBibleFields {
  return {
    story_genre: "",
    writing_style: "",
    narrative_pov: "",
    tone: "",
  };
}

/** Apply separated fields: trim; empty removes key from bible. */
function mergeSeparatedIntoBible(bible: Record<string, unknown>, fields: SeparatedBibleFields): Record<string, unknown> {
  const next: Record<string, unknown> = { ...bible };
  for (const key of SEPARATED_BIBLE_KEYS) {
    const t = fields[key].trim();
    if (t === "") {
      delete next[key];
    } else {
      next[key] = t;
    }
  }
  return next;
}

export function StorySetupForm({ onSubmit, disabled }: Props) {
  const [title, setTitle] = useState("王都疑雲");
  const [premise, setPremise] = useState("一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。");
  const [targetTotalWords, setTargetTotalWords] = useState(100000);
  const [planRetryLimit, setPlanRetryLimit] = useState(3);
  const [draftLoopRetryLimit, setDraftLoopRetryLimit] = useState(3);
  const [separated, setSeparated] = useState<SeparatedBibleFields>(emptySeparatedFields);
  const [bibleJson, setBibleJson] = useState(JSON.stringify(defaultBible, null, 2));
  const [bibleError, setBibleError] = useState("");

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    let bible: Record<string, unknown>;
    try {
      const parsed = JSON.parse(bibleJson) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setBibleError("JSON Bible 必須是 JSON 物件，不能是陣列、字串或空值。");
        return;
      }
      bible = parsed as Record<string, unknown>;
    } catch {
      setBibleError("JSON Bible 格式錯誤，請移除多餘逗號並確認引號與括號完整。");
      return;
    }

    setBibleError("");
    bible = mergeSeparatedIntoBible(bible, separated);

    await onSubmit({
      title,
      premise,
      target_total_words: targetTotalWords,
      plan_retry_limit: planRetryLimit,
      draft_loop_retry_limit: draftLoopRetryLimit,
      bible,
    });
  }

  return (
    <section className="panel">
      <h2>初始設定區</h2>
      <form className="form-grid" onSubmit={handleSubmit}>
        <label>
          故事標題
          <input value={title} onChange={(event) => setTitle(event.target.value)} disabled={disabled} />
        </label>
        <label>
          目標總字數
          <input
            type="number"
            value={targetTotalWords}
            onChange={(event) => setTargetTotalWords(Number(event.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          Planner 最大回退次數
          <input
            type="number"
            min={0}
            max={20}
            value={planRetryLimit}
            onChange={(event) => setPlanRetryLimit(Number(event.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          Draft/Reader 合併最大回退次數
          <input
            type="number"
            min={0}
            max={20}
            value={draftLoopRetryLimit}
            onChange={(event) => setDraftLoopRetryLimit(Number(event.target.value))}
            disabled={disabled}
          />
        </label>
        <label className="full-width">
          一句話大綱
          <textarea value={premise} onChange={(event) => setPremise(event.target.value)} rows={4} disabled={disabled} />
        </label>

        <div className="full-width story-bible-meta">
          <h3 className="story-bible-meta-title">故事類型與風格</h3>
          <p className="story-bible-meta-hint">
            以下欄位會在送出時寫入 Bible（鍵名：story_genre、writing_style、narrative_pov、tone）。若與下方 JSON
            內同名鍵並存，以這裡為準。
          </p>
        </div>
        <label>
          故事類型
          <input
            value={separated.story_genre}
            onChange={(event) => setSeparated((s) => ({ ...s, story_genre: event.target.value }))}
            placeholder="例：懸疑／宮廷奇幻"
            disabled={disabled}
          />
        </label>
        <label>
          敘事視角（可選）
          <input
            value={separated.narrative_pov}
            onChange={(event) => setSeparated((s) => ({ ...s, narrative_pov: event.target.value }))}
            placeholder="例：第三人稱限制視角（主角）"
            disabled={disabled}
          />
        </label>
        <label className="full-width">
          寫作風格
          <textarea
            value={separated.writing_style}
            onChange={(event) => setSeparated((s) => ({ ...s, writing_style: event.target.value }))}
            placeholder="例：節奏偏快、對白簡潔、畫面具象。"
            rows={3}
            disabled={disabled}
          />
        </label>
        <label className="full-width">
          整體基調（可選）
          <input
            value={separated.tone}
            onChange={(event) => setSeparated((s) => ({ ...s, tone: event.target.value }))}
            placeholder="例：陰鬱、冷硬派幽默"
            disabled={disabled}
          />
        </label>

        <label className="full-width">
          JSON Bible（世界規則、勢力等）
          <textarea
            value={bibleJson}
            onChange={(event) => {
              setBibleJson(event.target.value);
              if (bibleError) {
                setBibleError("");
              }
            }}
            rows={10}
            disabled={disabled}
            aria-invalid={Boolean(bibleError)}
          />
        </label>
        {bibleError ? <div className="error-banner full-width">{bibleError}</div> : null}
        <button type="submit" disabled={disabled}>
          建立故事
        </button>
      </form>
    </section>
  );
}
