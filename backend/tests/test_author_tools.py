from unittest.mock import MagicMock

from app.services.workflow.author_tools import (
    AUTHOR_GRAPH_RAG_TOOLS,
    MAX_AUTHOR_GRAPH_RAG_CALLS,
    make_author_tool_handler,
)


def test_author_graph_rag_tool_schema() -> None:
    fn = AUTHOR_GRAPH_RAG_TOOLS[0]["function"]
    assert fn["name"] == "graph_rag_ask"
    assert "question" in fn["parameters"]["properties"]


def test_author_tool_handler_calls_graph_rag_and_limits() -> None:
    graph_rag = MagicMock()
    graph_rag.ask_question.return_value = "Evidence answer."
    log: list[dict[str, str]] = []
    handler = make_author_tool_handler(
        graph_rag=graph_rag,
        story_id="story_1",
        active_epoch_id="epoch_present",
        pov_character_id="char_a",
        query_log=log,
    )
    out = handler("graph_rag_ask", {"question": "Who was injured?"})
    assert "Evidence answer" in out
    assert len(log) == 1
    graph_rag.ask_question.assert_called_once()
    for _ in range(MAX_AUTHOR_GRAPH_RAG_CALLS):
        handler("graph_rag_ask", {"question": "again"})
    blocked = handler("graph_rag_ask", {"question": "one more"})
    assert "limit" in blocked.lower()
    assert graph_rag.ask_question.call_count == MAX_AUTHOR_GRAPH_RAG_CALLS
