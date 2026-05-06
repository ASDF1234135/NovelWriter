from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.core.config import get_settings
from app.domain.schema import GraphQueryRequest, GraphSnapshot
from app.services.graph_store import GraphStore
from app.services.llm import LLMClient
from app.services.vector_store import VectorStore
from app.services.workflow.profiles import AgentPromptProfile


_GRAPH_RAG_ASK_SYSTEM_PROMPT = """You are a question answering assistant operating under a strict evidence-only policy.

Rules:
- Answer ONLY using objective facts that are explicitly present in the provided evidence pack.
- Do NOT guess, do NOT fill gaps, do NOT invent details, and do NOT assume missing relationships.
- If the evidence pack is insufficient to answer, say: 「無法從證據確定」, then list 1–3 specific missing evidence items.
- Keep the answer concise and grounded; avoid speculation language.
"""

_GRAPH_RAG_EVALUATE_SYSTEM_PROMPT = """You are a condition evaluation engine operating under a strict evidence-only policy.

Rules:
- Decide ONLY from objective facts explicitly present in the evidence pack.
- Do NOT guess. If the evidence does not support the condition, resolve=false with low confidence.
- reasoning MUST cite concrete evidence points (what in graph/vector supports or contradicts); no vague boilerplate.
- Output must be a single JSON object matching the provided schema; no markdown, no extra text.
"""


def _prune_empty_values(value: Any) -> Any:
    """Recursively drop empty scalars/containers from dict/list payloads."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            pruned = _prune_empty_values(v)
            if pruned is None:
                continue
            if pruned == "":
                continue
            if pruned == []:
                continue
            if pruned == {}:
                continue
            out[k] = pruned
        return out
    if isinstance(value, list):
        items = []
        for item in value:
            pruned = _prune_empty_values(item)
            if pruned is None or pruned == "" or pruned == [] or pruned == {}:
                continue
            items.append(pruned)
        return items
    if isinstance(value, str):
        s = value.strip()
        return s
    return value


def _stable_text_key(text: str, *, max_chars: int = 240) -> str:
    t = (text or "").strip()
    return re.sub(r"\s+", " ", t[:max_chars])


def _dedupe_vector_hits(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe vector documents by (chunk_id or text prefix)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in raw:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        cid = str(meta.get("chunk_id") or "").strip()
        txt = str(hit.get("text_chunk") or "")
        key = f"chunk:{cid}" if cid else f"text:{_stable_text_key(txt)}"
        if not key.strip() or key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _aligned_chunk_context(graph: dict[str, Any], vector_hits: list[dict[str, Any]], *, max_chars: int = 5000) -> str:
    """Optional: build an aligned context view using chunk_id links (best-effort)."""
    # Index edges by chunk_ids (if present in metadata).
    chunk_to_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in (graph.get("edges") or []) if isinstance(graph, dict) else []:
        if not isinstance(edge, dict):
            continue
        meta = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
        chunk_ids = meta.get("chunk_ids") or []
        if isinstance(chunk_ids, str):
            chunk_ids = [chunk_ids]
        if not isinstance(chunk_ids, list):
            continue
        for cid in chunk_ids:
            cid_s = str(cid).strip()
            if cid_s:
                chunk_to_edges.setdefault(cid_s, []).append(edge)

    grouped: dict[str, list[str]] = {}
    ambience: list[str] = []
    for hit in vector_hits:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        cid = str(meta.get("chunk_id") or "").strip()
        text = str(hit.get("text_chunk") or "").strip()
        if not text:
            continue
        aligned_edges = chunk_to_edges.get(cid, []) if cid else []
        if aligned_edges:
            key = f"chunk_id={cid}"
            grouped.setdefault(key, []).append(text)
        else:
            ambience.append(text)

    lines: list[str] = []
    if grouped:
        lines.append("【Aligned Evidence Chunks】")
        for key, texts in list(grouped.items())[:10]:
            lines.append(f"- {key}")
            for t in texts[:4]:
                lines.append(f"  - {t[:400]}")
    if ambience:
        if lines:
            lines.append("")
        lines.append("【背景語意/氛圍 (Unaligned but retained)】")
        for t in ambience[:8]:
            lines.append(f"- {t[:400]}")
    out = "\n".join(lines).strip()
    if len(out) <= max_chars:
        return out
    return out[: max_chars - 1] + "…"


@dataclass
class GraphRAGService:
    graph_store: GraphStore
    vector_store: VectorStore
    llm: LLMClient

    def _extract_entities(self, query: str) -> list[str]:
        """Lightweight entity/term extraction; best-effort only."""
        q = (query or "").strip()
        if not q:
            return []
        # Keep CJK tokens and simple word tokens; drop very short noise.
        tokens = re.split(r"[\s,，。.!?！？:：;；()（）\[\]{}<>\"'`]+", q.lower())
        out: list[str] = []
        seen: set[str] = set()
        for tok in tokens:
            t = tok.strip()
            if len(t) < 2:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= 8:
                break
        return out

    def _prune_graph_snapshot(self, snapshot: GraphSnapshot) -> dict[str, Any]:
        """Remove empty node attributes and technical edge fields (best-effort)."""
        raw = snapshot.model_dump(mode="json")
        raw = _prune_empty_values(raw)
        if not isinstance(raw, dict):
            return {"nodes": [], "edges": []}

        nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
        edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []

        pruned_nodes: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node = _prune_empty_values(node)
            if not isinstance(node, dict):
                continue
            # Keep required identity fields even if empty-ish (defensive).
            for k in ("node_id", "node_type", "canonical_name"):
                if k not in node:
                    node[k] = ""
            pruned_nodes.append(node)

        pruned_edges: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            edge = _prune_empty_values(edge)
            if not isinstance(edge, dict):
                continue
            # If a readable name is provided, the technical id can be omitted.
            if str(edge.get("source_name") or "").strip():
                edge.pop("source_id", None)
            if str(edge.get("target_name") or "").strip():
                edge.pop("target_id", None)
            pruned_edges.append(edge)

        return {"nodes": pruned_nodes, "edges": pruned_edges}

    def _retrieve_evidence_pack(
        self,
        query: str,
        *,
        story_id: str,
        active_epoch_id: str,
        pov_character_id: str,
        top_k: int = 5,
        context_hop_tier: int = 2,
        include_aligned_chunk_context: bool = True,
        max_evidence_chars: int = 30_000,
    ) -> dict[str, Any]:
        entities = self._extract_entities(query)
        request = GraphQueryRequest(
            story_id=story_id,
            active_epoch_id=active_epoch_id,
            pov_character_id=pov_character_id,
            narrative_directive=query,
            context_hop_tier=max(0, min(2, int(context_hop_tier))),
        )
        graph_snapshot = self.graph_store.query_context(request)
        pruned_graph = self._prune_graph_snapshot(graph_snapshot)

        vector_docs = self.vector_store.search(story_id, query, limit=max(1, min(20, int(top_k))))
        vector_hits_raw = [doc.model_dump(mode="json") for doc in vector_docs]
        vector_hits = _dedupe_vector_hits(vector_hits_raw)
        vector_hits = _prune_empty_values(vector_hits)

        pack: dict[str, Any] = {
            "entities": entities,
            "graph": pruned_graph,
            "vector": vector_hits,
        }
        if include_aligned_chunk_context:
            pack["aligned_chunk_context"] = _aligned_chunk_context(pruned_graph, vector_hits)

        # Hard cap (best-effort): trim vector hits if payload explodes.
        raw_text = json.dumps(pack, ensure_ascii=False)
        if len(raw_text) <= max_evidence_chars:
            return pack

        shrunk = dict(pack)
        vec = list(vector_hits) if isinstance(vector_hits, list) else []
        while vec and len(json.dumps({**shrunk, "vector": vec}, ensure_ascii=False)) > max_evidence_chars:
            vec = vec[:-1]
        shrunk["vector"] = vec
        return shrunk

    def ask_question(
        self,
        question: str,
        *,
        story_id: str,
        active_epoch_id: str,
        pov_character_id: str,
        top_k: int = 5,
        context_hop_tier: int = 2,
    ) -> str:
        evidence = self._retrieve_evidence_pack(
            question,
            story_id=story_id,
            active_epoch_id=active_epoch_id,
            pov_character_id=pov_character_id,
            top_k=top_k,
            context_hop_tier=context_hop_tier,
        )
        prompt = (
            "Evidence pack (JSON):\n"
            f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
            f"Question:\n{question}\n"
        )
        settings = get_settings()
        profile = AgentPromptProfile(
            agent_name="graph_rag_ask",
            system_prompt=_GRAPH_RAG_ASK_SYSTEM_PROMPT,
            model=settings.llm_model,
            temperature=0.1,
        )
        return self.llm.invoke_text(prompt, profile).content

    def evaluate_condition(
        self,
        condition_desc: str,
        *,
        story_id: str,
        active_epoch_id: str,
        pov_character_id: str,
        response_model: type[Any],
        top_k: int = 5,
        context_hop_tier: int = 2,
    ) -> Any:
        evidence = self._retrieve_evidence_pack(
            condition_desc,
            story_id=story_id,
            active_epoch_id=active_epoch_id,
            pov_character_id=pov_character_id,
            top_k=top_k,
            context_hop_tier=context_hop_tier,
        )
        prompt = (
            "You must evaluate the condition using the evidence pack.\n"
            "Evidence pack (JSON):\n"
            f"{json.dumps(evidence, ensure_ascii=False)}\n\n"
            f"Condition:\n{condition_desc}\n"
        )
        settings = get_settings()
        profile = AgentPromptProfile(
            agent_name="graph_rag_evaluate",
            system_prompt=_GRAPH_RAG_EVALUATE_SYSTEM_PROMPT,
            model=settings.llm_model,
            temperature=0.0,
        )
        parsed, _llm_result = self.llm.invoke_json(prompt, response_model, profile)
        return parsed

