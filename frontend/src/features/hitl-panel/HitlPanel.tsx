import { useEffect, useState } from "react";
import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
  onDecision: (optionId: string) => Promise<void>;
  onOutlineEdit: (payload: { ground_truth_events: Array<Record<string, unknown>>; narrative_script?: string }) => Promise<void>;
  onStateInjection: (payload: { mutations: Array<Record<string, unknown>> }) => Promise<void>;
  onDraftEdit: (payload: { chapter_content: string; resume_from?: string }) => Promise<void>;
};

function isHitlActive(workflow: WorkflowPayload | null): boolean {
  if (!workflow) return false;
  const st = workflow.state;
  return (
    workflow.run.requires_hitl === true ||
    workflow.run.status === "WAITING_HITL" ||
    st.workflow_status === "WAITING_HITL"
  );
}

export function HitlPanel({ workflow, onDecision, onOutlineEdit, onStateInjection, onDraftEdit }: Props) {
  const [outlineJson, setOutlineJson] = useState('[{"event_id":"event_manual_01","description":"人類手動修正事件","caused_by_event_id":null}]');
  const [narrativeScript, setNarrativeScript] = useState("人類手動指定的表層敘事劇本。");
  const [injectionJson, setInjectionJson] = useState(
    '[{"action":"CREATE_NODE","node_id":"item_backup_relic","node_type":"ITEM","properties":{"canonical_name":"備用道具","description":"HITL 強制注入"}}]',
  );
  const [draftText, setDraftText] = useState("");
  const [resumeFrom, setResumeFrom] = useState("reader");

  const hitlActive = isHitlActive(workflow);
  const options = (workflow?.state.pending_hitl_options as Array<{ id: string; label: string }> | undefined) ?? [];
  const reason = String(workflow?.run.hitl_reason ?? workflow?.state.hitl_reason ?? "");
  const resumeHint = String(workflow?.state.resume_from ?? "");

  useEffect(() => {
    if (hitlActive && workflow?.state.current_draft != null) {
      setDraftText(String(workflow.state.current_draft));
    }
  }, [hitlActive, workflow?.run.run_id, workflow?.state.current_draft]);

  return (
    <section className="panel">
      <h2>HITL 控制台</h2>
      <p>
        狀態：{hitlActive ? <strong>等待人工介入</strong> : "未暫停"}；模式：{workflow?.run.hitl_decision_mode ?? "NONE"}
      </p>
      {hitlActive ? (
        <p className="hitl-context">
          原因：{reason || "—"}；建議續跑節點：<code>{resumeHint || "—"}</code>
        </p>
      ) : null}
      <div className="hitl-grid">
        <article>
          <h3>Dashboard Mode</h3>
          {options.length === 0 ? (
            <p>目前沒有待決策選項。</p>
          ) : (
            options.map((option) => (
              <button key={option.id} type="button" disabled={!hitlActive} onClick={() => onDecision(option.id)}>
                {option.label}
              </button>
            ))
          )}
        </article>
        <article>
          <h3>Manual Outline Editing</h3>
          <textarea value={outlineJson} rows={8} onChange={(event) => setOutlineJson(event.target.value)} disabled={!hitlActive} />
          <textarea value={narrativeScript} rows={4} onChange={(event) => setNarrativeScript(event.target.value)} disabled={!hitlActive} />
          <button
            type="button"
            disabled={!hitlActive}
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
          <h3>正文人工修訂</h3>
          <p className="hint">暫停時會載入目前草稿；預設從 reader 再審一輪。</p>
          <label>
            續跑節點{" "}
            <select value={resumeFrom} onChange={(e) => setResumeFrom(e.target.value)} disabled={!hitlActive}>
              <option value="reader">reader</option>
              <option value="draft_supervisor">draft_supervisor</option>
              <option value="author">author</option>
            </select>
          </label>
          <textarea value={draftText} rows={12} onChange={(event) => setDraftText(event.target.value)} disabled={!hitlActive} />
          <button
            type="button"
            disabled={!hitlActive}
            onClick={() => onDraftEdit({ chapter_content: draftText, resume_from: resumeFrom })}
          >
            提交正文並續跑
          </button>
        </article>
        <article>
          <h3>State Injection</h3>
          <textarea value={injectionJson} rows={8} onChange={(event) => setInjectionJson(event.target.value)} disabled={!hitlActive} />
          <button
            type="button"
            disabled={!hitlActive}
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
