from __future__ import annotations

import json
from difflib import SequenceMatcher

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.schema import ProsePolishOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile

logger = get_logger(__name__)


def _normalize_for_similarity(text: str) -> str:
    return " ".join(text.split())


def _length_change_ratio(original: str, candidate: str) -> float:
    o, c = len(original), len(candidate)
    if o == 0:
        return 0.0 if c == 0 else 1.0
    return abs(c - o) / o


def _similarity_ratio(original: str, candidate: str) -> float:
    a = _normalize_for_similarity(original)
    b = _normalize_for_similarity(candidate)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _build_prose_polish_prompt(draft: str) -> str:
    max_chars = 28000
    excerpt = draft[:max_chars]
    instructions = {
        "task": "prose_polish",
        "rules": [
            "只做語言與版面修飾：標點、分段、冗字、病句、語氣一致、引號與空白格式。",
            "全文統一為繁體中文：將簡體字、中國用語慣用的簡化寫法改為台灣繁體常用寫法；專有名詞若已在文中固定請保留。",
            "禁止改變劇情、事件順序、因果、角色知識邊界、地點與時間邏輯。",
            "禁止新增或刪除情節段落意義上的內容；不可加入新場景、新對白主線、新角色行為。",
            "禁止更動章節結構性意圖（例如原本未寫明的結尾不可被改成完結）。",
            "輸出 JSON：polished_text（完整正文）與 change_summary（一句話說明修改類型，可為空字串）。",
        ],
        "draft_excerpt": excerpt,
        "excerpt_truncated": len(draft) > max_chars,
        "full_char_length": len(draft),
    }
    return json.dumps(instructions, ensure_ascii=False)


def polish_draft(draft: str, context: WorkflowContext) -> tuple[str, dict]:
    """
    Returns (final_text, diagnostics). On any skip/failure returns original draft.
    """
    settings = get_settings()
    diagnostics: dict = {"applied": False, "skipped_reason": "", "gate_failed": False}

    if not settings.prose_polish_enabled:
        diagnostics["skipped_reason"] = "disabled"
        return draft, diagnostics

    if not (draft or "").strip():
        diagnostics["skipped_reason"] = "empty_draft"
        return draft, diagnostics

    if isinstance(context.llm_client, MockLLMClient):
        diagnostics["skipped_reason"] = "mock_llm_passthrough"
        return draft, diagnostics

    profile = get_profile("prose_polish")
    prompt = _build_prose_polish_prompt(draft)
    try:
        out, res = context.llm_client.invoke_json(prompt, ProsePolishOutput, profile)
    except Exception as exc:
        logger.warning("prose_polish_llm_failed", extra={"extra_payload": {"error": str(exc)}})
        diagnostics["skipped_reason"] = f"llm_error:{exc!s}"
        return draft, diagnostics

    candidate = (out.polished_text or "").strip()
    if not candidate:
        diagnostics["skipped_reason"] = "empty_model_output"
        return draft, diagnostics

    max_delta = settings.prose_polish_max_relative_length_change
    if _length_change_ratio(draft, candidate) > max_delta:
        diagnostics["gate_failed"] = True
        diagnostics["skipped_reason"] = "length_change_exceeded"
        return draft, diagnostics

    min_sim = settings.prose_polish_min_similarity_ratio
    if _similarity_ratio(draft, candidate) < min_sim:
        diagnostics["gate_failed"] = True
        diagnostics["skipped_reason"] = "similarity_below_threshold"
        return draft, diagnostics

    diagnostics["applied"] = True
    diagnostics["change_summary"] = (out.change_summary or "")[:500]
    diagnostics["token_usage"] = res.token_usage
    diagnostics["latency_ms"] = res.latency_ms
    return candidate, diagnostics


def run_prose_polish(state: dict, context: WorkflowContext) -> dict:
    original = state["current_draft"]
    polished, diag = polish_draft(original, context)
    best = state.get("best_draft_content") or ""
    if best == original:
        best = polished
    return {
        "current_draft": polished,
        "best_draft_content": best,
        "prose_polish_diagnostics": diag,
        "last_agent": "prose_polish",
        "resume_from": "state_updater",
    }
