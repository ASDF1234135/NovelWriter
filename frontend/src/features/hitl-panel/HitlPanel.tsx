import { useState } from "react";
import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
  onDecision: (optionId: string) => Promise<void>;
  onOutlineEdit: (payload: { ground_truth_events: Array<Record<string, unknown>>; narrative_script?: string }) => Promise<void>;
  onStateInjection: (payload: { mutations: Array<Record<string, unknown>> }) => Promise<void>;
};

export function HitlPanel({ workflow, onDecision, onOutlineEdit, onStateInjection }: Props) {
  const [outlineJson, setOutlineJson] = useState('[{"event_id":"event_manual_01","description":"人類手動修正事件","caused_by_event_id":null}]');
  const [narrativeScript, setNarrativeScript] = useState("人類手動指定的表層敘事劇本。");
  const [injectionJson, setInjectionJson] = useState(
    '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"備用道具","description":"HITL 強制注入"}}]',
  );

  const options = (workflow?.state.pending_hitl_options as Array<{ id: string; label: string }> | undefined) ?? [];

  return (
    <section className="panel">
      <h2>HITL 控制台</h2>
      <p>目前模式：{workflow?.run.hitl_decision_mode ?? "NONE"}</p>
      <div className="hitl-grid">
        <article>
          <h3>Dashboard Mode</h3>
          {options.length === 0 ? (
            <p>目前沒有待決策選項。</p>
          ) : (
            options.map((option) => (
              <button key={option.id} onClick={() => onDecision(option.id)}>
                {option.label}
              </button>
            ))
          )}
        </article>
        <article>
          <h3>Manual Outline Editing</h3>
          <textarea value={outlineJson} rows={8} onChange={(event) => setOutlineJson(event.target.value)} />
          <textarea value={narrativeScript} rows={4} onChange={(event) => setNarrativeScript(event.target.value)} />
          <button
            onClick={() =>
              onOutlineEdit({
                ground_truth_events: JSON.parse(outlineJson) as Array<Record<string, unknown>>,
                narrative_script: narrativeScript,
              })
            }
          >
            提交大綱覆寫
          </button>
        </article>
        <article>
          <h3>State Injection</h3>
          <textarea value={injectionJson} rows={8} onChange={(event) => setInjectionJson(event.target.value)} />
          <button
            onClick={() =>
              onStateInjection({
                mutations: JSON.parse(injectionJson) as Array<Record<string, unknown>>,
              })
            }
          >
            強制寫入世界線
          </button>
        </article>
      </div>
    </section>
  );
}
