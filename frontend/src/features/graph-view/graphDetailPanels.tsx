import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { GraphEdge, GraphNode, GraphSnapshot } from "../../types";
import { styleForNodeType } from "./nodeTypeStyles";
import { useI18n } from "../../i18n/useI18n";

export const DRAWER_WIDTH_PX = 380;

type DrawerProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
};

/** Right-side drawer as flex sibling so the graph stays visible beside it. */
export function GraphDetailDrawer({ open, title, onClose, children }: DrawerProps) {
  const { t } = useI18n();
  if (!open) return null;
  return (
    <aside
      className="nb-panel flex h-[600px] w-[380px] shrink-0 flex-col shadow-lg"
      aria-label={t("graphDrawer.aria")}
    >
      <div className="flex items-start justify-between gap-2 nb-panel-header px-3 py-2">
        <h4 className="font-headline text-xs font-bold uppercase tracking-wider text-primary">{title}</h4>
        <button
          type="button"
          className="rounded-lg border border-outline-variant/20 bg-surface-container-low px-2 py-1 text-[11px] font-label text-primary hover:bg-surface-container-high"
          onClick={onClose}
        >
          {t("graphDrawer.close")}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">{children}</div>
    </aside>
  );
}

export function buildDisplayNameMap(nodes: GraphNode[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const n of nodes) {
    const id = String(n.node_id ?? "");
    if (!id) continue;
    const name = String(n.canonical_name ?? n.title ?? id);
    m.set(id, name);
  }
  return m;
}

function nodeTypeIcon(t: string): string {
  const u = t.toUpperCase();
  if (u === "CHARACTER") return "\u{1F464}";
  if (u === "PERSONA") return "\u{1F464}";
  if (u === "LOCATION") return "\u{1F4CD}";
  if (u === "ITEM") return "\u{1F392}";
  if (u === "EVENT") return "\u{26A1}";
  if (u === "EPOCH") return "\u{1F553}";
  if (u === "CONCEPT") return "\u{1F4A1}";
  if (u === "RULE") return "\u{1F4DC}";
  return "\u25CB";
}

type RelRow = { otherId: string; label: string; hint?: string };

export function summarizeNodeRelations(centerId: string, edges: GraphEdge[]): {
  locations: RelRow[];
  items: RelRow[];
  relations: RelRow[];
} {
  const locations: RelRow[] = [];
  const items: RelRow[] = [];
  const relations: RelRow[] = [];
  const seenLoc = new Set<string>();
  const seenItem = new Set<string>();
  const seenRel = new Set<string>();

  for (const e of edges) {
    const rel = String(e.relation_type ?? "").toUpperCase();
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    const ctx = String(e.context_details ?? "").trim();
    const hint = ctx.length > 40 ? `${ctx.slice(0, 40)}…` : ctx || undefined;

    if (rel === "LOCATED_IN" && s === centerId) {
      if (!seenLoc.has(t)) {
        seenLoc.add(t);
        locations.push({ otherId: t, label: t, hint });
      }
    }
    if (rel === "HAS_ITEM" && s === centerId) {
      if (!seenItem.has(t)) {
        seenItem.add(t);
        items.push({ otherId: t, label: t, hint });
      }
    }
    if (rel === "HAS_RELATION") {
      let other: string | undefined;
      if (s === centerId && t !== centerId) other = t;
      else if (t === centerId && s !== centerId) other = s;
      if (other && !seenRel.has(other)) {
        seenRel.add(other);
        relations.push({ otherId: other, label: other, hint });
      }
    }
  }
  return { locations, items, relations };
}

export function summarizeRuleRelations(centerId: string, edges: GraphEdge[]): {
  enforcedIn: RelRow[];
  restricts: RelRow[];
  exempt: RelRow[];
} {
  const enforcedIn: RelRow[] = [];
  const restricts: RelRow[] = [];
  const exempt: RelRow[] = [];
  const seenE = new Set<string>();
  const seenR = new Set<string>();
  const seenX = new Set<string>();

  for (const e of edges) {
    const rel = String(e.relation_type ?? "").toUpperCase();
    const s = String(e.source_id ?? "");
    const t = String(e.target_id ?? "");
    if (s !== centerId) continue;
    const ctx = String(e.context_details ?? "").trim();
    const hint = ctx.length > 40 ? `${ctx.slice(0, 40)}…` : ctx || undefined;
    if (rel === "ENFORCED_IN" && t && !seenE.has(t)) {
      seenE.add(t);
      enforcedIn.push({ otherId: t, label: t, hint });
    }
    if (rel === "RESTRICTS" && t && !seenR.has(t)) {
      seenR.add(t);
      restricts.push({ otherId: t, label: t, hint });
    }
    if (rel === "EXEMPT_FROM" && t && !seenX.has(t)) {
      seenX.add(t);
      exempt.push({ otherId: t, label: t, hint });
    }
  }
  return { enforcedIn, restricts, exempt };
}

type NodePanelProps = {
  model: Record<string, unknown>;
  graph: GraphSnapshot;
  displayNames: Map<string, string>;
  onFocusNodeId: (id: string) => void;
  onSetEgoCenter?: (nodeId: string) => void;
};

export function GraphNodeDetailPanel({ model, graph, displayNames, onFocusNodeId, onSetEgoCenter }: NodePanelProps) {
  const { t } = useI18n();
  const [draftOpen, setDraftOpen] = useState(false);
  const nodeId = String(model.node_id ?? model.id ?? "");
  const nodeType = String(model.node_type ?? "");
  const canonical = String(model.canonical_name ?? displayNames.get(nodeId) ?? nodeId);
  const aliases = Array.isArray(model.aliases) ? (model.aliases as unknown[]).map((a) => String(a)) : [];
  const tagList = Array.isArray(model.tags) ? (model.tags as unknown[]).map((a) => String(a)).filter(Boolean) : [];
  const nodeMeta =
    model.metadata && typeof model.metadata === "object" && !Array.isArray(model.metadata)
      ? (model.metadata as Record<string, unknown>)
      : null;
  const nodeMetaJson =
    nodeMeta && Object.keys(nodeMeta).length > 0 ? JSON.stringify(nodeMeta, null, 2) : "";
  const description = String(model.description ?? "").trim();
  const env = String((model as { environmental_condition?: string }).environmental_condition ?? "").trim();
  const itemStatus = String(model.item_status ?? "").trim();
  const isCharacter = nodeType.toUpperCase() === "CHARACTER" || nodeType.toUpperCase() === "PERSONA";
  const isLocation = nodeType.toUpperCase() === "LOCATION";
  const isItem = nodeType.toUpperCase() === "ITEM";
  const isRule = nodeType.toUpperCase() === "RULE";
  const isDead = isCharacter && model.is_alive === false;
  const noEnter = isLocation && model.is_accessible === false;
  const isUnique = isItem && model.is_unique === true;

  const { locations, items, relations } = useMemo(
    () => summarizeNodeRelations(nodeId, graph.edges ?? []),
    [graph.edges, nodeId],
  );
  const { enforcedIn, restricts, exempt } = useMemo(
    () => summarizeRuleRelations(nodeId, graph.edges ?? []),
    [graph.edges, nodeId],
  );
  const rulePenalty = model.penalty != null ? String(model.penalty).trim() : "";

  const resolve = (id: string) => displayNames.get(id) ?? id;

  const mutationDraft = useMemo(() => {
    const props: Record<string, unknown> = {};
    if (description) props.description = description;
    if (env) props.environmental_condition = env;
    if (itemStatus) props.item_status = itemStatus;
    if (isCharacter) props.is_alive = model.is_alive !== false;
    if (isLocation) props.is_accessible = model.is_accessible !== false;
    if (isItem) props.is_unique = model.is_unique === true;
    if (isRule) {
      if (description) props.description = description;
      if (rulePenalty) props.penalty = rulePenalty;
      props.is_active = model.is_active !== false;
    }
    if (aliases.length) props.aliases = aliases;
    if (tagList.length) props.tags = tagList;
    if (nodeMeta && Object.keys(nodeMeta).length > 0) props.metadata = { ...nodeMeta };
    return [
      {
        action: "UPDATE_NODE",
        node_id: nodeId,
        node_type: nodeType,
        properties: props,
      },
    ];
  }, [
    nodeId,
    nodeType,
    description,
    env,
    itemStatus,
    isCharacter,
    isLocation,
    isItem,
    aliases,
    model.is_alive,
    model.is_accessible,
    model.is_unique,
    isRule,
    rulePenalty,
    tagList,
    nodeMeta,
  ]);

  const copyMutation = () => {
    void navigator.clipboard.writeText(JSON.stringify(mutationDraft, null, 2));
  };

  const palette = styleForNodeType(nodeType);

  return (
    <div className="space-y-4 text-on-surface">
      <header className="space-y-2 border-b border-outline-variant/10 pb-3">
        <div className="flex items-start gap-2">
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-base"
            style={{ background: palette.fill, borderColor: palette.stroke, color: "#e5e7eb" }}
            title={nodeType}
          >
            {nodeTypeIcon(nodeType)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate font-headline text-lg font-bold text-on-surface">{canonical}</div>
            <div className="font-mono text-[10px] text-on-surface-variant">{nodeType}</div>
          </div>
        </div>
        {aliases.length ? (
          <div className="flex flex-wrap gap-1">
            {aliases.map((a) => (
              <span
                key={a}
                className="rounded-full border border-outline-variant/20 bg-surface-container-low px-2 py-0.5 text-[10px] text-on-surface-variant"
              >
                {a}
              </span>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {isDead ? (
            <span className="rounded-md bg-red-950/50 px-2 py-0.5 text-[11px] font-medium text-red-200">已死亡</span>
          ) : null}
          {noEnter ? (
            <span className="rounded-md bg-surface-container-high px-2 py-0.5 text-[11px] font-medium text-on-surface">
              無法進入
            </span>
          ) : null}
          {isUnique ? (
            <span className="rounded-md bg-secondary/15 px-2 py-0.5 text-[11px] font-medium text-secondary">唯一物品</span>
          ) : null}
          {isRule && model.is_active === false ? (
            <span className="rounded-md bg-surface-container-high px-2 py-0.5 text-[11px] font-medium text-on-surface-variant line-through">
              規則已失效
            </span>
          ) : null}
        </div>
      </header>

      {isRule ? (
        <section>
          <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">規則內文</h5>
          {description ? (
            <p className="text-sm leading-relaxed text-on-surface-variant">{description}</p>
          ) : (
            <p className="text-xs text-on-surface-variant">{t("graphPanel.noDescription")}</p>
          )}
          {rulePenalty ? (
            <p className="mt-3 rounded-md border border-amber-500/35 bg-amber-950/30 px-3 py-2 text-sm text-amber-100">
              <span className="font-label text-[10px] uppercase tracking-wider text-amber-200/90">違規代價</span>
              <br />
              {rulePenalty}
            </p>
          ) : null}
          <div className="mt-4 space-y-3 text-sm">
            {enforcedIn.length ? (
              <div>
                <span className="font-medium text-on-surface">{t("graphPanel.ruleScope")}</span>
                <ul className="mt-1 space-y-1">
                  {enforcedIn.map((r) => (
                    <li key={r.otherId}>
                      <button
                        type="button"
                        className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                        onClick={() => onFocusNodeId(r.otherId)}
                      >
                        {resolve(r.otherId)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {restricts.length ? (
              <div>
                <span className="font-medium text-on-surface">{t("graphPanel.ruleRestricts")}</span>
                <ul className="mt-1 space-y-1">
                  {restricts.map((r) => (
                    <li key={r.otherId}>
                      <button
                        type="button"
                        className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                        onClick={() => onFocusNodeId(r.otherId)}
                      >
                        {resolve(r.otherId)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {exempt.length ? (
              <div>
                <span className="font-medium text-on-surface">{t("graphPanel.ruleExempt")}</span>
                <ul className="mt-1 space-y-1">
                  {exempt.map((r) => (
                    <li key={r.otherId}>
                      <button
                        type="button"
                        className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                        onClick={() => onFocusNodeId(r.otherId)}
                      >
                        {resolve(r.otherId)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {(description || env || itemStatus) && !isRule && (
        <section>
          <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">核心描述</h5>
          {description ? <p className="text-sm leading-relaxed text-on-surface-variant">{description}</p> : null}
          {env ? (
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              <span className="font-label text-outline">環境：</span>
              {env}
            </p>
          ) : null}
          {itemStatus ? (
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              <span className="font-label text-outline">物品狀態：</span>
              {itemStatus}
            </p>
          ) : null}
        </section>
      )}

      {(tagList.length > 0 || nodeMetaJson) && (
        <section>
          <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">標籤與延伸資料</h5>
          {tagList.length > 0 ? (
            <div className="mb-2 flex flex-wrap gap-1">
              {tagList.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
                >
                  {t}
                </span>
              ))}
            </div>
          ) : null}
          {nodeMetaJson ? (
            <pre className="max-h-32 overflow-auto rounded-md border border-outline-variant/15 bg-surface-container-high/80 p-2 font-mono text-[10px] text-on-surface-variant">
              {nodeMetaJson}
            </pre>
          ) : null}
        </section>
      )}

      <section>
        <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">戰術關係摘要</h5>
        <ul className="space-y-3 text-sm">
          {locations.length ? (
            <li>
              <span className="font-medium text-on-surface">目前位置</span>
              <ul className="mt-1 space-y-1">
                {locations.map((r) => (
                  <li key={r.otherId}>
                    <button
                      type="button"
                      className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                      onClick={() => onFocusNodeId(r.otherId)}
                    >
                      {resolve(r.otherId)}
                    </button>
                    {r.hint ? <span className="ml-2 text-xs text-on-surface-variant">({r.hint})</span> : null}
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
          {items.length ? (
            <li>
              <span className="font-medium text-on-surface">持有物品</span>
              <ul className="mt-1 space-y-1">
                {items.map((r) => (
                  <li key={r.otherId}>
                    <button
                      type="button"
                      className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                      onClick={() => onFocusNodeId(r.otherId)}
                    >
                      {resolve(r.otherId)}
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
          {relations.length ? (
            <li>
              <span className="font-medium text-on-surface">關鍵關係</span>
              <ul className="mt-1 space-y-1">
                {relations.map((r) => (
                  <li key={r.otherId}>
                    <button
                      type="button"
                      className="text-left text-primary underline decoration-outline-variant/40 hover:opacity-90"
                      onClick={() => onFocusNodeId(r.otherId)}
                    >
                      {resolve(r.otherId)}
                    </button>
                    {r.hint ? <span className="ml-2 text-xs text-on-surface-variant">· {r.hint}</span> : null}
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
          {!locations.length && !items.length && !relations.length ? (
            <li className="text-xs text-on-surface-variant">{t("graphPanel.relationsEmpty")}</li>
          ) : null}
        </ul>
      </section>

      <section className="flex flex-col gap-2 border-t border-outline-variant/10 pt-3">
        {onSetEgoCenter ? (
          <button
            type="button"
            className="w-full rounded-lg border border-primary/30 bg-primary/10 py-2 text-sm font-medium text-primary hover:bg-primary/15"
            onClick={() => onSetEgoCenter(nodeId)}
          >
            {t("graphPanel.setEgoCenter")}
          </button>
        ) : null}
        <button
          type="button"
          className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-low py-2 text-sm text-on-surface hover:bg-surface-container-high"
          onClick={() => setDraftOpen((v) => !v)}
        >
          {t("graphPanel.manualFix")}
        </button>
        {draftOpen ? (
          <div className="rounded-lg border border-outline-variant/15 bg-surface-container-low p-2">
            <p className="mb-2 text-[11px] text-on-surface-variant">{t("graphPanel.manualFixHint")}</p>
            <pre className="mb-2 max-h-40 overflow-auto rounded bg-surface-container-high p-2 text-[10px] text-on-surface-variant">
              {JSON.stringify(mutationDraft, null, 2)}
            </pre>
            <button
              type="button"
              className="w-full rounded border border-outline-variant/20 py-1.5 text-xs text-primary"
              onClick={copyMutation}
            >
              {t("graphPanel.copyJson")}
            </button>
          </div>
        ) : null}
      </section>

      <details className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50">
        <summary className="cursor-pointer px-2 py-1.5 font-label text-[10px] text-on-surface-variant">{t("graphPanel.rawJson")}</summary>
        <pre className="max-h-48 overflow-auto p-2 text-[10px] text-on-surface-variant">{JSON.stringify(model, null, 2)}</pre>
      </details>
    </div>
  );
}

type EdgePanelProps = {
  model: Record<string, unknown>;
  graph: GraphSnapshot;
  displayNames: Map<string, string>;
  onFocusNodeId: (id: string) => void;
};

export function GraphEdgeDetailPanel({ model, graph, displayNames, onFocusNodeId }: EdgePanelProps) {
  const { t } = useI18n();
  const sourceId = String(model.source ?? "");
  const targetId = String(model.target ?? "");
  const relation = String(model.relation_type ?? "");
  const resolve = (id: string) => displayNames.get(id) ?? id;
  const ctx = String(model.context_details ?? "").trim();
  const validEpoch = String((model as { valid_epoch?: string }).valid_epoch ?? "").trim();
  const startEv = String((model as { start_event_id?: string }).start_event_id ?? "").trim();
  const endEv = String((model as { end_event_id?: string }).end_event_id ?? "").trim();

  const eventName = (eventNodeId: string) => {
    const n = (graph.nodes ?? []).find((x) => String(x.node_id) === eventNodeId && String(x.node_type).toUpperCase() === "EVENT");
    return n ? String(n.canonical_name ?? n.title ?? eventNodeId) : eventNodeId;
  };
  const epochName = (epochId: string) => {
    const n = (graph.nodes ?? []).find((x) => String(x.node_id) === epochId && String(x.node_type).toUpperCase() === "EPOCH");
    return n ? String(n.canonical_name ?? n.title ?? epochId) : epochId;
  };

  const isTruth = model.is_truth !== false;
  const isPublic = model.is_public === true;
  const knownBy = Array.isArray(model.known_by) ? (model.known_by as unknown[]).map(String).filter(Boolean) : [];
  const holders = Array.isArray(model.holder) ? (model.holder as unknown[]).map(String).filter(Boolean) : [];
  const edgeTagList = Array.isArray(model.tags) ? (model.tags as unknown[]).map((a) => String(a)).filter(Boolean) : [];
  const edgeMeta =
    model.metadata && typeof model.metadata === "object" && !Array.isArray(model.metadata)
      ? (model.metadata as Record<string, unknown>)
      : null;
  const edgeMetaJson =
    edgeMeta && Object.keys(edgeMeta).length > 0 ? JSON.stringify(edgeMeta, null, 2) : "";

  const resolveMaybeId = (v: string) => displayNames.get(v) ?? v;

  return (
    <div className="space-y-4 text-on-surface">
      <section className="rounded-lg border border-outline-variant/15 bg-surface-container-low/40 p-3 text-sm">
        <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">關係鏈</h5>
        <div className="flex flex-wrap items-center gap-1 break-words text-on-surface">
          <button type="button" className="text-primary underline" onClick={() => onFocusNodeId(sourceId)}>
            {resolve(sourceId)}
          </button>
          <span aria-hidden="true" className="text-on-surface-variant">
            ➔
          </span>
          <span className="font-mono text-xs text-secondary">{relation}</span>
          <span aria-hidden="true" className="text-on-surface-variant">
            ➔
          </span>
          <button type="button" className="text-primary underline" onClick={() => onFocusNodeId(targetId)}>
            {resolve(targetId)}
          </button>
        </div>
      </section>

      <section className="space-y-2">
        <h5 className="font-label text-[10px] uppercase tracking-wider text-outline">認知狀態</h5>
        <div className="flex flex-wrap gap-2">
          <span
            className={`rounded-md px-2 py-1 text-[11px] font-medium ${
              isTruth ? "bg-green-900/40 text-green-200" : "bg-red-900/40 text-red-200"
            }`}
          >
            {isTruth ? "客觀事實" : "謠言 / 錯誤認知"}
          </span>
          <span
            className={`rounded-md px-2 py-1 text-[11px] font-medium ${
              isPublic ? "bg-sky-900/40 text-sky-200" : "bg-stone-800 text-stone-300"
            }`}
          >
            {isPublic ? "公開情報" : "秘密"}
          </span>
        </div>
        {knownBy.length ? (
          <div>
            <div className="text-[11px] font-medium text-on-surface-variant">{t("graphPanel.knownBy")}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {knownBy.map((kb) => (
                <span key={kb} className="rounded-full bg-surface-container-high px-2 py-0.5 text-[10px]">
                  {resolveMaybeId(kb)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {holders.length ? (
          <div>
            <div className="text-[11px] font-medium text-on-surface-variant">{t("graphPanel.holders")}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {holders.map((h) => (
                <span key={h} className="rounded-full bg-surface-container-high px-2 py-0.5 text-[10px]">
                  {resolveMaybeId(h)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {(edgeTagList.length > 0 || edgeMetaJson) && (
        <section>
          <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">連線標籤與延伸資料</h5>
          {edgeTagList.length > 0 ? (
            <div className="mb-2 flex flex-wrap gap-1">
              {edgeTagList.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-secondary/30 bg-secondary/10 px-2 py-0.5 text-[10px] text-secondary"
                >
                  {t}
                </span>
              ))}
            </div>
          ) : null}
          {edgeMetaJson ? (
            <pre className="max-h-28 overflow-auto rounded-md border border-outline-variant/15 bg-surface-container-high/80 p-2 font-mono text-[10px] text-on-surface-variant">
              {edgeMetaJson}
            </pre>
          ) : null}
        </section>
      )}

      {(ctx || startEv || endEv || validEpoch) && (
        <section>
          <h5 className="mb-2 font-label text-[10px] uppercase tracking-wider text-outline">脈絡與時間</h5>
          {ctx ? <p className="text-sm leading-relaxed text-on-surface-variant">{ctx}</p> : null}
          {validEpoch ? (
            <p className="mt-2 text-sm">
              <span className="font-label text-outline">時代：</span>
              <button type="button" className="text-primary underline" onClick={() => onFocusNodeId(validEpoch)}>
                {epochName(validEpoch)}
              </button>
            </p>
          ) : null}
          {startEv ? (
            <p className="mt-2 text-sm">
              <span className="font-label text-outline">起源事件：</span>
              <button type="button" className="text-primary underline" onClick={() => onFocusNodeId(startEv)}>
                {eventName(startEv)}
              </button>
            </p>
          ) : null}
          {endEv ? (
            <p className="mt-2 text-sm">
              <span className="font-label text-outline">結算事件：</span>
              <button type="button" className="text-primary underline" onClick={() => onFocusNodeId(endEv)}>
                {eventName(endEv)}
              </button>
            </p>
          ) : null}
        </section>
      )}

      <details className="rounded-lg border border-outline-variant/10 bg-surface-container-low/50">
        <summary className="cursor-pointer px-2 py-1.5 font-label text-[10px] text-on-surface-variant">{t("graphPanel.rawJson")}</summary>
        <pre className="max-h-48 overflow-auto p-2 text-[10px] text-on-surface-variant">{JSON.stringify(model, null, 2)}</pre>
      </details>
    </div>
  );
}
