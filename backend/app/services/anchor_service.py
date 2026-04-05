from __future__ import annotations

import math
import re
import json
import logging
from typing import Any

from app.domain.schema import (
    MacroCastMember,
    MacroNestedAnchorDraft,
    MacroPlanOutput,
    MacroVolumePlanDraft,
    StateAnchor,
    StoryCastMemberStored,
    StoryCastSeedEntry,
    StoryInput,
    VolumePlan,
)
from app.services.llm import LLMClient, MockLLMClient
from app.services.workflow.constants import MAX_ANCHORS_PER_VOLUME, MIN_ANCHORS_PER_VOLUME
from app.services.workflow.profiles import get_profile

logger = logging.getLogger(__name__)

MACRO_AUTHOR_NOTES_MAX = 8192
CAST_SHORT_BIO_MAX = 500
CAST_MOTIVATION_MAX = 600
CAST_SPEECH_STYLE_MAX = 240
CAST_FATAL_FLAW_MAX = 400
CAST_AGE_MAX = 48
CAST_CORE_MOTIVATION_MAX = 600
CAST_QUIRKS_MAX = 400


def clamp_macro_author_notes(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) <= MACRO_AUTHOR_NOTES_MAX:
        return s
    logger.warning(
        "macro_author_notes truncated for macro prompt",
        extra={"original_len": len(s), "max_len": MACRO_AUTHOR_NOTES_MAX},
    )
    return s[:MACRO_AUTHOR_NOTES_MAX]


def extract_notes_keypoints(raw: str, *, max_keypoints: int = 12) -> list[dict[str, str]]:
    """
    Convert free-form macro_author_notes into deterministic keypoints for enforcement.
    Output format:
      [{"id":"KP1","text":"..."}]
    """
    notes = (raw or "").strip()
    if not notes:
        return []

    # Split by lines first (most common author input format).
    chunks = re.split(r"\r?\n+", notes)
    segments: list[str] = []
    for ch in chunks:
        line = (ch or "").strip()
        if not line:
            continue
        # Remove common bullet prefixes.
        line = re.sub(r"^(\s*[-*•·‧]|^\s*\d+[\.\)]|^\s*\([0-9]+\)\s*)", "", line).strip()
        if not line:
            continue
        # Optional second split by semicolon to reduce overly long lines.
        parts = re.split(r"[；;]", line)
        for p in parts:
            seg = (p or "").strip()
            if not seg:
                continue
            segments.append(seg)

    # Dedupe while preserving order.
    seen: set[str] = set()
    key_texts: list[str] = []
    for seg in segments:
        s = seg.strip()[:200]
        if not s or s in seen:
            continue
        seen.add(s)
        key_texts.append(s)
        if len(key_texts) >= max_keypoints:
            break

    if not key_texts:
        key_texts = [notes[:200]]

    return [{"id": f"KP{i+1}", "text": t} for i, t in enumerate(key_texts)]


def _merge_cast_llm_with_seed(raw: list[MacroCastMember], seeds: list[StoryCastSeedEntry]) -> list[MacroCastMember]:
    """Preserve user seed order; fill from LLM matches; append unmatched LLM members after."""
    if not seeds:
        return list(raw)
    pool = [m for m in raw if (m.canonical_name or "").strip()]
    consumed: set[int] = set()
    by_key: dict[str, list[int]] = {}
    for i, m in enumerate(pool):
        key = m.canonical_name.strip().casefold()
        by_key.setdefault(key, []).append(i)
    merged: list[MacroCastMember] = []
    for seed in seeds:
        key = seed.canonical_name.strip().casefold()
        candidates = [i for i in by_key.get(key, []) if i not in consumed]
        if candidates:
            i = candidates[0]
            consumed.add(i)
            merged.append(pool[i].model_copy(update={"canonical_name": seed.canonical_name.strip()}))
            continue
        role = seed.role or "supporting"
        merged.append(
            MacroCastMember(
                canonical_name=seed.canonical_name.strip(),
                role=role,
                short_bio=(seed.short_hint or "").strip(),
                core_motivation="",
                motivation="",
            )
        )
    for i, m in enumerate(pool):
        if i not in consumed:
            merged.append(m)
    return merged


class AnchorService:
    def compile_macro_plan(
        self, story_id: str, story_input: StoryInput, llm_client: LLMClient | None = None
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, Any]], dict[str, Any]]:
        fixed_total_chapters = max(12, story_input.target_total_words // 2500)
        fixed_total_volumes = max(3, int(math.ceil(story_input.target_total_words / 25000)))
        if llm_client is not None and not isinstance(llm_client, MockLLMClient):
            profile = get_profile("macro_planner")
            notes = clamp_macro_author_notes(story_input.macro_author_notes)
            notes_keypoints = extract_notes_keypoints(notes)
            keypoint_ids = [kp["id"] for kp in notes_keypoints]
            enforce_notes_links = bool(notes.strip()) and bool(keypoint_ids)

            def _validate_notes_links(output: MacroPlanOutput) -> bool:
                if not enforce_notes_links:
                    return True
                for c in output.cast or []:
                    if not c.notes_links:
                        return False
                    if any(nl not in keypoint_ids for nl in (c.notes_links or [])):
                        return False
                for v in output.volumes or []:
                    for a in v.anchors or []:
                        if not a.notes_links:
                            return False
                        if any(nl not in keypoint_ids for nl in (a.notes_links or [])):
                            return False
                return True

            # Retry if the model violates (1) fixed volumes count or (2) notes_links enforcement.
            structured_output: MacroPlanOutput | None = None
            for _attempt in range(2):
                prompt = self._build_macro_prompt(
                    story_input,
                    fixed_total_chapters=fixed_total_chapters,
                    fixed_total_volumes=fixed_total_volumes,
                )
                structured_output, _ = llm_client.invoke_json(prompt, MacroPlanOutput, profile)
                ok_volumes = len(structured_output.volumes or []) == fixed_total_volumes
                ok_notes = _validate_notes_links(structured_output)
                if ok_volumes and ok_notes:
                    break

            if structured_output is None:
                raise RuntimeError("macro_planner produced no structured output")

            # Deterministic fallback for volume count (keep cast + bible from the model).
            if len(structured_output.volumes or []) != fixed_total_volumes:
                structured_output = structured_output.model_copy(
                    update={
                        "volumes": self._fallback_volume_plan_drafts_by_count(
                            story_input=story_input,
                            total_chapters=max(6, fixed_total_chapters),
                            volume_count=fixed_total_volumes,
                            notes_keypoint_ids=keypoint_ids if enforce_notes_links else None,
                        )
                    }
                )

            if enforce_notes_links and not _validate_notes_links(structured_output):
                raise ValueError("macro compile notes_links enforcement failed (cast/anchor missing KP references)")

            return self._normalize_macro_plan(
                story_id, structured_output, fixed_total_chapters, story_input.target_total_words, story_input
            )
        return self._build_mock_macro_plan(story_id, story_input)

    def _build_mock_macro_plan(
        self, story_id: str, story_input: StoryInput
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, Any]], dict[str, Any]]:
        total_chapters = max(12, story_input.target_total_words // 2500)
        volume_breaks = [1, total_chapters // 3, (total_chapters // 3) * 2, total_chapters]
        total_words = max(12_000, story_input.target_total_words)
        budget_one = int(total_words * 0.28)
        budget_two = int(total_words * 0.33)
        budget_three = total_words - budget_one - budget_two

        v1_end = max(4, volume_breaks[1])
        v2_end = max(8, volume_breaks[2])
        v1_start, v1_end = 1, v1_end
        v2_start, v2_end = max(5, volume_breaks[1] + 1), v2_end
        v3_start, v3_end = max(9, volume_breaks[2] + 1), total_chapters

        vol1_drafts = self._default_nested_anchors_for_range(
            "卷一：命運啟動",
            f"建立世界與主角困境，鋪設核心衝突。{story_input.premise}",
            v1_start,
            v1_end,
            beat_prefix="啟程",
        )
        vol2_drafts = self._default_nested_anchors_for_range(
            "卷二：真相逼近",
            "讓角色面對代價，逐步逼近錨點與秘密。",
            v2_start,
            v2_end,
            beat_prefix="逼近",
        )
        vol3_drafts = self._default_nested_anchors_for_range(
            "卷三：決戰與回收",
            "回收伏筆並完成主線收束。",
            v3_start,
            v3_end,
            beat_prefix="終局",
        )

        mock_bible = self._fallback_bible_from_premise(story_input)
        plan = MacroPlanOutput(
            bible=mock_bible,
            cast=[],
            volumes=[
                MacroVolumePlanDraft(
                    title="卷一：命運啟動",
                    summary=f"建立世界與主角困境，鋪設核心衝突。{story_input.premise}",
                    chapter_start=v1_start,
                    chapter_end=v1_end,
                    target_volume_words=budget_one,
                    anchors=vol1_drafts,
                ),
                MacroVolumePlanDraft(
                    title="卷二：真相逼近",
                    summary="讓角色面對代價，逐步逼近錨點與秘密。",
                    chapter_start=v2_start,
                    chapter_end=v2_end,
                    target_volume_words=budget_two,
                    anchors=vol2_drafts,
                ),
                MacroVolumePlanDraft(
                    title="卷三：決戰與回收",
                    summary="回收伏筆並完成主線收束。",
                    chapter_start=v3_start,
                    chapter_end=v3_end,
                    target_volume_words=budget_three,
                    anchors=vol3_drafts,
                ),
            ],
        )
        return self._normalize_macro_plan(story_id, plan, total_chapters, story_input.target_total_words, story_input)

    def _fallback_bible_from_premise(self, story_input: StoryInput) -> dict[str, Any]:
        return {
            "story_genre": "未指定",
            "writing_style": "敘事清晰、節奏穩健",
            "narrative_pov": "第三人稱有限視角",
            "tone": "依 premise 自然延伸",
            "world_rules": ["規則將隨章節展開補齊"],
            "factions": ["依故事自然浮現的勢力"],
            "premise_seed": (story_input.premise or "")[:800],
        }

    def _normalize_generated_bible(self, story_input: StoryInput, output: MacroPlanOutput) -> dict[str, Any]:
        raw = output.bible
        if isinstance(raw, dict) and raw:
            return dict(raw)
        return self._fallback_bible_from_premise(story_input)

    def _default_nested_anchors_for_range(
        self,
        volume_title: str,
        volume_summary: str,
        chapter_start: int,
        chapter_end: int,
        *,
        beat_prefix: str,
    ) -> list[MacroNestedAnchorDraft]:
        span = max(1, chapter_end - chapter_start + 1)
        positions: list[int]
        if span >= 3:
            p1 = chapter_start + max(0, span // 4)
            p2 = chapter_start + max(0, span // 2)
            p3 = chapter_end
            positions = [
                min(max(p1, chapter_start), chapter_end),
                min(max(p2, chapter_start), chapter_end),
                min(max(p3, chapter_start), chapter_end),
            ]
        else:
            positions = [chapter_end, chapter_end, chapter_end]

        templates = [
            (f"{beat_prefix}：局勢推進", f"在《{volume_title}》中段前完成一次可觀的劇情推進。", {"beat": 1}),
            (f"{beat_prefix}：壓力升級", f"角色在《{volume_title}》中面臨更高風險或更強阻力。", {"beat": 2}),
            (f"{beat_prefix}：卷內收束", f"完成《{volume_title}》的階段性目標並銜接下一階段。", {"beat": 3}),
        ]
        return [
            MacroNestedAnchorDraft(
                title=templates[i][0],
                description=templates[i][1],
                target_state=dict(templates[i][2]),
                chapter_target=positions[i],
                priority=i + 1,
            )
            for i in range(3)
        ]

    def _build_macro_prompt(
        self,
        story_input: StoryInput,
        *,
        fixed_total_chapters: int,
        fixed_total_volumes: int,
    ) -> str:
        notes = clamp_macro_author_notes(story_input.macro_author_notes)
        notes_keypoints = extract_notes_keypoints(notes)
        target_chapters_per_volume = fixed_total_chapters / max(1, fixed_total_volumes)
        cast_seed_payload = [s.model_dump(mode="json") for s in story_input.cast_seed]
        cast_req: list[str] = [
            "cast：人數不限，但每位都必須是貫穿主線的核心人物；禁止一次性路人、過渡工具人進入 cast。",
            "全書結構上僅允許 1 位 protagonist、0-1 位 antagonist，其餘為主要 supporting（後端會對重複角色類型做調整）；錨點敘述優先使用 canonical_name。",
        ]
        if cast_seed_payload:
            cast_req.append(
                "cast_seed 為使用者指定的核心名單：其中每個 canonical_name 不得改名、不得合併、不得遺漏；"
                "你仍須為每位補齊 short_bio、core_motivation、notes_links 等欄位；可在不違反上述前提下新增其他核心人物。"
            )
        return json.dumps(
            {
                "title": story_input.title,
                "premise": story_input.premise,
                "macro_author_notes": notes,
                "notes_keypoints": notes_keypoints,
                "cast_seed": cast_seed_payload,
                "target_total_words": story_input.target_total_words,
                "fixed_total_chapters": fixed_total_chapters,
                "fixed_total_volumes": fixed_total_volumes,
                "output_shape": {
                    "bible": {
                        "story_genre": "string",
                        "writing_style": "string",
                        "narrative_pov": "string",
                        "tone": "string",
                        "writing_note": "string[]",
                        "world_rules": "string[]",
                        "factions": "string[]",
                        "extra": "optional object — you may add consistent keys (magic, tech_level, themes, ...)",
                    },
                    "cast": [
                        {
                            "canonical_name": "string",
                            "role": "protagonist | supporting | antagonist",
                            "short_bio": "string",
                            "aliases": "string[] optional",
                            "age": "string optional",
                            "motivation": "string optional (legacy)",
                            "core_motivation": "string — primary drive across the series",
                            "core_value": "string optional — guiding principle / core value",
                            "notes_links": "string[] optional — select from notes_keypoints ids (e.g. KP1, KP2) when macro_author_notes is non-empty",
                            "speech_style": "string optional — sparing verbal tic, not every sentence",
                            "fatal_flaw": "string optional",
                            "quirks_and_habits": "string optional — observable habits, sparing",
                        }
                    ],
                    "initial_b_stories": [
                        {
                            "id": "string",
                            "desc": "string",
                            "type": "BStoryType enum string",
                            "resolution_condition": "string — objective completion criteria",
                        }
                    ],
                    "volumes": [
                        {
                            "title": "string",
                            "summary": "string",
                            "chapter_start": "int",
                            "chapter_end": "int",
                            "target_volume_words": "int",
                            "anchors": [
                                {
                                    "title": "string",
                                    "description": "string",
                                    "target_state": "object",
                                    "chapter_target": "int",
                                    "priority": "int optional",
                                    "notes_links": "string[] optional — select from notes_keypoints ids (e.g. KP1, KP2) when macro_author_notes is non-empty",
                                }
                            ],
                        }
                    ],
                },
                "requirements": [
                    f"總章數固定為 {fixed_total_chapters} 章，必須嚴格依此規劃。",
                    f"總 volumes 固定為 {fixed_total_volumes} 個，必須嚴格依此輸出（不可少/不可多）。",
                    f"每個 volume 的 chapter_start / chapter_end 長度目標約為每卷 {target_chapters_per_volume:.1f} 章（允許小誤差；後端會重整為連續覆蓋）。",
                    "每個 volume 需有連續不重疊的 chapter_start / chapter_end，且涵蓋 1 到總章數。",
                    f"每個 volume 都必須提供 target_volume_words，且所有 volume 的字數總和應接近 {story_input.target_total_words}。",
                    f"**每個 volume 的 anchors 陣列必須含 {MIN_ANCHORS_PER_VOLUME}-{MAX_ANCHORS_PER_VOLUME} 個元素**；"
                    "每個 anchor 的 chapter_target 必須落在該 volume 的 chapter_start 與 chapter_end 之間（含）。",
                    "你必須輸出 bible：具體、可執行，並與 volumes、anchors、cast 一致；可在 bible 內合理擴充額外鍵。",
                    "若 macro_author_notes 非空，bible 與劇情規劃必須尊重其中設定。",
                    "若 macro_author_notes 非空：每個 cast 成員 notes_links 必須為非空陣列，且內容只能選自 notes_keypoints 的 id（如 KP1, KP2）；"
                    "每個 volume anchor notes_links 亦必須為非空陣列，且同樣只能選自 notes_keypoints 的 id。",
                    "每個 anchor 的 target_state 必須具體可追蹤。",
                    "不要把 anchors 放在 volumes 外層；只能嵌套在對應 volume 內。",
                    *cast_req,
                    "initial_b_stories（可選）：僅允許貫穿全書的長線心魔或終極目標拆解；禁止短期戰術任務（如單章找人、開鎖）。每條必含 resolution_condition。",
                    "speech_style / quirks_and_habits 僅作偶爾點綴，不可設計成每句口頭禪。",
                ],
            },
            ensure_ascii=False,
        )

    def _default_cast_drafts(self, story_input: StoryInput) -> list[MacroCastMember]:
        lead = (story_input.title or "").strip()[:64] or "主角"
        return [
            MacroCastMember(
                canonical_name=lead,
                role="protagonist",
                short_bio=(story_input.premise or "")[:240],
                motivation="在當前處境中求存並改變局面。",
                core_motivation="在當前處境中求存並改變局面。",
                core_value="在當下活下去並主動改變局勢。",
            ),
            MacroCastMember(
                canonical_name="主要反派",
                role="antagonist",
                short_bio="與主角目標對立的核心對手。",
                motivation="鞏固自身秩序並壓制主角。",
                core_motivation="鞏固自身秩序並壓制主角。",
                core_value="維持既定秩序並消滅威脅。",
            ),
            MacroCastMember(
                canonical_name="重要配角",
                role="supporting",
                short_bio="與主線密切相關的核心人物。",
                motivation="協助或阻擾主角，推動衝突。",
                core_motivation="協助或阻擾主角，推動衝突。",
                core_value="在風險與選擇間維持自我立場。",
            ),
        ]

    def _normalize_cast_output(
        self, story_id: str, raw: list[MacroCastMember], story_input: StoryInput
    ) -> list[StoryCastMemberStored]:
        filtered = [m for m in (raw or []) if (m.canonical_name or "").strip()]
        if story_input.cast_seed:
            members = _merge_cast_llm_with_seed(filtered, list(story_input.cast_seed))
        else:
            members = list(filtered)
        if not members:
            members = self._default_cast_drafts(story_input)

        coerced_pre: list[MacroCastMember] = []
        for m in members:
            core = (m.core_motivation or "").strip() or (m.motivation or "").strip()
            mot = (m.motivation or "").strip() or core
            coerced_pre.append(m.model_copy(update={"core_motivation": core, "motivation": mot}))
        members = coerced_pre

        if not any(m.role == "protagonist" for m in members):
            members[0] = members[0].model_copy(update={"role": "protagonist"})

        protagonist_seen = False
        antagonist_seen = False
        coerced: list[MacroCastMember] = []
        for m in members:
            role = m.role
            if role == "protagonist":
                if protagonist_seen:
                    role = "supporting"
                else:
                    protagonist_seen = True
            elif role == "antagonist":
                if antagonist_seen:
                    role = "supporting"
                else:
                    antagonist_seen = True
            coerced.append(m.model_copy(update={"role": role}))
        members = coerced

        members.sort(
            key=lambda m: (
                {"protagonist": 0, "antagonist": 1, "supporting": 2}.get(m.role, 2),
                m.canonical_name,
            )
        )

        def _age_str(a: object) -> str:
            if a is None:
                return ""
            if isinstance(a, int | float):
                return str(int(a))[:CAST_AGE_MAX]
            return str(a).strip()[:CAST_AGE_MAX]

        stored: list[StoryCastMemberStored] = []
        for idx, m in enumerate(members, start=1):
            node_id = f"{story_id}_mc_{idx:02d}"
            name = m.canonical_name.strip()
            core = (m.core_motivation or "").strip() or (m.motivation or "").strip()
            core_value = (m.core_value or "").strip() or core
            stored.append(
                StoryCastMemberStored(
                    node_id=node_id,
                    canonical_name=name,
                    role=m.role,
                    short_bio=(m.short_bio or "")[:CAST_SHORT_BIO_MAX],
                    aliases=[a.strip() for a in m.aliases if str(a).strip()][:8],
                    age=_age_str(m.age),
                    motivation=(m.motivation or "")[:CAST_MOTIVATION_MAX] or core[:CAST_MOTIVATION_MAX],
                    core_motivation=core[:CAST_CORE_MOTIVATION_MAX],
                    core_value=core_value[:CAST_CORE_MOTIVATION_MAX],
                    speech_style=(m.speech_style or "")[:CAST_SPEECH_STYLE_MAX],
                    fatal_flaw=(m.fatal_flaw or "")[:CAST_FATAL_FLAW_MAX],
                    quirks_and_habits=(m.quirks_and_habits or "")[:CAST_QUIRKS_MAX],
                )
            )
        return stored

    def _normalize_macro_plan(
        self,
        story_id: str,
        output: MacroPlanOutput,
        fixed_total_chapters: int,
        target_total_words: int,
        story_input: StoryInput,
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, Any]], dict[str, Any]]:
        bible_out = self._normalize_generated_bible(story_input, output)
        total_chapters = max(6, fixed_total_chapters)
        raw_volumes = output.volumes or self._fallback_volume_plan_drafts(total_chapters)
        normalized_drafts = sorted(raw_volumes, key=lambda volume: volume.chapter_start)
        provisional_volumes: list[VolumePlan] = []
        previous_end = 0
        for index, draft in enumerate(normalized_drafts, start=1):
            chapter_start = max(previous_end + 1, draft.chapter_start)
            chapter_end = min(total_chapters, max(chapter_start, draft.chapter_end))
            if index == len(normalized_drafts):
                chapter_end = total_chapters
            provisional_volumes.append(
                VolumePlan(
                    volume_id=f"{story_id}_vol{index}",
                    title=draft.title,
                    summary=draft.summary,
                    chapter_start=chapter_start,
                    chapter_end=chapter_end,
                    target_volume_words=max(0, draft.target_volume_words),
                )
            )
            previous_end = chapter_end

        provisional_volumes[-1].chapter_end = total_chapters
        normalized_budgets = self._normalize_volume_word_budgets(
            provisional_volumes,
            target_total_words=max(12_000, target_total_words),
        )
        volumes = [
            volume.model_copy(update={"target_volume_words": budget})
            for volume, budget in zip(provisional_volumes, normalized_budgets, strict=False)
        ]

        staged: list[tuple[VolumePlan, MacroNestedAnchorDraft]] = []
        for volume, vol_draft in zip(volumes, normalized_drafts, strict=False):
            coerced = self._coerce_volume_anchors(volume, vol_draft.anchors)
            for anchor_draft in coerced:
                staged.append((volume, anchor_draft))

        staged.sort(key=lambda row: (row[1].chapter_target, row[1].priority))
        anchors: list[StateAnchor] = []
        for index, (volume, draft) in enumerate(staged, start=1):
            chapter_target = min(max(draft.chapter_target, volume.chapter_start), volume.chapter_end)
            anchors.append(
                StateAnchor(
                    anchor_id=f"{story_id}_anchor_{index:02d}",
                    story_id=story_id,
                    volume_id=volume.volume_id,
                    title=draft.title,
                    description=draft.description,
                    target_state=draft.target_state,
                    chapter_target=chapter_target,
                    priority=draft.priority,
                )
            )
        cast_stored = self._normalize_cast_output(story_id, output.cast, story_input)
        b_seed: list[dict[str, Any]] = []
        for item in output.initial_b_stories or []:
            bid = str(getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else "") or "").strip()
            if not bid:
                continue
            if isinstance(item, dict):
                desc = str(item.get("desc") or "")[:800]
                typ = str(item.get("type") or "UNKNOWN")
                res = str(item.get("resolution_condition") or "")[:800]
            else:
                desc = str(getattr(item, "desc", "") or "")[:800]
                typ = getattr(item, "type", None)
                typ = typ.value if hasattr(typ, "value") else str(typ or "UNKNOWN")
                res = str(getattr(item, "resolution_condition", "") or "")[:800]
            b_seed.append(
                {
                    "id": bid,
                    "desc": desc,
                    "type": typ,
                    "resolution_condition": res,
                }
            )
        return volumes, anchors, cast_stored, b_seed, bible_out

    def _coerce_volume_anchors(self, volume: VolumePlan, raw: list[MacroNestedAnchorDraft]) -> list[MacroNestedAnchorDraft]:
        clamped: list[MacroNestedAnchorDraft] = []
        for a in sorted(raw, key=lambda x: (x.chapter_target, x.priority)):
            ct = min(max(a.chapter_target, volume.chapter_start), volume.chapter_end)
            clamped.append(a.model_copy(update={"chapter_target": ct}))

        if len(clamped) > MAX_ANCHORS_PER_VOLUME:
            clamped = clamped[:MAX_ANCHORS_PER_VOLUME]

        pad_i = 0
        while len(clamped) < MIN_ANCHORS_PER_VOLUME:
            span = volume.chapter_end - volume.chapter_start + 1
            step = max(1, span // (MIN_ANCHORS_PER_VOLUME + 1))
            ch = volume.chapter_start + (len(clamped) + 1) * step
            ch = min(max(ch, volume.chapter_start), volume.chapter_end)
            clamped.append(
                MacroNestedAnchorDraft(
                    title=f"{volume.title} 補位節點 {pad_i + 1}",
                    description=f"在本卷內第 {ch} 章前後需達成的劇情節點（系統補齊）。",
                    target_state={"volume.placeholder": pad_i + 1},
                    chapter_target=ch,
                    priority=90 + pad_i,
                )
            )
            pad_i += 1

        return clamped

    def _fallback_volume_plan_drafts(self, total_chapters: int) -> list[MacroVolumePlanDraft]:
        split_one = max(4, total_chapters // 3)
        split_two = max(split_one + 3, (total_chapters // 3) * 2)
        v1 = (1, split_one)
        v2 = (split_one + 1, split_two)
        v3 = (split_two + 1, total_chapters)
        return [
            MacroVolumePlanDraft(
                title="卷一：命運啟動",
                summary="建立世界與主角困境，鋪設核心衝突。",
                chapter_start=v1[0],
                chapter_end=v1[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range("卷一：命運啟動", "", v1[0], v1[1], beat_prefix="卷一"),
            ),
            MacroVolumePlanDraft(
                title="卷二：真相逼近",
                summary="讓角色面對代價，逐步逼近錨點與秘密。",
                chapter_start=v2[0],
                chapter_end=v2[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range("卷二：真相逼近", "", v2[0], v2[1], beat_prefix="卷二"),
            ),
            MacroVolumePlanDraft(
                title="卷三：決戰與回收",
                summary="回收伏筆並完成主線收束。",
                chapter_start=v3[0],
                chapter_end=v3[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range("卷三：決戰與回收", "", v3[0], v3[1], beat_prefix="卷三"),
            ),
        ]

    def _fallback_volume_plan_drafts_by_count(
        self,
        *,
        story_input: StoryInput,
        total_chapters: int,
        volume_count: int,
        notes_keypoint_ids: list[str] | None = None,
    ) -> list[MacroVolumePlanDraft]:
        """Deterministic volume segmentation used when the LLM violates fixed volumes constraint."""
        volume_count = max(1, int(volume_count))
        if total_chapters < 1:
            total_chapters = 1

        base = total_chapters // volume_count
        rem = total_chapters % volume_count

        prev_start = 1
        target_per_volume = max(1, int(story_input.target_total_words // max(1, volume_count)))

        out: list[MacroVolumePlanDraft] = []
        for i in range(volume_count):
            length = base + (1 if i < rem else 0)
            ch_start = prev_start
            ch_end = min(total_chapters, ch_start + max(0, length) - 1)
            if ch_end < ch_start:
                ch_end = ch_start

            idx = i + 1
            volume_title = f"卷{idx}：階段推進"
            volume_summary = f"承接前情並推進主題（{story_input.premise[:40]}）。"
            anchors = self._default_nested_anchors_for_range(
                volume_title,
                volume_summary,
                ch_start,
                ch_end,
                beat_prefix=f"卷{idx}",
            )
            if notes_keypoint_ids:
                # Assign at least one keypoint id to each anchor for enforcement.
                anchors = [
                    a.model_copy(update={"notes_links": [notes_keypoint_ids[i % len(notes_keypoint_ids)]]})
                    for i, a in enumerate(anchors)
                ]
            out.append(
                MacroVolumePlanDraft(
                    title=volume_title,
                    summary=volume_summary,
                    chapter_start=ch_start,
                    chapter_end=ch_end,
                    target_volume_words=target_per_volume,
                    anchors=anchors,
                )
            )
            prev_start = ch_end + 1
            if prev_start > total_chapters:
                break

        # If rounding caused fewer volumes, pad by extending the last one.
        if len(out) < volume_count and out:
            out[-1].chapter_end = total_chapters
        return out

    def _normalize_volume_word_budgets(
        self,
        volumes: list[VolumePlan],
        target_total_words: int,
    ) -> list[int]:
        chapter_weights = [
            max(1, volume.chapter_end - volume.chapter_start + 1)
            for volume in volumes
        ]
        requested_weights = [max(0, volume.target_volume_words) for volume in volumes]
        weights = requested_weights if any(requested_weights) else chapter_weights
        total_weight = sum(weights) or sum(chapter_weights) or len(volumes) or 1
        budgets: list[int] = []
        remaining_words = target_total_words
        remaining_weight = total_weight
        for index, weight in enumerate(weights):
            if index == len(weights) - 1:
                budget = max(1, remaining_words)
            else:
                budget = max(1, round(remaining_words * weight / max(1, remaining_weight)))
                remaining_words -= budget
                remaining_weight -= weight
            budgets.append(int(budget))
        return budgets
