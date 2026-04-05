import { useState } from "react";
import type { Anchor, CastMember, MacroCompileData, VolumePlan } from "../../types";

type Props = {
  macroData: MacroCompileData | null;
};

type MacroTab = "bible" | "volumes" | "cast" | "anchors";

function formatVolumeTargetWords(value: number | undefined): string {
  if (value === undefined || value === null || value === 0) return "未指定";
  return value.toLocaleString("zh-TW");
}

function roleLabel(role: string): string {
  if (role === "protagonist") return "主角";
  if (role === "antagonist") return "反派";
  if (role === "supporting") return "配角";
  return role;
}

function renderTargetState(targetState: Record<string, unknown>) {
  const entries = Object.entries(targetState);
  if (entries.length === 0) return <p className="font-body text-on-surface-variant">尚未定義預期狀態細節。</p>;
  return (
    <div className="space-y-3">
      {entries.map(([key, value]) => (
        <div key={key}>
          <span className="font-label text-xs font-semibold text-on-surface-variant">{key}</span>
          <pre className="auteur-pre mt-1 text-xs">{JSON.stringify(value, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

function VolumeCard({ volume, accent }: { volume: VolumePlan; accent: "secondary" | "primary" | "tertiary" }) {
  const dot =
    accent === "secondary" ? "bg-secondary" : accent === "primary" ? "bg-primary" : "bg-tertiary";
  const labelColor =
    accent === "secondary" ? "text-secondary" : accent === "primary" ? "text-primary" : "text-tertiary";
  return (
    <article className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 transition-colors hover:bg-surface-container-high/80">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${labelColor}`}>{volume.volume_id}</span>
          <h3 className="font-headline text-xl font-bold text-on-surface">{volume.title}</h3>
        </div>
        <span className="font-label text-xs text-outline">
          第 {volume.chapter_start}–{volume.chapter_end} 章
        </span>
      </div>
      <p className="mb-3 font-body text-sm italic leading-relaxed text-on-surface-variant">{volume.summary}</p>
      <p className="mb-3 font-label text-xs text-primary/90">卷目標字數：{formatVolumeTargetWords(volume.target_volume_words)}</p>
      <div className={`space-y-2 border-t border-outline-variant/10 pt-3`}>
        <div className="flex items-center gap-2 text-sm text-on-surface">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
          <span>分卷故事線</span>
        </div>
      </div>
    </article>
  );
}

function AnchorCard({ anchor }: { anchor: Anchor }) {
  const priority = anchor.priority ?? 1;
  return (
    <article className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-5">
      <div className="mb-2 flex flex-wrap justify-between gap-2">
        <h3 className="font-headline text-lg font-bold text-on-surface">{anchor.title}</h3>
        <span className="font-label text-xs text-secondary">
          目標章節 {anchor.chapter_target} · 優先 {priority}
        </span>
      </div>
      <p className="mb-3 font-body text-sm text-on-surface-variant">{anchor.description}</p>
      {anchor.volume_id ? <p className="mb-2 font-label text-xs text-outline">所屬分卷：{anchor.volume_id}</p> : null}
      <h4 className="mb-2 font-headline text-xs font-bold uppercase tracking-wider text-primary">預期狀態（細節）</h4>
      {renderTargetState(anchor.target_state)}
    </article>
  );
}

function CastDetail({ label, value }: { label: string; value: string }) {
  if (!value.trim()) return null;
  return (
    <div className="mt-2 border-t border-outline-variant/10 pt-2">
      <span className="font-label text-[10px] font-bold uppercase tracking-wider text-outline">{label}</span>
      <p className="mt-1 font-body text-sm text-on-surface/90">{value}</p>
    </div>
  );
}

function CastCard({ member, isProtagonistPov }: { member: CastMember; isProtagonistPov: boolean }) {
  const aliases = member.aliases?.length ? member.aliases.join("、") : null;
  return (
    <article className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-5 transition-all hover:border-primary/20">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-headline text-lg font-bold">{member.canonical_name}</h3>
        <div className="flex flex-wrap gap-2">
          {isProtagonistPov ? (
            <span className="rounded-full border border-secondary/40 bg-secondary/15 px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wide text-secondary">
              主角視角
            </span>
          ) : null}
          <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-label text-[10px] text-primary">
            {roleLabel(member.role)}
          </span>
        </div>
      </div>
      <p className="mb-1 font-mono text-xs text-on-surface-variant">系統內部編號：{member.node_id}</p>
      {member.short_bio ? <p className="font-body text-sm text-on-surface/90">{member.short_bio}</p> : null}
      <CastDetail label="年齡" value={member.age ?? ""} />
      <CastDetail label="動機" value={member.motivation ?? ""} />
      <CastDetail label="核心價值" value={member.core_value ?? ""} />
      <CastDetail label="語感" value={member.speech_style ?? ""} />
      <CastDetail label="致命缺陷" value={member.fatal_flaw ?? ""} />
      {aliases ? <p className="mt-2 font-label text-xs text-outline">別名：{aliases}</p> : null}
    </article>
  );
}

const tabAccent: Record<number, "secondary" | "primary" | "tertiary"> = {
  0: "secondary",
  1: "primary",
  2: "tertiary",
};

export function MacroPlanPanel({ macroData }: Props) {
  const [tab, setTab] = useState<MacroTab>("volumes");
  const volumes = macroData?.volumes ?? [];
  const anchors = macroData?.anchors ?? [];
  const cast = macroData?.cast ?? [];
  const protagonistId = macroData?.protagonist_character_id ?? "";
  const bible = macroData?.bible;
  const hasBible = bible && typeof bible === "object" && Object.keys(bible).length > 0;

  function copyBibleJson() {
    if (!bible) return;
    void navigator.clipboard.writeText(JSON.stringify(bible, null, 2));
  }

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-headline text-xl font-bold text-on-surface">
          <span className="material-symbols-outlined text-secondary">format_list_bulleted</span>
          世界觀與結構產出
        </h2>
        {macroData ? (
          <span className="rounded-full border border-outline-variant/20 bg-surface-container px-3 py-1 font-label text-[10px] font-bold uppercase tracking-widest text-outline">
            分卷 {volumes.length}
          </span>
        ) : null}
      </div>

      {!macroData ? (
        <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-8 text-center font-body text-on-surface-variant">
          執行「產生世界觀與結構」後，可在此檢視世界觀總表、分卷、人物與里程碑。
        </div>
      ) : (
        <>
          <nav className="flex flex-wrap gap-4 border-b border-outline-variant/10 font-label text-sm font-bold uppercase tracking-widest md:gap-6">
            {(["bible", "volumes", "cast", "anchors"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`pb-3 transition-colors ${
                  tab === t ? "border-b-2 border-primary text-primary" : "text-on-surface-variant/60 hover:text-on-surface"
                }`}
              >
                {t === "bible" ? "世界觀總表" : t === "volumes" ? "分卷" : t === "cast" ? "人物" : "里程碑"}
              </button>
            ))}
          </nav>

          {tab === "bible" ? (
            <div className="space-y-4">
              {!hasBible ? (
                <p className="font-body text-on-surface-variant">尚未執行世界觀編譯，或總表仍為空。</p>
              ) : (
                <>
                  <div className="flex justify-end">
                    <button type="button" className="btn-secondary text-xs" onClick={copyBibleJson}>
                      複製完整資料（供備份）
                    </button>
                  </div>
                  <pre className="auteur-pre max-h-[min(70vh,520px)] overflow-auto rounded-xl border border-outline-variant/10 bg-surface-container-low p-4 text-xs">
                    {JSON.stringify(bible, null, 2)}
                  </pre>
                </>
              )}
              {macroData.macro_author_notes ? (
                <details className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-4">
                  <summary className="cursor-pointer font-label text-sm font-bold text-on-surface">作者補充筆記（編譯輸入）</summary>
                  <p className="mt-3 whitespace-pre-wrap font-body text-sm text-on-surface-variant">{macroData.macro_author_notes}</p>
                </details>
              ) : null}
            </div>
          ) : null}

          {tab === "volumes" ? (
            <div className="space-y-6">
              {volumes.map((volume, i) => (
                <VolumeCard key={volume.volume_id} volume={volume} accent={tabAccent[i % 3] ?? "primary"} />
              ))}
            </div>
          ) : null}

          {tab === "cast" ? (
            <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
              {cast.length === 0 ? (
                <p className="text-on-surface-variant">尚無人物資料。</p>
              ) : (
                cast.map((member) => (
                  <CastCard
                    key={member.node_id}
                    member={member}
                    isProtagonistPov={Boolean(protagonistId && member.node_id === protagonistId)}
                  />
                ))
              )}
            </div>
          ) : null}

          {tab === "anchors" ? (
            <div className="space-y-4">
              {anchors.length === 0 ? (
                <p className="text-on-surface-variant">無錨點。</p>
              ) : (
                anchors.map((anchor) => <AnchorCard key={anchor.anchor_id} anchor={anchor} />)
              )}
            </div>
          ) : null}

          <div className="glass-panel mt-8 rounded-xl border border-outline-variant/20 p-6 shadow-glow">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20">
                <span className="material-symbols-outlined text-primary">psychology</span>
              </div>
              <div>
                <h5 className="font-headline text-sm font-bold text-on-surface">小提示</h5>
                <p className="font-label text-[10px] font-bold uppercase tracking-widest text-tertiary">操作說明</p>
              </div>
            </div>
            <p className="font-body text-sm leading-relaxed text-on-surface-variant">
              調整左側梗概與作者補充後按「儲存設定」，再按「產生世界觀與結構」以更新總表、分卷、里程碑與人物卡。
            </p>
          </div>
        </>
      )}
    </section>
  );
}
