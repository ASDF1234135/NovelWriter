from __future__ import annotations

import json


class BibleService:
    def compile_context(self, bible: dict) -> str:
        if not bible:
            return "未提供世界觀設定。"
        return json.dumps(bible, ensure_ascii=False, indent=2)
