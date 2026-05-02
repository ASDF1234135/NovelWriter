from __future__ import annotations

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
