from __future__ import annotations

import json

from app.domain.story_runtime import bible_user_view
from app.services.workflow.bible_general_lore import effective_general_world_lore


class BibleService:
    def compile_context(self, bible: dict, *, macro_author_notes: str = "") -> str:
        lore = effective_general_world_lore(bible or {})
        if lore:
            base = "## World lore\n\n" + lore
        else:
            base = "未提供世界觀設定。"
        notes = (macro_author_notes or "").strip()
        if notes:
            return f"{base}\n\n【作者補充設定】\n{notes}"
        return base

    def compile_full_context(self, bible: dict, *, macro_author_notes: str = "") -> str:
        """Full bible for chapter agents: world lore markdown + user bible JSON + author notes."""
        lore = effective_general_world_lore(bible or {})
        if lore:
            parts = ["## World lore", "", lore, ""]
        else:
            parts = ["## World lore", "", "未提供世界觀設定。", ""]
        user_bible = bible_user_view(bible)
        if user_bible:
            parts.extend(
                [
                    "## Bible (user fields, JSON)",
                    "",
                    json.dumps(user_bible, ensure_ascii=False, indent=2),
                    "",
                ]
            )
        notes = (macro_author_notes or "").strip()
        if notes:
            parts.extend(["【作者補充設定】", notes])
        return "\n".join(parts).strip()
