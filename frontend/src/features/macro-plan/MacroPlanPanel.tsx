import type { Anchor, CastMember, MacroCompileData, VolumePlan } from "../../types";

type Props = {
  macroData: MacroCompileData | null;
};

function formatVolumeTargetWords(value: number | undefined): string {
  if (value === undefined || value === null || value === 0) {
    return "未指定";
  }
  return value.toLocaleString("zh-TW");
}

function roleLabel(role: string): string {
  if (role === "protagonist") return "主角";
  if (role === "supporting") return "配角";
  return role;
}

function renderTargetState(targetState: Record<string, unknown>) {
  const entries = Object.entries(targetState);
  if (entries.length === 0) {
    return <p>尚未定義 target state。</p>;
  }

  return (
    <div className="macro-target-state">
      {entries.map(([key, value]) => (
        <div key={key} className="macro-kv">
          <span className="macro-kv-key">{key}</span>
          <code>{JSON.stringify(value, null, 2)}</code>
        </div>
      ))}
    </div>
  );
}

function VolumeCard({ volume }: { volume: VolumePlan }) {
  return (
    <article className="macro-card">
      <div className="macro-card-header">
        <h3>{volume.title}</h3>
        <span>
          Ch. {volume.chapter_start}-{volume.chapter_end}
        </span>
      </div>
      <p className="macro-meta">卷目標字數：{formatVolumeTargetWords(volume.target_volume_words)}</p>
      <p>{volume.summary}</p>
    </article>
  );
}

function AnchorCard({ anchor }: { anchor: Anchor }) {
  const priority = anchor.priority ?? 1;
  return (
    <article className="macro-card">
      <div className="macro-card-header">
        <h3>{anchor.title}</h3>
        <span>
          目標章節: {anchor.chapter_target} · 優先序: {priority}
        </span>
      </div>
      <p>{anchor.description}</p>
      {anchor.volume_id ? <p className="macro-meta">Volume: {anchor.volume_id}</p> : null}
      <h4>Target State</h4>
      {renderTargetState(anchor.target_state)}
    </article>
  );
}

function CastCard({
  member,
  isProtagonistPov,
}: {
  member: CastMember;
  isProtagonistPov: boolean;
}) {
  const aliases = member.aliases?.length ? member.aliases.join("、") : null;
  return (
    <article className="macro-card macro-cast-card">
      <div className="macro-card-header">
        <h3>{member.canonical_name}</h3>
        <div className="macro-cast-badges">
          {isProtagonistPov ? <span className="macro-protagonist-badge">主角 POV</span> : null}
          <span className="macro-role-pill">{roleLabel(member.role)}</span>
        </div>
      </div>
      <p className="macro-meta mono">node_id: {member.node_id}</p>
      {member.short_bio ? <p>{member.short_bio}</p> : null}
      {aliases ? <p className="macro-meta">別名：{aliases}</p> : null}
    </article>
  );
}

export function MacroPlanPanel({ macroData }: Props) {
  const volumes = macroData?.volumes ?? [];
  const anchors = macroData?.anchors ?? [];
  const cast = macroData?.cast ?? [];
  const protagonistId = macroData?.protagonist_character_id ?? "";

  return (
    <section className="panel">
      <h2>Macro Compile 結果</h2>
      {!macroData ? (
        <p>
          尚未執行 macro compile，完成後會在這裡顯示卷規劃、錨點、target state，以及角色表（cast）與主角 POV。
        </p>
      ) : (
        <div className="macro-plan-root">
          <div className="macro-plan-layout">
            <article>
              <div className="macro-section-header">
                <h3>Volumes</h3>
                <span>{volumes.length} 個</span>
              </div>
              <div className="macro-card-list">
                {volumes.map((volume) => (
                  <VolumeCard key={volume.volume_id} volume={volume} />
                ))}
              </div>
            </article>
            <article>
              <div className="macro-section-header">
                <h3>Anchors</h3>
                <span>{anchors.length} 個</span>
              </div>
              <div className="macro-card-list">
                {anchors.map((anchor) => (
                  <AnchorCard key={anchor.anchor_id} anchor={anchor} />
                ))}
              </div>
            </article>
          </div>
          {cast.length > 0 ? (
            <article className="macro-cast-section">
              <div className="macro-section-header">
                <h3>Cast（角色表）</h3>
                <span>{cast.length} 人</span>
              </div>
              {protagonistId ? (
                <p className="macro-meta macro-cast-pov-line">主角 POV node_id: {protagonistId}</p>
              ) : null}
              <div className="macro-cast-list">
                {cast.map((member) => (
                  <CastCard
                    key={member.node_id}
                    member={member}
                    isProtagonistPov={Boolean(protagonistId && member.node_id === protagonistId)}
                  />
                ))}
              </div>
            </article>
          ) : null}
        </div>
      )}
    </section>
  );
}
