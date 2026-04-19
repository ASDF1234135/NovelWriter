"""Pure helpers for chapter-to-chapter pacing constraints (shared by workflow state and writing preamble)."""

from __future__ import annotations


def chapter_distance_to_anchor(chapter_id: int, unachieved_anchors: list[dict]) -> int | None:
    if not unachieved_anchors:
        return None
    ct = unachieved_anchors[0].get("chapter_target")
    if ct is None:
        return None
    try:
        return int(ct) - int(chapter_id)
    except (TypeError, ValueError):
        return None


def build_resolution_cooldown_constraint(recent_summaries: list[dict]) -> dict:
    methods = [str((row or {}).get("resolution_method") or "").strip().upper() for row in recent_summaries if row]
    methods = [m for m in methods if m]
    if len(methods) < 3:
        return {"active": False, "forbidden_methods": [], "mandatory_methods": []}
    forbidden_pool = {"DISCOVERY", "REVELATION", "DECEPTION"}
    if len(set(methods[-3:])) == 1 and methods[-1] in forbidden_pool:
        return {
            "active": True,
            "forbidden_methods": list(sorted(forbidden_pool)),
            "mandatory_methods": ["NEGOTIATION", "VIOLENCE", "ESCAPE", "ALLIANCE"],
            "ban_text": (
                "偵測到連續章節重複使用精神/資訊直取式破局手段。"
                "本章嚴禁再次使用精神連結、神經駭入、純資訊直讀。"
                "本章衝突解決必須改用物理潛行、環境機關利用、談判欺詐或暴力奪取。"
            ),
        }
    return {"active": False, "forbidden_methods": [], "mandatory_methods": []}


def build_ending_vibe_cooldown_constraint(recent_summaries: list[dict]) -> dict:
    vibes = [str((row or {}).get("ending_vibe") or "").strip().upper() for row in recent_summaries if row]
    vibes = [v for v in vibes if v]
    if not vibes:
        return {"active": False, "forbidden_vibes": [], "required_vibe": None}
    if vibes[-1] == "SAFE_ROOM_EXPOSITION":
        return {
            "active": True,
            "forbidden_vibes": ["SAFE_ROOM_EXPOSITION"],
            "required_vibe": "ACTION_CLIFFHANGER",
            "interrupt_text": (
                "不要讓角色再次進入安全密室做總結對話。"
                "本章結尾必須是 ACTION_CLIFFHANGER，並在門關上後立刻出現新威脅。"
            ),
        }
    return {"active": False, "forbidden_vibes": [], "required_vibe": None}
