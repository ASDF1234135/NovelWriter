from __future__ import annotations

import json


class BibleService:
    def compile_context(self, bible: dict, *, macro_author_notes: str = "") -> str:
        if not bible:
            base = "未提供世界觀設定。"
        else:
            base = json.dumps(bible, ensure_ascii=False, indent=2)
        notes = (macro_author_notes or "").strip()
        if notes:
            return f"{base}\n\n【作者補充設定】\n{notes}"
        return base
