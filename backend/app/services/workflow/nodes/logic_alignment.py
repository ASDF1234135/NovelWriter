from __future__ import annotations

import json
import re
from typing import Any

from app.domain.schema import AlignmentOutput, HitlReason
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile

LOGIC_ALIGN_BIBLE_CAP = 4500
LOGIC_ALIGN_GRAPH_CAP = 3500
LOGIC_ALIGN_VECTOR_CAP = 2500


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "")
    return t if len(t) <= max_chars else t[:max_chars]


def _looks_like_complex_mind_game(state: dict[str, Any]) -> bool:
    script = str(state.get("narrative_script") or "")
    beats = " ".join(str(x) for x in (state.get("must_include_beats") or []))
    events = " ".join(str((e or {}).get("description") or "") for e in (state.get("ground_truth_events") or []))
    text = f"{script}\n{beats}\n{events}"
    if not text.strip():
        return False
    lowered = text.casefold()

    keyword_groups: list[list[str]] = [
        ["俄羅斯輪盤", "博弈", "賭局", "死亡遊戲", "生死遊戲", "規則牌局", "回合制對決"],
        ["籌碼", "押注", "代價", "交易條件", "交換條件", "談判桌", "制衡", "權力平衡"],
        ["漏洞", "exploit", "規則漏洞", "反殺", "逆轉機制", "系統機制", "條款漏洞", "判定漏洞"],
    ]
    if any(any(k.casefold() in lowered for k in group) for group in keyword_groups):
        return True

    rule_signals = len(re.findall(r"(規則|條件|勝利條件|失敗條件|判定|回合|結算|懲罰)", text))
    return rule_signals >= 3


def _should_run_canon_audit(state: dict[str, Any]) -> bool:
    outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    if len(outline) >= 20:
        return True
    if len(str(state.get("graph_context") or "").strip()) > 80:
        return True
    if len(str(state.get("bible_context") or "").strip()) > 80:
        return True
    if len(str(state.get("vector_context") or "").strip()) > 80:
        return True
    return False


def _build_logic_alignment_prompt(state: dict[str, Any]) -> str:
    hard_rules = str(state.get("chapter_hard_rules") or "")
    has_hard = bool(hard_rules.strip())
    pov = str(state.get("pov_character_id") or "")
    draft_script = str(state.get("narrative_script") or "")
    draft_beats = list(state.get("must_include_beats") or [])
    draft_events = list(state.get("ground_truth_events") or [])
    boundary = str(state.get("ending_boundary_rule") or "")
    forbidden = list(state.get("forbidden_reveals") or [])
    human_outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    bible = _clip(str(state.get("bible_context") or ""), LOGIC_ALIGN_BIBLE_CAP)
    graph = _clip(str(state.get("graph_context") or ""), LOGIC_ALIGN_GRAPH_CAP)
    vector = _clip(str(state.get("vector_context") or ""), LOGIC_ALIGN_VECTOR_CAP)

    hard_block = (
        "## 本章硬性規則原文（必須保真；若有 POV 暴雷需遮蔽後輸出）\n"
        f"{_clip(hard_rules, 8000)}\n\n"
        if has_hard
        else (
            "## 本章硬性規則原文\n"
            "（作者未提供 chapter_hard_rules；請勿臆造規則。safe_chapter_rules 可輸出空字串。）\n\n"
        )
    )

    rules_priority = (
        "## 絕對優先權（硬性規則存在時）\n"
        "1) 『硬性規則』優先於草稿。\n"
        "2) 若草稿違反硬性規則，修改 final_* 使其符合規則。\n"
        "3) 若根本性衝突無法修補：捨棄違規動作，依規則重推演合理行動。\n\n"
        if has_hard
        else (
            "## 無硬性規則時\n"
            "- 預設 final_ground_truth_events / final_narrative_script / final_must_include_beats 與草稿一致，"
            "除非與下方 bible／graph／vector 或人類大綱存在**硬衝突**且你能給出**最小必要修正**。\n"
            "- 仍必須填寫 human_outline_conflict_notes：列出人類大綱或草稿與設定證據的牴觸（無則 []）。\n"
            "- 區分：純 Planner 腦補問題 vs 人類原文即與 canon 衝突；後者須在 hitl_reason 或衝突條目中寫清。\n"
            "- 無法調和的核心世界規則衝突：requires_hitl=true。\n\n"
        )
    )

    pov_block = (
        "## POV 資訊安全（硬性規則存在時）\n"
        f"- 當前 POV：{pov}\n"
        "- 檢查硬性規則原文：若含 POV 不可知的上帝視角，請用 [系統遮蔽：POV未知] 替換並寫入 safe_chapter_rules。\n\n"
        if has_hard
        else ""
    )

    weave_block = (
        "## 無縫編織（硬性規則存在時）\n"
        "- 把規則執行細節轉成可寫作提示，安插進 final_must_include_beats。\n\n"
        if has_hard
        else ""
    )

    return (
        "你是邏輯對齊與修補代理（Logic_Alignment_Agent）：吃書稽核員與降神攔截器。\n"
        "比對『人類大綱 + Planner 草稿』與 bible／graph／vector 記憶；違反聖經、邏輯死結、未解釋機械降神 → 要求 HITL 或修正。\n"
        "無論大綱是人類寫的還是 Planner 補充的，只要違反已建立的設定證據，須列入 human_outline_conflict_notes，不得略過不報。\n\n"
        f"{rules_priority}"
        f"{pov_block}"
        f"{weave_block}"
        "## 設定與檢索記憶（強制比對）\n"
        f"- bible_context:\n{bible}\n\n"
        f"- graph_context:\n{graph}\n\n"
        f"- vector_context:\n{vector}\n\n"
        "## 人類本章大綱（原文）\n"
        f"{_clip(human_outline, 2000) if human_outline else '（無）'}\n\n"
        "## 草稿大綱（待對齊）\n"
        f"- draft_ground_truth_events: {json.dumps(draft_events, ensure_ascii=False)[:6000]}\n"
        f"- draft_narrative_script:\n{_clip(draft_script, 8000)}\n\n"
        f"- draft_must_include_beats: {json.dumps(draft_beats, ensure_ascii=False)[:2000]}\n\n"
        f"{hard_block}"
        "## 章末邊界（參考）\n"
        f"{_clip(boundary, 800)}\n\n"
        "## 禁止揭露（參考）\n"
        f"{json.dumps(forbidden, ensure_ascii=False)[:1200]}\n\n"
        "## 輸出要求（JSON / AlignmentOutput）\n"
        "- human_outline_conflict_notes：字串陣列，逐條說明衝突（人類主張 vs 證據來源）。軟張力可列在此；硬衝突應 requires_hitl。\n"
        "- alignment_log：簡述修改與原因；若未改草稿，說明已審核無需修正。\n"
        "- final_* 必須是可交付 Author 的版本。\n\n"
        "## HITL 紅線（與硬性規則並列；有則 requires_hitl）\n"
        "1) 複雜智鬥／博弈但無可執行硬性規則支撐。\n"
        "2) 解謎依賴本章未定義機制。\n"
        "3) 機械降神：新能力／援軍無鋪墊且與圖譜記憶牴觸。\n"
        "4) 人類大綱**原文**與 bible／graph 決定性矛盾且無法自動調和。\n"
        "5) 極端道德／核心死亡等需作者確認。\n"
    )


def run_logic_alignment(
    state: dict,
    context: WorkflowContext,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    hard_rules = str(state.get("chapter_hard_rules") or "").strip()

    if not hard_rules:
        if not _should_run_canon_audit(state):
            requires_hitl = _looks_like_complex_mind_game(state)
            reason = None
            log = "Skipped: No hard rules and no canon-audit context."
            if requires_hitl:
                reason = (
                    "草稿包含高複雜智鬥元素，但缺少可執行硬性規則。"
                    "請補充勝負條件、回合/判定流程、籌碼/代價與可用策略邊界。"
                )
                log = "Paused: Missing hard rules for complex mind-game draft."
            out: dict[str, Any] = {
                "safe_chapter_rules": "",
                "alignment_log": log,
                "human_outline_conflict_notes": [],
                "requires_hitl": requires_hitl,
                "hitl_reason": reason,
            }
            payload: dict[str, Any] = {
                "chapter_id": state.get("chapter_id"),
                "pov_character_id": state.get("pov_character_id"),
                "skipped": True,
                "complex_draft_detected": requires_hitl,
            }
            return out, payload, 0, 0

    payload = {
        "chapter_id": state.get("chapter_id"),
        "pov_character_id": state.get("pov_character_id"),
        "draft_ground_truth_events": list(state.get("ground_truth_events") or []),
        "draft_narrative_script": str(state.get("narrative_script") or ""),
        "draft_must_include_beats": list(state.get("must_include_beats") or []),
        "chapter_hard_rules": _clip(hard_rules, 8000),
        "chapter_outline": _clip(str(state.get("chapter_outline") or ""), 2000),
    }
    prompt = _build_logic_alignment_prompt(state)

    if isinstance(context.llm_client, MockLLMClient):
        out = AlignmentOutput(
            final_ground_truth_events=[],
            final_narrative_script=str(state.get("narrative_script") or ""),
            final_must_include_beats=list(state.get("must_include_beats") or []),
            safe_chapter_rules=hard_rules,
            alignment_log="Mock: passthrough (no rule enforcement).",
            human_outline_conflict_notes=[],
            requires_hitl=False,
            hitl_reason=None,
        ).model_dump(mode="json")
        return out, payload, 0, 0

    profile = get_profile("logic_alignment")
    structured, res = context.llm_client.invoke_json(prompt, AlignmentOutput, profile)
    dumped = structured.model_dump(mode="json")
    if dumped.get("requires_hitl") and not dumped.get("hitl_reason"):
        dumped["hitl_reason"] = HitlReason.ALIGNMENT_RULES_REQUIRED
    return dumped, payload, res.token_usage, res.latency_ms
