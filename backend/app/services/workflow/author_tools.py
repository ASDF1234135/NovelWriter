"""Author agent tools (GraphRAG canon lookup during chapter writing)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.graph_rag_service import GraphRAGService

MAX_AUTHOR_GRAPH_RAG_CALLS = 4
MAX_GRAPH_RAG_QUESTION_CHARS = 2000

AUTHOR_GRAPH_RAG_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "graph_rag_ask",
            "description": (
                "Query story evidence (graph + vector) under current POV and epoch. "
                "Use when unsure about injuries, relationships, prior events, or world rules before writing an action."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Specific canon question grounded in what you need to write next.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Max vector hits (1-20, default 5).",
                    },
                    "context_hop_tier": {
                        "type": "integer",
                        "description": "Graph context tier 0-2 (default 2).",
                    },
                },
                "required": ["question"],
            },
        },
    }
]


def make_author_tool_handler(
    *,
    graph_rag: GraphRAGService,
    story_id: str,
    active_epoch_id: str,
    pov_character_id: str,
    query_log: list[dict[str, str]] | None = None,
) -> Callable[[str, dict[str, Any]], str]:
    call_count = 0

    def handler(name: str, args: dict[str, Any]) -> str:
        nonlocal call_count
        if name != "graph_rag_ask":
            return f"Unknown tool: {name}"
        if call_count >= MAX_AUTHOR_GRAPH_RAG_CALLS:
            return "Tool call limit reached for this chapter (max 4). Write from given context or show uncertainty."
        question = str(args.get("question") or "").strip()
        if not question:
            return "Error: question is required."
        if len(question) > MAX_GRAPH_RAG_QUESTION_CHARS:
            question = question[:MAX_GRAPH_RAG_QUESTION_CHARS]
        try:
            top_k = int(args.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(20, top_k))
        try:
            tier = int(args.get("context_hop_tier") if args.get("context_hop_tier") is not None else 2)
        except (TypeError, ValueError):
            tier = 2
        tier = max(0, min(2, tier))
        call_count += 1
        try:
            answer = graph_rag.ask_question(
                question,
                story_id=story_id,
                active_epoch_id=active_epoch_id or "epoch_present",
                pov_character_id=pov_character_id or "char_public_observer",
                top_k=top_k,
                context_hop_tier=tier,
            )
        except Exception as exc:
            return f"GraphRAG query failed: {exc}"
        text = (answer or "").strip() or "無法從證據確定。"
        if query_log is not None:
            query_log.append(
                {
                    "question": question[:500],
                    "answer_preview": text[:800],
                }
            )
        return text

    return handler
