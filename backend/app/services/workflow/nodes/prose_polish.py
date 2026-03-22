"""Post-reader prose polish: Traditional Chinese unification, light formatting — no plot changes."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from app.core.config import get_settings
from app.domain.schema import ProsePolishOutput
from app.core.logging import get_logger
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile

logger = get_logger(__name__)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _length_delta_ratio(original: str, candidate: str) -> float:
    olen = max(len(original), 1)
    return abs(len(candidate) - len(original)) / olen


def _similarity_ratio(original: str, candidate: str) -> float:
    a, b = _collapse_ws(original), _collapse_ws(candidate)
    if not a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _polish_passes_gate(original: str, candidate: str, max_len_delta: float, min_similarity: float) -> tuple[bool, str]:
    if candidate.strip() == "":
        return False, "empty_polished_text"
    if _length_delta_ratio(original, candidate) > max_len_delta:
        return False, "length_delta_exceeded"
    if _similarity_ratio(original, candidate) < min_similarity:
        return False, "similarity_below_threshold"
    return True, ""


def _build_polish_prompt(draft: str) -> str:
    return json.dumps(
        {
            "role": "prose_polish",
            "instructions": (
                "你是繁體中文小說定稿編修。只能做語言與版面層面的整理，不得改變劇情、事件順序、因果、角色知識邊界、地點與時間邏輯，"
                "不得新增或刪除情節意義上的內容。"
                "\n必須統一為繁體中文：將簡體字、中國大陸用語或異體字改為台灣書面語慣用之繁體與詞彙；"
                "專有名詞（人名、地名、作品名）若原文已固定寫法則維持，不要硬改音譯。"
                "\n可調整：標點、分段、冗餘口頭禪、輕微病句、引號與換行格式、明顯的語氣不一致。"
                "\n請輸出完整 polished_text（整章正文），不要摘要或刪段。"
            ),
            "draft": draft,
            "draft_char_count": len(draft),
        },
        ensure_ascii=False,
    )


def run_prose_polish(state: dict, context: WorkflowContext) -> dict:
    """Return state updates for current_draft / best_draft_content and diagnostics fields."""
    settings = get_settings()
    raw = state.get("current_draft") or ""
    diagnostics: dict = {
        "applied": False,
        "skipped": False,
        "gate_rejected": False,
        "gate_reason": "",
        "similarity": None,
        "length_delta_ratio": None,
    }

    if not settings.prose_polish_enabled:
        diagnostics["skipped"] = True
        diagnostics["reason"] = "disabled_in_settings"
        return {
            "current_draft": raw,
            "best_draft_content": raw,
            "prose_polish_diagnostics": diagnostics,
        }

    if isinstance(context.llm_client, MockLLMClient):
        diagnostics["skipped"] = True
        diagnostics["reason"] = "mock_llm_client"
        return {
            "current_draft": raw,
            "best_draft_content": raw,
            "prose_polish_diagnostics": diagnostics,
        }

    prompt = _build_polish_prompt(raw)
    profile = get_profile("prose_polish")
    try:
        out, res = context.llm_client.invoke_json(prompt, ProsePolishOutput, profile)
        candidate = out.polished_text or ""
    except Exception as exc:
        logger.error("prose_polish llm failed", extra={"extra_payload": {"error": str(exc)}})
        diagnostics["skipped"] = True
        diagnostics["reason"] = f"llm_error:{exc!s}"
        return {
            "current_draft": raw,
            "best_draft_content": raw,
            "prose_polish_diagnostics": diagnostics,
        }

    ok, reason = _polish_passes_gate(
        raw,
        candidate,
        settings.prose_polish_max_relative_length_delta,
        settings.prose_polish_min_similarity_ratio,
    )
    diagnostics["similarity"] = round(_similarity_ratio(raw, candidate), 4)
    diagnostics["length_delta_ratio"] = round(_length_delta_ratio(raw, candidate), 4)

    if not ok:
        diagnostics["gate_rejected"] = True
        diagnostics["gate_reason"] = reason
        logger.warning(
            "prose_polish gate rejected candidate; keeping original",
            extra={"extra_payload": {"reason": reason, **diagnostics}},
        )
        return {
            "current_draft": raw,
            "best_draft_content": raw,
            "prose_polish_diagnostics": diagnostics,
        }

    diagnostics["applied"] = True
    diagnostics["token_usage"] = res.token_usage
    diagnostics["latency_ms"] = res.latency_ms
    diagnostics["change_summary"] = (out.change_summary or "")[:500]
    return {
        "current_draft": candidate,
        "best_draft_content": candidate,
        "prose_polish_diagnostics": diagnostics,
    }
