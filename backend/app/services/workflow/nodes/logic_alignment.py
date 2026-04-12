from __future__ import annotations

import json
import re
from typing import Any

from app.domain.schema import AlignmentOutput, HitlReason
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.profiles import get_profile


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
        # 具名智鬥遊戲 / 死亡博弈
        ["俄羅斯輪盤", "博弈", "賭局", "死亡遊戲", "生死遊戲", "規則牌局", "回合制對決"],
        # 資源交易 / 籌碼談判 / 權力制衡
        ["籌碼", "押注", "代價", "交易條件", "交換條件", "談判桌", "制衡", "權力平衡"],
        # exploit / 系統漏洞反殺
        ["漏洞", "exploit", "規則漏洞", "反殺", "逆轉機制", "系統機制", "條款漏洞", "判定漏洞"],
    ]
    if any(any(k.casefold() in lowered for k in group) for group in keyword_groups):
        return True

    # Heuristic: explicit rule-like structures without provided hard rules.
    rule_signals = len(re.findall(r"(規則|條件|勝利條件|失敗條件|判定|回合|結算|懲罰)", text))
    return rule_signals >= 3


def _build_logic_alignment_prompt(state: dict[str, Any]) -> str:
    hard_rules = str(state.get("chapter_hard_rules") or "")
    pov = str(state.get("pov_character_id") or "")
    draft_script = str(state.get("narrative_script") or "")
    draft_beats = list(state.get("must_include_beats") or [])
    draft_events = list(state.get("ground_truth_events") or [])
    boundary = str(state.get("ending_boundary_rule") or "")
    forbidden = list(state.get("forbidden_reveals") or [])

    return (
        "你是邏輯對齊與修補代理（Logic_Alignment_Agent）。\n"
        "你會收到一份『草稿大綱』與一份『本章硬性規則原文』。\n\n"
        "## 絕對優先權（硬性）\n"
        "1) 任何時候『硬性規則』優先於草稿。\n"
        "2) 若草稿行為/破局方式違反硬性規則，你必須修改草稿，使其符合規則。\n"
        "3) 若草稿與規則存在不可修補的根本性衝突：請捨棄草稿中違規的動作，"
        "直接依據規則重新推演一個合理的破局行動，寫入 final_narrative_script。\n\n"
        "## POV 資訊安全（硬性）\n"
        f"- 當前 POV：{pov}\n"
        "- 檢查硬性規則原文：若包含當前 POV 絕對無法知道的上帝視角底牌、真相答案、或內幕，\n"
        "  請用 [系統遮蔽：POV未知] 替換該字眼（保留句子可讀性），並輸出到 safe_chapter_rules。\n\n"
        "## 無縫編織（硬性）\n"
        "- 你必須把規則執行細節『轉成可寫作提示』，安插進 final_must_include_beats，\n"
        "  讓 Author 知道在何時該描寫哪一條規則（例如判定、結算、勝負條件觸發）。\n\n"
        "## 輸出要求（JSON schema）\n"
        "- 請只輸出 AlignmentOutput 所需 JSON。\n"
        "- final_ground_truth_events / final_narrative_script / final_must_include_beats 必須是對齊後可直接交付 Author 的版本。\n"
        "- alignment_log 請用短段落列出你改了哪些地方、因為哪條規則。\n\n"
        "## 🚨 HITL（人類介入）觸發協議：敘事與邏輯守門員\n"
        "請嚴格審視草稿。若草稿的推演跨越了以下「必須由作者親自裁定」的紅線，你必須輸出 requires_hitl=true，"
        "並在 hitl_reason 具體說明你需要作者補充什麼設定。若無以下情況，則 requires_hitl=false 正常放行。\n\n"
        "1) 【機制與權力博弈的黑箱 (Systemic Opaque)】\n"
        "   - 觸發條件：草稿涉及具名的死亡博弈、複雜的資源交易、或利用環境/漏洞（Exploit）進行反殺，但 `chapter_hard_rules` 中未提供支撐此行動的明確勝負條件或物理限制。\n"
        "   - 判斷標準：「如果我不介入，Author 是否會被迫自行編造遊戲規則？」\n\n"
        "2) 【解謎手法的邏輯斷層 (Resolution Logic Gap)】\n"
        "   - 觸發條件：草稿試圖收束一個長線伏筆或解開重大謎團，但主角破解該謎題的「手法」，依賴了本章未定義的機制或現場發明的新設定。\n"
        "   - 行動要求：拒絕「降神式解謎」，要求作者提供主角破解該謎題的具體邏輯或物理限制。\n\n"
        "3) 【機械降神與突兀設定 (Deus Ex Machina Defense)】\n"
        "   - 觸發條件：角色在絕境中突然獲得新能力、新物品，或突然出現背景不明的強大援軍，且在過往劇情中毫無鋪陳。\n\n"
        "4) 【情感與道德的極端臨界點 (Ethical Extremes)】\n"
        "   - 觸發條件：涉及核心角色的死亡、不可挽回的背叛、或極端道德困境。\n"
        "   - 判斷標準：確認這是否是作者的本意，防止 AI 擅自用「廉價的和解」稀釋劇情張力。\n\n"
        "## 草稿大綱（待對齊）\n"
        f"- draft_ground_truth_events: {json.dumps(draft_events, ensure_ascii=False)[:6000]}\n"
        f"- draft_narrative_script:\n{_clip(draft_script, 8000)}\n\n"
        f"- draft_must_include_beats: {json.dumps(draft_beats, ensure_ascii=False)[:2000]}\n\n"
        "## 本章硬性規則原文（必須保真；若有 POV 暴雷需遮蔽後輸出）\n"
        f"{_clip(hard_rules, 8000)}\n\n"
        "## 章末邊界（參考）\n"
        f"{_clip(boundary, 800)}\n\n"
        "## 禁止揭露（參考）\n"
        f"{json.dumps(forbidden, ensure_ascii=False)[:1200]}\n"
    )


def run_logic_alignment(
    state: dict,
    context: WorkflowContext,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    hard_rules = str(state.get("chapter_hard_rules") or "").strip()

    # Short-circuit: no hard rules.
    if not hard_rules:
        requires_hitl = _looks_like_complex_mind_game(state)
        reason = None
        log = "Skipped: No hard rules provided."
        if requires_hitl:
            reason = (
                "草稿包含高複雜智鬥元素，但缺少可執行硬性規則。"
                "請補充勝負條件、回合/判定流程、籌碼/代價與可用策略邊界。"
            )
            log = "Paused: Missing hard rules for complex mind-game draft."
        out: dict[str, Any] = {
            "safe_chapter_rules": "",
            "alignment_log": log,
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
    }
    prompt = _build_logic_alignment_prompt(state)

    if isinstance(context.llm_client, MockLLMClient):
        out = AlignmentOutput(
            final_ground_truth_events=[],
            final_narrative_script=str(state.get("narrative_script") or ""),
            final_must_include_beats=list(state.get("must_include_beats") or []),
            safe_chapter_rules=hard_rules,
            alignment_log="Mock: passthrough (no rule enforcement).",
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

