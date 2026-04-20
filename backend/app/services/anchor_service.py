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
from app.core.config import get_settings
from app.services.llm import LLMClient, MockLLMClient
from app.services.workflow.constants import MAX_ANCHORS_PER_VOLUME, MIN_ANCHORS_PER_VOLUME
from app.services.workflow.output_language import (
    OUTPUT_LANGUAGE_LABEL,
    augment_profile_system_prompt,
    default_chapter_target_words,
    normalize_output_language,
)
from app.services.workflow.profiles import get_profile

logger = logging.getLogger(__name__)
_BIBLE_PRIMARY_OPTIONAL_KEYS = frozenset({"theme", "narrative_pov", "writing_style"})

# Heuristic: codepoints that usually indicate Traditional Chinese when Mainland Simplified is required.
# (Distinct from common simplified forms; intentionally biased toward high-frequency editorial variants.)
_CJK_TRADITIONAL_STRONG_CHARS = frozenset(
    "這與國時會說對從種經長門問間題關聽見個們體員為點應該計記認護達遠運邊選過開來還裡麼"
    "騎號雖電龍鳥魚馬顯頭願風飛養聲壓夠婦屆層幫幹廣廳後徵復徹懲憑慮據擇擊擴擾攜敵數斷"
    "晝曆東極樣機檢歡歲殘殺氣汙決沒況洩洶涼淚淺測湧滯漸潛潔災無煙熱燙爭狀狹獲獸獻獵環"
    "畫當疊確碼磚祕祿禮禱禦禪離積穩竊竄筆節範簽籃籌紛納紐純終絕給網緊緣總縱繁織繪繼續"
    "罰罷羅義習職聰聯節點敘稱線審攤鑲鐘鐵銀銅錢鎖鏡鐵鑰門閱開關閣隊階際陳險隱霧靜韋頂顆題額顏顫"
    "餵館餅養餘駕騰騷驗驅驅體鬥鬧魘鴉鴿麗黨齡齊龍龜"
)
# Heuristic: simplified-preferring codepoints when Traditional Chinese is required (unified zh-Hant).
_CJK_SIMPLIFIED_STRONG_CHARS = frozenset(
    "这国时说对从种经长门问间题关听见个们体员为点应该计记认护达远运边选过来还里么"
    "专东丝严丧临举义乐乡亿仅众优伞伟传伦伪侠侦侨俭债倾储兰兴养冲决况冻净凉凑凛凯击划刘创删剑劲勋"
    "华卖卢历厉压厌厕县参变叽吗听呐呜咙唤啧啬啮啸团围圆圣坏块坚坛坞垦堕墙增壳壶复够夹奥妇姗婴妈婆"
    "寻导将尔岁帮庆庐库庙庞异张弹强彦彻径忧怀恳恶悬悯惊惕惫惩惭惮愤憋懒护择挝拣拥拨挣挤挥捞损换捣"
    "握掷掺揽敌敛斋斑斩断旷显曾朋服望期杨杰极构枪枫柜柠标栈栋栏树桦检棱椰概榆榈槽樊樟横樱橄橇橙橘"
    "檐橱毡毯毽汇汉污汹泛泞泽洁测浒浓浦涝润涧涨淑淌淬淡深混淹渠渗温渴渺湿溃溅溉滥滩滚滞澳激灌灭灯"
    "灵灶炖炮炼烁炽烛烘烩烬烫焊焕焖焘爷牍牺犁犊狎狈狭狮狱猎猕猜猪猬献獭玛环现琐琼瓯畅畴疗疟疡疮疯"
    "痪痹瘟瘤癣皑皱盏盐监盖盗盘睐睑睛瞄矫矶矿码砥砾础确硷碍碑碰碱祸禅秃秆秽穷窍窑筑筒筛箩篓简签篮"
    "篱粮粱粹系紧累絷纠纽纺绑绒结绘绚络绝绞绢综绽缀缕编缭缮缰缴网罗罚罢羟翘翻耆聊聪联聋肾胀胆胜脉"
    "胰脏胳脐脑脓脸腾腰腺腮膛舒舔舜舞航般舵舶舫艇艰艳艺节芦芜苇苞荨荡荫荧莺萨落蓝蓟蕴蘑虏虑虾蚂蚀"
    "蚱蚌蝇融衅衔补衬袜袭裆裢裤褛褴见观规觅视览觉觑觇计订讣认讨讪训议记讲讶许讹论讽设访诀证评识诉"
    "诊试诗诚话诞诠询该详诫诬诱请诺读课谁调谅谈谊谋谐谓谚谢谣谦谨谩谭谱谴贞负贡财责贤败账质贩贫购贯"
    "贰贱贴贻贼贿赁赂赃赊赋赌赎赐赔赖赘赚赛赞赠赡赢赵赶趋趟趴践跷跃跄踢踩踱蹿躯轧轨转轮软轰轴轻载轿"
    "较辆辈辉辊辍辐辑辕辙辽达迁过迈运进远违连迟适逊递逻遗遥邀邪邮邹郑郸酝酱酿醋释鉴钙钝钞钠钥钧钩钾"
    "铀铁铂铃铄铅铆铲银铸铺链销锁锐错锚锤锥锨键锯锹锻镇镐镰镶闸闹闺闽阀阁阂阅阔阚阴阵际陨险隐雾静靥"
    "韦韧韩韵颂预领颗颚额颤飞饵馆馈馔驮驱验骏骑骚"
)

MACRO_AUTHOR_NOTES_MAX = 8192
CAST_SHORT_BIO_MAX = 500
CAST_PERSONALITY_MAX = 600
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
                personality="",
            )
        )
    for i, m in enumerate(pool):
        if i not in consumed:
            merged.append(m)
    return merged


class AnchorService:
    @staticmethod
    def _macro_chapter_unit_and_words_per_volume(story_input: StoryInput) -> tuple[int, int]:
        settings = get_settings()
        ol = normalize_output_language(story_input.output_language)
        if ol == "en":
            chapter_unit = max(1, int(settings.macro_english_chapter_unit))
        else:
            chapter_unit = max(1, default_chapter_target_words(ol))
        words_per_volume = max(1, int(settings.macro_chapters_per_volume) * chapter_unit)
        return chapter_unit, words_per_volume

    def compile_macro_plan(
        self, story_id: str, story_input: StoryInput, llm_client: LLMClient | None = None
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, Any]], dict[str, Any]]:
        chapter_unit, words_per_volume = self._macro_chapter_unit_and_words_per_volume(story_input)
        fixed_total_chapters = max(12, story_input.target_total_words // chapter_unit)
        fixed_total_volumes = max(3, int(math.ceil(story_input.target_total_words / words_per_volume)))
        if llm_client is not None and not isinstance(llm_client, MockLLMClient):
            profile = augment_profile_system_prompt(
                get_profile("macro_planner"), story_input.output_language
            )
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

            def _validate_output_language(output: MacroPlanOutput) -> str | None:
                return self._detect_macro_output_language_mismatch(output, story_input.output_language)

            # Retry if the model violates (1) fixed volumes count or (2) notes_links enforcement.
            structured_output: MacroPlanOutput | None = None
            language_mismatch_detail: str | None = None
            for _attempt in range(2):
                prompt = self._build_macro_prompt(
                    story_input,
                    fixed_total_chapters=fixed_total_chapters,
                    fixed_total_volumes=fixed_total_volumes,
                )
                if language_mismatch_detail:
                    prompt = (
                        f"{prompt}\n\n"
                        "Previous output violated the configured output language requirement. "
                        f"Rewrite all natural-language values so they are entirely in "
                        f"{OUTPUT_LANGUAGE_LABEL.get(normalize_output_language(story_input.output_language), 'the configured language')}. "
                        f"Issue: {language_mismatch_detail}"
                    )
                structured_output, _ = llm_client.invoke_json(prompt, MacroPlanOutput, profile)
                ok_volumes = len(structured_output.volumes or []) == fixed_total_volumes
                ok_notes = _validate_notes_links(structured_output)
                language_mismatch_detail = _validate_output_language(structured_output)
                if ok_volumes and ok_notes and language_mismatch_detail is None:
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
            final_language_mismatch = _validate_output_language(structured_output)
            if final_language_mismatch:
                raise ValueError(f"macro compile output language mismatch: {final_language_mismatch}")

            return self._normalize_macro_plan(
                story_id, structured_output, fixed_total_chapters, story_input.target_total_words, story_input
            )
        return self._build_mock_macro_plan(story_id, story_input)

    @staticmethod
    def _is_cjk_letter(ch: str) -> bool:
        if len(ch) != 1:
            return False
        o = ord(ch)
        return (0x3400 <= o <= 0x4DBF) or (0x4E00 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF)

    def _script_letter_counts(self, text: str) -> tuple[int, int]:
        cjk = 0
        latin = 0
        for ch in text:
            if ch.isascii() and ch.isalpha():
                latin += 1
            elif ch.isalpha() and self._is_cjk_letter(ch):
                cjk += 1
        return cjk, latin

    def _collect_macro_output_text(self, output: MacroPlanOutput) -> str:
        parts: list[str] = []

        def _walk(value: Any) -> None:
            if isinstance(value, str):
                s = value.strip()
                if s:
                    parts.append(s)
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for v in value:
                    _walk(v)

        _walk(output.model_dump(mode="json"))
        return "\n".join(parts)

    def _detect_macro_output_language_mismatch(self, output: MacroPlanOutput, output_language: str) -> str | None:
        text = self._collect_macro_output_text(output)
        if len(text) < 80:
            return None
        norm = normalize_output_language(output_language)
        cjk, latin = self._script_letter_counts(text)
        total = cjk + latin
        if total < 40:
            return None
        cjk_ratio = cjk / total
        if norm == "en":
            if cjk >= 24 and cjk_ratio >= 0.22:
                return f"expected English but counted many CJK letters ({cjk} CJK, {latin} Latin; ratio {cjk_ratio:.0%})."
            return None
        if norm in ("zh-Hant", "zh-Hans"):
            # Structured JSON still carries English role tokens and anchor codes (e.g. protagonist, "v1"),
            # which inflate Latin counts; do not treat as mismatch if prose-scale CJK is clearly present.
            if latin >= 90 and cjk_ratio <= 0.14 and cjk < 45:
                return (
                    f"expected {OUTPUT_LANGUAGE_LABEL.get(norm, norm)} but output looks mostly Latin "
                    f"({cjk} CJK, {latin} Latin; ratio {cjk_ratio:.0%})."
                )
            if norm == "zh-Hans":
                trad = self._zh_hans_traditional_script_mismatch(text, cjk)
                if trad:
                    return trad
            elif norm == "zh-Hant":
                simp = self._zh_hant_simplified_script_mismatch(text, cjk)
                if simp:
                    return simp
            return None
        return None

    @staticmethod
    def _zh_hans_traditional_script_mismatch(text: str, cjk: int) -> str | None:
        if cjk < 28:
            return None
        hits = sum(1 for ch in text if ch in _CJK_TRADITIONAL_STRONG_CHARS)
        ratio = hits / cjk
        if hits >= 14 and ratio >= 0.025:
            return (
                "expected Simplified Chinese but output contains many Traditional-form CJK characters "
                f"({hits} likely-Traditional indicators in {cjk} CJK letters, ~{ratio:.1%})."
            )
        if hits >= 28:
            return (
                "expected Simplified Chinese but output contains many Traditional-form CJK characters "
                f"({hits} likely-Traditional indicators in {cjk} CJK letters)."
            )
        return None

    @staticmethod
    def _zh_hant_simplified_script_mismatch(text: str, cjk: int) -> str | None:
        if cjk < 28:
            return None
        hits = sum(1 for ch in text if ch in _CJK_SIMPLIFIED_STRONG_CHARS)
        ratio = hits / cjk
        if hits >= 14 and ratio >= 0.025:
            return (
                "expected Traditional Chinese but output contains many Simplified-form CJK characters "
                f"({hits} likely-Simplified indicators in {cjk} CJK letters, ~{ratio:.1%})."
            )
        if hits >= 28:
            return (
                "expected Traditional Chinese but output contains many Simplified-form CJK characters "
                f"({hits} likely-Simplified indicators in {cjk} CJK letters)."
            )
        return None

    def _build_mock_macro_plan(
        self, story_id: str, story_input: StoryInput
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, Any]], dict[str, Any]]:
        chapter_unit, words_per_volume = self._macro_chapter_unit_and_words_per_volume(story_input)
        total_chapters = max(12, story_input.target_total_words // chapter_unit)
        fixed_total_volumes = max(3, int(math.ceil(story_input.target_total_words / words_per_volume)))
        volume_drafts = self._fallback_volume_plan_drafts_by_count(
            story_input=story_input,
            total_chapters=total_chapters,
            volume_count=fixed_total_volumes,
            notes_keypoint_ids=None,
        )
        mock_bible = self._fallback_bible_from_premise(story_input)
        plan = MacroPlanOutput(
            bible=mock_bible,
            cast=[],
            volumes=volume_drafts,
        )
        return self._normalize_macro_plan(story_id, plan, total_chapters, story_input.target_total_words, story_input)

    def _fallback_bible_from_premise(self, story_input: StoryInput) -> dict[str, Any]:
        return {
            "story_genre": "unspecified",
            "writing_style": "clear narration, steady pacing",
            "narrative_pov": "third-person limited",
            "tone": "derive naturally from premise",
            "world_rules": ["Rules will be refined as chapters progress"],
            "factions": ["Factions emerge naturally from the story"],
            "premise_seed": (story_input.premise or "")[:800],
        }

    def _normalize_generated_bible(self, story_input: StoryInput, output: MacroPlanOutput) -> dict[str, Any]:
        raw = output.bible
        if isinstance(raw, dict) and raw:
            out = dict(raw)
            if "theme" not in out and "themes" in out:
                out["theme"] = out.get("themes")
            out.pop("themes", None)
            extra_raw = out.get("extra")
            if isinstance(extra_raw, dict):
                extra_clean = {k: v for k, v in extra_raw.items() if k not in _BIBLE_PRIMARY_OPTIONAL_KEYS}
                out["extra"] = extra_clean
            return out
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
            (f"{beat_prefix}: Push the board", f"Before the midpoint of “{volume_title}”, land one clear plot advance.", {"beat": 1}),
            (f"{beat_prefix}: Raise the pressure", f"Inside “{volume_title}”, expose the cast to higher risk or stronger opposition.", {"beat": 2}),
            (f"{beat_prefix}: Close the volume beat", f"Hit a volume-scale milestone in “{volume_title}” and hand off to the next phase.", {"beat": 3}),
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
            "cast: any headcount, but everyone listed must be core to the spine across the series - no one-off walk-ons or pure transition tools.",
            "Globally allow exactly 1 protagonist, 0–1 antagonist, with the remainder as major supporting (backend may coerce duplicate role labels); prefer canonical_name in anchor prose.",
        ]
        if cast_seed_payload:
            cast_req.append(
                "cast_seed is the user's locked core roster: every canonical_name must be preserved (no renames, merges, or omissions); "
                "still enrich each row with short_bio, core_motivation, notes_links, etc.; you may add other core figures without breaking those constraints."
            )
        ol = normalize_output_language(story_input.output_language)
        script_shape_req: list[str] = []
        if ol == "zh-Hans":
            script_shape_req.append(
                "Author text in title / premise / macro_author_notes may be Traditional Chinese, mixed script, or Latin; "
                "still write every JSON string in Mainland China normative Simplified Chinese (大陆规范简体字). "
                "Do not mirror the author's Traditional character forms."
            )
        elif ol == "zh-Hant":
            script_shape_req.append(
                "Author text may be Simplified Chinese, mixed, or Latin; unify every JSON string to standard Traditional Chinese (繁體中文) for this story. "
                "Avoid simplified-only character forms where Traditional orthography differs from Simplified."
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
                        "extra": "optional object - custom world metadata only; do not duplicate theme / narrative_pov / writing_style here",
                    },
                    "cast": [
                        {
                            "canonical_name": "string",
                            "role": "protagonist | supporting | antagonist",
                            "short_bio": "string",
                            "aliases": "string[] optional",
                            "age": "string optional",
                            "personality": "string optional",
                            "core_motivation": "string - primary drive across the series",
                            "core_value": "string optional - guiding principle / core value",
                            "notes_links": "string[] optional - select from notes_keypoints ids (e.g. KP1, KP2) when macro_author_notes is non-empty",
                            "speech_style": "string optional - sparing verbal tic, not every sentence",
                            "fatal_flaw": "string optional",
                            "quirks_and_habits": "string optional - observable habits, sparing",
                        }
                    ],
                    "initial_b_stories": [
                        {
                            "id": "string",
                            "desc": "string",
                            "type": "BStoryType enum string",
                            "resolution_condition": "string - objective completion criteria",
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
                                    "notes_links": "string[] optional - select from notes_keypoints ids (e.g. KP1, KP2) when macro_author_notes is non-empty",
                                }
                            ],
                        }
                    ],
                },
                "requirements": [
                    f"Total chapters is fixed at {fixed_total_chapters}; plan strictly to that count.",
                    f"Total volumes is fixed at {fixed_total_volumes}; emit exactly that many (no fewer, no more).",
                    f"Each volume's chapter_start/chapter_end span should target ~{target_chapters_per_volume:.1f} chapters on average (small drift OK; backend will re-normalize continuous coverage).",
                    "Each volume must have contiguous, non-overlapping chapter_start/chapter_end ranges covering 1 through total chapters.",
                    f"Each volume must include target_volume_words, and the sum across volumes should approximate {story_input.target_total_words}.",
                    f"**Each volume anchors array must contain {MIN_ANCHORS_PER_VOLUME}-{MAX_ANCHORS_PER_VOLUME} items**; "
                    "each anchor.chapter_target must fall between that volume's chapter_start and chapter_end (inclusive).",
                    "You must output bible: concrete, executable, and consistent with volumes, anchors, and cast; you may add reasonable extra keys inside bible.",
                    "theme / narrative_pov / writing_style are optional bible top-level fields - if present, place them at bible root, not inside extra.",
                    "extra may only hold other supplemental keys; do not duplicate theme / narrative_pov / writing_style (backend will drop duplicate keys from extra).",
                    "When macro_author_notes is non-empty, bible and plot planning must respect it.",
                    "When macro_author_notes is non-empty: each cast member notes_links must be a non-empty array whose entries are only ids from notes_keypoints (e.g. KP1, KP2); "
                    "each volume anchor notes_links must likewise be non-empty and drawn only from notes_keypoints ids.",
                    "Each anchor.target_state must be concrete and trackable.",
                    "Do not place anchors outside volumes; nest anchors only inside their owning volume.",
                    *script_shape_req,
                    *cast_req,
                    "initial_b_stories (optional): only series-long obsessions or terminal-goal decompositions - no short tactical errands (single-chapter fetch, lockpick, etc.). Each row needs resolution_condition.",
                    "speech_style / quirks_and_habits are occasional flavor - do not design them as every-line catchphrases.",
                ],
            },
            ensure_ascii=False,
        )

    def _default_cast_drafts(self, story_input: StoryInput) -> list[MacroCastMember]:
        lead = (story_input.title or "").strip()[:64] or "Protagonist"
        return [
            MacroCastMember(
                canonical_name=lead,
                role="protagonist",
                short_bio=(story_input.premise or "")[:240],
                personality="Restrained under pressure, but stubborn once committed.",
                core_motivation="Survive the present predicament and change the board.",
                core_value="Stay alive now while actively reshaping the situation.",
            ),
            MacroCastMember(
                canonical_name="Primary antagonist",
                role="antagonist",
                short_bio="The principal opponent aligned against the protagonist's goal.",
                personality="Cool, controlling, good at bending situations.",
                core_motivation="Fortify their order and suppress the protagonist.",
                core_value="Preserve the established order and eliminate threats.",
            ),
            MacroCastMember(
                canonical_name="Key supporting ally",
                role="supporting",
                short_bio="A core figure tightly coupled to the main spine.",
                personality="Pragmatic but emotionally acute; convictions tug hard.",
                core_motivation="Help or hinder the protagonist to move the conflict.",
                core_value="Hold a personal line between risk and choice.",
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
            core = (m.core_motivation or "").strip()
            personality = (m.personality or "").strip()
            coerced_pre.append(m.model_copy(update={"core_motivation": core, "personality": personality}))
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
            core = (m.core_motivation or "").strip()
            core_value = (m.core_value or "").strip() or core
            stored.append(
                StoryCastMemberStored(
                    node_id=node_id,
                    canonical_name=name,
                    role=m.role,
                    short_bio=(m.short_bio or "")[:CAST_SHORT_BIO_MAX],
                    aliases=[a.strip() for a in m.aliases if str(a).strip()][:8],
                    age=_age_str(m.age),
                    personality=(m.personality or "")[:CAST_PERSONALITY_MAX],
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
                    title=f"{volume.title} padding beat {pad_i + 1}",
                    description=f"Plot beat to land around chapter {ch} inside this volume (system-padded).",
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
                title="Volume I: The spark",
                summary="Establish the world and the protagonist's bind; lay the core conflict.",
                chapter_start=v1[0],
                chapter_end=v1[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range("Volume I: The spark", "", v1[0], v1[1], beat_prefix="Vol I"),
            ),
            MacroVolumePlanDraft(
                title="Volume II: Closing in",
                summary="Force costs on the cast while closing on anchors and secrets.",
                chapter_start=v2[0],
                chapter_end=v2[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range("Volume II: Closing in", "", v2[0], v2[1], beat_prefix="Vol II"),
            ),
            MacroVolumePlanDraft(
                title="Volume III: Collide and collect",
                summary="Pay off seeds and close the main spine.",
                chapter_start=v3[0],
                chapter_end=v3[1],
                target_volume_words=0,
                anchors=self._default_nested_anchors_for_range(
                    "Volume III: Collide and collect", "", v3[0], v3[1], beat_prefix="Vol III"
                ),
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
            volume_title = f"Volume {idx}: staged advance"
            volume_summary = f"Carry prior momentum and push the theme ({story_input.premise[:40]})."
            anchors = self._default_nested_anchors_for_range(
                volume_title,
                volume_summary,
                ch_start,
                ch_end,
                beat_prefix=f"Vol{idx}",
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
