from __future__ import annotations

import math
import re
import json
import logging
import random
from concurrent.futures import as_completed
from typing import Any, Literal

from app.core.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor
from pydantic import BaseModel, Field

from app.domain.schema import (
    AnchorNode,
    AnchorStatus,
    MacroCastMember,
    Storyline,
    StorylineTier,
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
MAIN_SLOT_BATCH_SUMMARY_MAX = 500


class _LLMStorylineDraft(BaseModel):
    id: str
    type: StorylineTier
    title: str
    overall_goal: str
    involved_entities: list[str] = Field(default_factory=list)


class _LLMAnchorNodeDraft(BaseModel):
    id: str
    storyline_ids: list[str] = Field(default_factory=list)
    volume_id: str
    node_kind: Literal["NORMAL", "FORK", "MERGE", "CHECKPOINT", "ENDING"] = "NORMAL"
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)


class _LLMWeavePlanOutput(BaseModel):
    storylines: list[_LLMStorylineDraft] = Field(default_factory=list)
    anchor_nodes: list[_LLMAnchorNodeDraft] = Field(default_factory=list)


class _LLMSlotFillItem(BaseModel):
    node_id: str
    title: str
    description: str


class _LLMSlotFillOutput(BaseModel):
    items: list[_LLMSlotFillItem] = Field(default_factory=list)
    batch_summary: str = ""


class _LLMStorylineSlotItem(BaseModel):
    storyline_id: str
    title: str
    overall_goal: str
    involved_entities: list[str] = Field(default_factory=list)


class _LLMStorylineSlotOutput(BaseModel):
    items: list[_LLMStorylineSlotItem] = Field(default_factory=list)

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


# --- Setup-wizard structured hint extraction --------------------------------
# The frontend Setup wizard composes its Stage 2/3 structured fields into
# `macro_author_notes` under stable section markers (see frontend/.../setupPhases.ts).
# These helpers parse them back out so we can feed structured hints to the
# storyline weave prompt — without changing the backend schema.

# Subplot hint line format. The optional `:N` after the tier letter is a 1-indexed
# volume pin emitted by the Setup wizard for A_TIER and B_TIER rows (S spans the
# whole book and never carries a volume). Both full-width 「｜」 and ASCII pipe are
# accepted so legacy notes keep working.
_SUBPLOT_HINT_LINE_RE = re.compile(
    r"^\[([SAB])(?::(\d+))?\]\s*[｜|]\s*([^｜|]*)[｜|]\s*(.*)$"
)
_VOLUME_GOAL_LINE_RE = re.compile(
    r"^(?:V|第\s*|Volume\s+)(\d+)(?:\s*卷)?\s*[｜|]\s*(.+)$",
    re.IGNORECASE,
)
_SETUP_SECTION_MARKERS: tuple[str, ...] = (
    "[[WORLD]]",
    "[[CHARACTERS]]",
    "[[STYLE]]",
    "[[VOLUME_GOALS]]",
    "[[SUBPLOTS]]",
)


def _slice_setup_section(notes: str, marker: str) -> str:
    """Return text between `marker` and the next setup section marker (or EOF)."""
    if not notes:
        return ""
    start = notes.find(marker)
    if start == -1:
        return ""
    section_start = start + len(marker)
    end = len(notes)
    for other in _SETUP_SECTION_MARKERS:
        if other == marker:
            continue
        idx = notes.find(other, section_start)
        if idx != -1 and idx < end:
            end = idx
    return notes[section_start:end].strip()


def extract_user_subplot_hints(notes: str) -> list[dict[str, Any]]:
    """Parse the wizard's ``[[SUBPLOTS]]`` block into structured hints.

    Each returned entry is shaped as ``{tier, title, goal}`` and may additionally
    carry a ``volume: int`` (1-indexed) when the wizard pinned the A/B row to a
    specific volume. S_TIER lines never carry a volume because S spans the whole
    book. Legacy notes (``[A]｜title｜goal``) parse without the ``volume`` key so
    older snapshots keep their wire shape.
    """
    section = _slice_setup_section(notes or "", "[[SUBPLOTS]]")
    if not section:
        return []
    hints: list[dict[str, Any]] = []
    for raw_line in section.splitlines():
        match = _SUBPLOT_HINT_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        tier = match.group(1).upper()
        if tier not in ("S", "A", "B"):
            continue
        title = match.group(3).strip()
        goal = match.group(4).strip()
        if not title and not goal:
            continue
        entry: dict[str, Any] = {"tier": tier, "title": title, "goal": goal}
        volume_raw = match.group(2)
        # S can't be pinned to a volume; ignore stray `:N` tags on S to be lenient.
        if volume_raw and tier in ("A", "B"):
            try:
                vol = int(volume_raw)
                if vol > 0:
                    entry["volume"] = vol
            except ValueError:
                pass
        hints.append(entry)
    return hints


def extract_user_volume_goals(notes: str) -> list[dict[str, Any]]:
    """Parse the wizard's ``[[VOLUME_GOALS]]`` block into ``[{volume, goal}, ...]``."""
    section = _slice_setup_section(notes or "", "[[VOLUME_GOALS]]")
    if not section:
        return []
    goals: list[dict[str, Any]] = []
    seen_volumes: set[int] = set()
    for raw_line in section.splitlines():
        match = _VOLUME_GOAL_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        try:
            volume = int(match.group(1))
        except ValueError:
            continue
        if volume <= 0 or volume in seen_volumes:
            continue
        goal = match.group(2).strip()
        if not goal:
            continue
        seen_volumes.add(volume)
        goals.append({"volume": volume, "goal": goal})
    goals.sort(key=lambda entry: entry["volume"])
    return goals


def _count_subplot_hints_by_tier(hints: list[dict[str, str]]) -> dict[str, int]:
    counts = {"S": 0, "A": 0, "B": 0}
    for h in hints:
        tier = str(h.get("tier", "")).upper()
        if tier in counts:
            counts[tier] += 1
    return counts


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
    def _tri_instruction(zh_hant: str, zh_hans: str, en: str) -> str:
        """Force multilingual instruction parity for compile prompts."""
        return f"[zh-Hant] {zh_hant}\n[zh-Hans] {zh_hans}\n[en] {en}"

    def _branch_count_for_story(self, story_input: StoryInput) -> int:
        if story_input.branch_count_override is not None:
            return max(1, int(story_input.branch_count_override))
        return max(1, round((int(story_input.target_total_words) / 100000) * 2))

    def _build_storylines(
        self,
        story_id: str,
        volumes: list[VolumePlan],
        cast: list[StoryCastMemberStored],
        branch_count: int,
    ) -> list[Storyline]:
        involved = [c.node_id for c in cast[:8]]
        rows: list[Storyline] = [
            Storyline(
                id=f"{story_id}_main",
                type=StorylineTier.MAIN,
                title="Main storyline",
                overall_goal="Drive the core conflict to final resolution.",
                involved_entities=involved[:5],
            )
        ]
        rows.append(
            Storyline(
                id=f"{story_id}_s_tier_01",
                type=StorylineTier.S_TIER,
                title="Series-spanning pressure line",
                overall_goal="Continuously apply long-horizon pressure to main arc decisions.",
                involved_entities=involved[:4],
            )
        )
        # Ensure at least one A-tier per volume.
        for i, v in enumerate(volumes, start=1):
            rows.append(
                Storyline(
                    id=f"{story_id}_a_tier_v{i:02d}",
                    type=StorylineTier.A_TIER,
                    title=f"{v.title} supporting line",
                    overall_goal=f"Serve and tighten {v.title} main volume objective.",
                    involved_entities=involved[:4],
                )
            )
        # Fill additional branch quota with B-tier micro lines.
        existing_branches = max(0, len(rows) - 1)
        extra = max(0, branch_count - existing_branches)
        for i in range(extra):
            rows.append(
                Storyline(
                    id=f"{story_id}_b_tier_{i+1:02d}",
                    type=StorylineTier.B_TIER,
                    title=f"Micro beat line {i+1}",
                    overall_goal="Provide local texture and chapter-scale swing without derailing the spine.",
                    involved_entities=involved[:3],
                )
            )
        return rows

    def _build_fishbone_storylines(
        self,
        story_id: str,
        volumes: list[VolumePlan],
        cast: list[StoryCastMemberStored],
        user_subplot_hints: list[dict[str, Any]] | None = None,
    ) -> tuple[list[Storyline], dict[str, Any]]:
        """Build the deterministic fishbone storyline skeleton.

        When the wizard pinned A/B subplot rows to specific volumes via
        ``[[SUBPLOTS]]`` (``[A:N]`` / ``[B:N]``), we bump the per-volume A_TIER
        count to at least the user-supplied hint count for that volume, and we
        pre-assign B_TIER storylines to the requested volumes (with any
        remaining auto-generated B lines round-robin'd across the remaining
        volumes). Without user hints, the original random behaviour is kept.
        """
        involved = [c.node_id for c in cast[:8]]
        rng = random.Random(f"fishbone:{story_id}:{len(volumes)}")

        # Tally user [A]/[B] hint counts per 1-indexed volume so we can honour
        # the wizard's requested spread without the LLM having to invent extra
        # storyline rows post-hoc.
        a_hint_counts_by_volume: dict[int, int] = {}
        b_pinned_volume_indices: list[int] = []
        for h in user_subplot_hints or []:
            tier = str(h.get("tier", "")).upper()
            vol = h.get("volume")
            if not isinstance(vol, int) or vol <= 0 or vol > len(volumes):
                continue
            if tier == "A":
                a_hint_counts_by_volume[vol] = a_hint_counts_by_volume.get(vol, 0) + 1
            elif tier == "B":
                b_pinned_volume_indices.append(vol)

        s_count = rng.randint(1, 2)
        rows: list[Storyline] = [
            Storyline(
                id=f"{story_id}_main",
                type=StorylineTier.MAIN,
                title="Main storyline",
                overall_goal="Drive the core conflict to final resolution.",
                involved_entities=involved[:5],
            )
        ]
        for i in range(s_count):
            rows.append(
                Storyline(
                    id=f"{story_id}_s_tier_{i+1:02d}",
                    type=StorylineTier.S_TIER,
                    title=f"Series arc {i+1}",
                    overall_goal="Apply long-horizon pressure across volumes and converge at checkpoints.",
                    involved_entities=involved[:4],
                )
            )
        a_lines_per_volume: dict[str, list[str]] = {}
        for i, v in enumerate(volumes, start=1):
            # Honour user-supplied per-volume A hints first; fall back to the
            # original random per-volume count of 1~2 when no user hints exist.
            user_a = a_hint_counts_by_volume.get(i, 0)
            count = max(rng.randint(1, 2), user_a)
            ids: list[str] = []
            for j in range(count):
                sid = f"{story_id}_a_tier_v{i:02d}_{j+1:02d}"
                ids.append(sid)
                rows.append(
                    Storyline(
                        id=sid,
                        type=StorylineTier.A_TIER,
                        title=f"{v.title} supporting arc {j+1}",
                        overall_goal=f"Serve and tighten {v.title} objective, then converge into volume end.",
                        involved_entities=involved[:4],
                    )
                )
            a_lines_per_volume[v.volume_id] = ids

        # B_TIER: random formula count, then bump up so every pinned user [B]
        # hint gets its own storyline row.
        b_min = max(1, int(math.ceil(len(volumes) * 0.5)))
        b_max = max(b_min, int(math.ceil(len(volumes) * 1.5)))
        b_count = max(rng.randint(b_min, b_max), len(b_pinned_volume_indices))

        # Decide which volume each B-tier storyline lives in. Pinned hints win
        # the first slots in order; the rest round-robin across volumes so the
        # default texture stays evenly distributed (matches old random mount).
        b_volume_indices: list[int | None] = list(b_pinned_volume_indices)
        rr_cursor = 0
        while len(b_volume_indices) < b_count:
            if volumes:
                b_volume_indices.append((rr_cursor % len(volumes)) + 1)
                rr_cursor += 1
            else:
                b_volume_indices.append(None)

        b_storyline_volume_by_id: dict[str, str] = {}
        for i in range(b_count):
            sid = f"{story_id}_b_tier_{i+1:02d}"
            rows.append(
                Storyline(
                    id=sid,
                    type=StorylineTier.B_TIER,
                    title=f"Micro beat line {i+1}",
                    overall_goal="Provide local texture and chapter-scale swing without derailing the spine.",
                    involved_entities=involved[:3],
                )
            )
            vol_idx = b_volume_indices[i] if i < len(b_volume_indices) else None
            if vol_idx and 1 <= vol_idx <= len(volumes):
                b_storyline_volume_by_id[sid] = volumes[vol_idx - 1].volume_id

        return rows, {
            "a_lines_per_volume": a_lines_per_volume,
            "b_storyline_volume_by_id": b_storyline_volume_by_id,
        }

    def _build_fishbone_anchor_nodes(
        self,
        *,
        story_id: str,
        anchors: list[StateAnchor],
        storylines: list[Storyline],
        volumes: list[VolumePlan],
        a_lines_per_volume: dict[str, list[str]],
        b_storyline_volume_by_id: dict[str, str] | None = None,
    ) -> list[AnchorNode]:
        rng = random.Random(f"fishbone:nodes:{story_id}:{len(anchors)}")
        by_volume: dict[str, list[StateAnchor]] = {}
        for a in sorted(anchors, key=lambda x: (x.priority, x.anchor_id)):
            by_volume.setdefault(a.volume_id, []).append(a)
        main_id = next((s.id for s in storylines if s.type == StorylineTier.MAIN), "")
        s_ids = [s.id for s in storylines if s.type == StorylineTier.S_TIER]
        b_ids = [s.id for s in storylines if s.type == StorylineTier.B_TIER]
        nodes: list[AnchorNode] = []
        roots: set[str] = set()
        prev_s_tail: dict[str, str] = {}
        volume_last_main: dict[str, str] = {}
        volume_start_main: dict[str, str] = {}
        prev_volume_last_main: str | None = None

        for vol in volumes:
            main_rows = by_volume.get(vol.volume_id, [])
            if not main_rows:
                continue
            for idx, a in enumerate(main_rows):
                if idx > 0:
                    deps = [main_rows[idx - 1].anchor_id]
                elif prev_volume_last_main:
                    deps = [prev_volume_last_main]
                else:
                    deps = []
                if not deps:
                    roots.add(a.anchor_id)
                nodes.append(
                    AnchorNode(
                        id=a.anchor_id,
                        storyline_ids=[main_id] if main_id else [],
                        volume_id=vol.volume_id,
                        node_kind="NORMAL",
                        title=a.title,
                        description=a.description,
                        depends_on=deps,
                        status=AnchorStatus.UNLOCKED if not deps else AnchorStatus.LOCKED,
                    )
                )
            volume_start_main[vol.volume_id] = main_rows[0].anchor_id
            volume_last_main[vol.volume_id] = main_rows[-1].anchor_id
            prev_volume_last_main = main_rows[-1].anchor_id

        prev_checkpoint_id: str | None = None
        for vol in volumes:
            start_main = volume_start_main.get(vol.volume_id)
            last_main = volume_last_main.get(vol.volume_id)
            if not start_main or not last_main:
                continue
            s_tail_ids: list[str] = []
            for s_idx, sid in enumerate(s_ids, start=1):
                count = rng.randint(1, 3)
                prior_s_tail = prev_s_tail.get(sid)
                prev = prior_s_tail or start_main
                for i in range(count):
                    nid = f"{vol.volume_id}_s{s_idx:02d}_{i+1:02d}"
                    deps = [prev] if prev else []
                    if i == 0 and prior_s_tail and prev_checkpoint_id:
                        deps.append(prev_checkpoint_id)
                    deps = list(dict.fromkeys([d for d in deps if d]))
                    if not deps:
                        roots.add(nid)
                    nodes.append(
                        AnchorNode(
                            id=nid,
                            storyline_ids=[sid],
                            volume_id=vol.volume_id,
                            node_kind="NORMAL",
                            title=f"S{s_idx} beat {i+1}",
                            description="Series arc progression beat.",
                            depends_on=deps,
                            status=AnchorStatus.UNLOCKED if not deps else AnchorStatus.LOCKED,
                        )
                    )
                    prev = nid
                prev_s_tail[sid] = prev
                s_tail_ids.append(prev)

            a_tail_ids: list[str] = []
            main_rows = by_volume.get(vol.volume_id, [])
            for a_idx, sid in enumerate(a_lines_per_volume.get(vol.volume_id, []), start=1):
                count = rng.randint(2, 4)
                latest_start = max(0, len(main_rows) - count)
                start_index = rng.randint(0, latest_start) if latest_start > 0 else 0
                prev = main_rows[start_index].anchor_id if main_rows else start_main
                for i in range(count):
                    nid = f"{vol.volume_id}_a{a_idx:02d}_{i+1:02d}"
                    deps = [prev] if prev else []
                    if not deps:
                        roots.add(nid)
                    nodes.append(
                        AnchorNode(
                            id=nid,
                            storyline_ids=[sid],
                            volume_id=vol.volume_id,
                            node_kind="NORMAL",
                            title=f"A{a_idx} beat {i+1}",
                            description="Volume-scoped support arc beat.",
                            depends_on=deps,
                            status=AnchorStatus.UNLOCKED if not deps else AnchorStatus.LOCKED,
                        )
                    )
                    prev = nid
                a_tail_ids.append(prev)

            cp_deps = [last_main] + s_tail_ids + a_tail_ids
            cp = f"{vol.volume_id}_checkpoint"
            nodes.append(
                AnchorNode(
                    id=cp,
                    storyline_ids=[main_id] if main_id else [],
                    volume_id=vol.volume_id,
                    node_kind="CHECKPOINT",
                    title=f"{vol.volume_id} checkpoint",
                    description="Volume convergence checkpoint.",
                    depends_on=list(dict.fromkeys([d for d in cp_deps if d])),
                    status=AnchorStatus.LOCKED,
                )
            )
            prev_checkpoint_id = cp

        b_tails_by_volume: dict[str, list[str]] = {}
        b_storyline_volume_by_id = b_storyline_volume_by_id or {}
        if b_ids:
            main_all = [a.anchor_id for a in sorted(anchors, key=lambda x: (x.priority, x.anchor_id))]
            rng.shuffle(main_all)
            used_mounts: set[str] = set()
            for idx, sid in enumerate(b_ids, start=1):
                length = rng.randint(1, 2)
                # If the wizard pinned this B-tier storyline to a specific
                # volume, prefer a mount inside that volume so the resulting
                # nodes obey the user's volume binding. Otherwise fall back to
                # the original random round-robin selection.
                preferred_vol = b_storyline_volume_by_id.get(sid)
                if preferred_vol:
                    mount = next(
                        (
                            a.anchor_id
                            for a in sorted(anchors, key=lambda x: (x.priority, x.anchor_id))
                            if a.volume_id == preferred_vol and a.anchor_id not in used_mounts
                        ),
                        None,
                    )
                    if mount is None:
                        mount = next(
                            (
                                a.anchor_id
                                for a in sorted(anchors, key=lambda x: (x.priority, x.anchor_id))
                                if a.volume_id == preferred_vol
                            ),
                            None,
                        )
                    if mount is None:
                        mount = next((m for m in main_all if m not in used_mounts), main_all[0] if main_all else "")
                else:
                    mount = next((m for m in main_all if m not in used_mounts), main_all[0] if main_all else "")
                if mount:
                    used_mounts.add(mount)
                prev = mount
                target_vol = next((a.volume_id for a in anchors if a.anchor_id == mount), volumes[-1].volume_id if volumes else "vol_unknown")
                for i in range(length):
                    nid = f"{target_vol}_b{idx:02d}_{i+1:02d}"
                    deps = [prev] if prev else []
                    nodes.append(
                        AnchorNode(
                            id=nid,
                            storyline_ids=[sid],
                            volume_id=target_vol,
                            node_kind="NORMAL",
                            title=f"B{idx} beat {i+1}",
                            description="Micro beat for local texture.",
                            depends_on=deps,
                            status=AnchorStatus.UNLOCKED if not deps else AnchorStatus.LOCKED,
                        )
                    )
                    prev = nid
                b_tails_by_volume.setdefault(target_vol, []).append(prev)

        # Wire each B-tier chain tail into that volume's checkpoint (nearest convergence point).
        if b_tails_by_volume:
            for i, n in enumerate(nodes):
                if n.node_kind != "CHECKPOINT":
                    continue
                extras = b_tails_by_volume.get(n.volume_id) or []
                if not extras:
                    continue
                merged = list(dict.fromkeys([*(n.depends_on or []), *extras]))
                nodes[i] = n.model_copy(update={"depends_on": merged})

        checkpoints = [n.id for n in nodes if n.node_kind == "CHECKPOINT"]
        if checkpoints:
            nodes.append(
                AnchorNode(
                    id=f"{story_id}_ending",
                    storyline_ids=[main_id] if main_id else [],
                    volume_id=volumes[-1].volume_id if volumes else "vol_unknown",
                    node_kind="ENDING",
                    title="Final ending",
                    description="Series final convergence ending node.",
                    depends_on=checkpoints,
                    status=AnchorStatus.LOCKED,
                )
            )
        self._validate_dag(nodes)
        self._ensure_tier_convergence(nodes, storylines)
        self._validate_strict_join(nodes, storylines)
        return nodes

    def _build_weave_prompt(
        self,
        *,
        story_id: str,
        story_input: StoryInput,
        volumes: list[VolumePlan],
        anchors: list[Any],
        cast: list[StoryCastMemberStored],
        branch_count: int,
        target_tier: StorylineTier | None = None,
        target_volume_id: str | None = None,
        user_subplot_hints: list[dict[str, str]] | None = None,
        user_volume_goals: list[dict[str, Any]] | None = None,
    ) -> str:
        tier_mode = target_tier.value if target_tier else "ALL"
        # Resolve user hints up front so we can both inject them into the prompt
        # and lift our hard quotas to at least cover the user's requested counts.
        # The wizard publishes them via `[[SUBPLOTS]] / [[VOLUME_GOALS]]` sections
        # in macro_author_notes; if callers don't pass them through, fall back to
        # parsing here so the prompt stays self-contained.
        if user_subplot_hints is None:
            user_subplot_hints = extract_user_subplot_hints(
                getattr(story_input, "macro_author_notes", "") or ""
            )
        if user_volume_goals is None:
            user_volume_goals = extract_user_volume_goals(
                getattr(story_input, "macro_author_notes", "") or ""
            )
        user_tier_counts = _count_subplot_hints_by_tier(user_subplot_hints)
        b_tier_overgen_min = max(1, int(math.ceil(branch_count * 1.3)))
        b_tier_overgen_max = max(
            b_tier_overgen_min,
            int(math.ceil(branch_count * 1.5)),
            user_tier_counts["B"],  # user-provided B hints raise the ceiling, never lower it
        )
        anchor_context: list[dict[str, Any]] = []
        for a in anchors:
            if isinstance(a, StateAnchor):
                anchor_context.append(
                    {
                        "id": a.anchor_id,
                        "volume_id": a.volume_id,
                        "title": a.title,
                        "description": a.description,
                        "dag_order": a.priority,
                        "priority": a.priority,
                        "storyline_ids": [],
                        "node_kind": "NORMAL",
                        "depends_on": [],
                        "source": "mainline_candidate",
                    }
                )
            elif isinstance(a, AnchorNode):
                anchor_context.append(
                    {
                        "id": a.id,
                        "volume_id": a.volume_id,
                        "title": a.title,
                        "description": a.description,
                        "dag_order": None,
                        "priority": None,
                        "storyline_ids": list(a.storyline_ids or []),
                        "node_kind": a.node_kind,
                        "depends_on": list(a.depends_on or []),
                        "source": "existing_side_or_merged",
                    }
                )
            else:
                continue

        requirements: list[str] = [
            f"CURRENT TASK: You are executing ONLY the {tier_mode} tier stage in a staged weave pipeline.",
            f"Do NOT generate new normal storyline rows or normal nodes for tiers other than {tier_mode}.",
            "You must keep provided existing anchor context coherent and connect your new nodes to that context via depends_on.",
            "MAIN = core conflict spine; S_TIER = series-long pressure line; A_TIER = per-volume key side thread serving the volume mainline; B_TIER = short micro-beat texture.",
            "NOTE THE DIFFERENCE: 'Storyline' is the overarching thread. 'Anchor Node' is a single chapter event within that thread. DO NOT confuse the counts for them.",
            "Every side thread must materially support mainline progression and cannot exceed owning volume scope.",
            "Allow free fork/merge topology while keeping graph acyclic.",
            "Each anchor node must be a concrete, physically verifiable event achievable within one chapter.",
            "CRITICAL RESOLUTION RULE: The `description` of each anchor node will be used by an automated GraphRAG logic engine to evaluate if the chapter goal is met. It MUST ONLY contain objective, observable actions, dialogue acts, or physical state changes.",
            "DO NOT include subjective atmosphere (e.g., 'coldness', 'hostility'), inner monologues, or narrative subtext/foreshadowing (e.g., 'implying someone...', 'setting the stage for...'). The logic engine cannot verify feelings or implications.",
            "Format descriptions as definitive factual statements between entities. Example BAD: 'He arrives to a hostile crowd, hinting at a conspiracy.' Example GOOD: 'He arrives at the city gate. The guards refuse his entry. An assassin attacks him with a poisoned dagger.'",
            "No Orphans: every generated node must be depended on by at least one other node, except ENDING nodes.",
            "storyline_ids in each node must reference existing storyline ids only.",
            "depends_on must reference existing anchor node ids only.",
            "Provide at least one UNLOCKED root-capable node (service will set statuses by dependency).",
        ]

        # Author hint adherence: when the wizard supplied structured subplot or
        # volume-goal hints, the LLM should treat them as the seed material
        # rather than inventing fresh themes from scratch. We don't drop hints
        # to fit a tight quota — if the backend asks for more storylines than
        # the user listed, the model invents extras; if fewer, the model still
        # tries to honour the user's full set first.
        if user_subplot_hints:
            requirements.extend([
                f"User has provided {len(user_subplot_hints)} subplot hint(s) in `user_subplot_hints` "
                "(each tagged with tier S/A/B plus title and goal).",
                "When user_subplot_hints contains entries whose tier matches the current tier_mode, "
                "prefer reusing the provided titles/goals as the basis for new storylines.",
                "When quota allows more storylines than user-provided hints, invent additional ones to fill the quota.",
                "Never drop a user-provided hint just to satisfy a tighter quota; cover all hints whose tier matches first.",
            ])
        if user_volume_goals:
            requirements.append(
                "User has provided per-volume narrative goals in `user_volume_goals`; align mainline beats "
                "and tier nodes within each volume so they progress those volume goals."
            )

        if target_tier == StorylineTier.S_TIER:
            requirements.extend([
                "Generate S_TIER (Series-spanning) storylines and anchor nodes.",
                "CRITICAL QUOTA: For target volume, each S_TIER storyline must generate between 1 and 3 anchor nodes.",
                "You must weave S_TIER smoothly across volumes using existing context, but this stage focuses on target_volume_id when provided.",
                "If target volume contains 0 nodes or more than 3 nodes for an S_TIER storyline, validation will reject your output.",
                "STRUCTURAL NODES: Emit DAG anchor_nodes with explicit FORK / MERGE / CHECKPOINT / ENDING where appropriate.",
                "Each CHECKPOINT and ENDING must strictly converge critical mainline + key side-thread outcomes.",
                "For each volume CHECKPOINT node, depends_on must include: [that volume's last MAIN node id] + [the last node id of every S_TIER and A_TIER line in that volume]."
            ])
            if user_tier_counts["S"] > 0:
                requirements.append(
                    "user_subplot_hints contains entries tagged [S]; reuse their titles/goals as the basis for the new S_TIER storylines."
                )

        elif target_tier == StorylineTier.A_TIER and target_volume_id:
            requirements.extend([
                f"Generate A_TIER nodes only for target_volume_id={target_volume_id}.",
                "CRITICAL QUOTA: You MUST generate exactly 2 to 4 anchor nodes for this A_TIER storyline.",
                "If you generate fewer than 2 or more than 4 nodes, the JSON compiler will crash.",
                "DO NOT continue A_TIER storylines from previous volumes. You MUST create a BRAND NEW A_TIER storyline ID specifically for this volume.",
                "STRUCTURAL NODES: Emit DAG anchor_nodes with explicit FORK / MERGE / CHECKPOINT / ENDING where appropriate.",
                "Each CHECKPOINT and ENDING must strictly converge critical mainline + key side-thread outcomes.",
                "For each volume CHECKPOINT node, depends_on must include: [that volume's last MAIN node id] + [the last node id of every S_TIER and A_TIER line in that volume]."
            ])
            if user_tier_counts["A"] > 0:
                requirements.append(
                    "user_subplot_hints contains entries tagged [A]; whenever an unused [A] hint remains, draw this new "
                    "A_TIER storyline from it (title and overall_goal). Pick the first unused hint that has not yet been "
                    "covered by the existing_anchor_context for any volume."
                )

        elif target_tier == StorylineTier.B_TIER:
            requirements.extend([
                f"Generate exactly {b_tier_overgen_max} independent B_TIER storylines.",
                "CRITICAL QUOTA: Every single B_TIER storyline MUST have exactly 1 or 2 anchor nodes. NO MORE THAN 2.",
                "Do NOT turn a B_TIER beat into a multi-chapter arc. If any B_TIER has 3 or more nodes, the system will crash.",
                "B_TIER nodes are micro-beats. Do NOT generate CHECKPOINT, MERGE, or ENDING nodes. Just attach your B_TIER 'NORMAL' nodes to existing forks or mainline nodes."
            ])
            if user_tier_counts["B"] > 0:
                requirements.append(
                    "user_subplot_hints contains entries tagged [B]; cover every [B] hint first (one storyline per hint), "
                    "then invent additional B_TIER lines to meet the overgen quota."
                )
        return json.dumps(
            {
                "task": "Generate side-thread storylines and weave them back into mainline DAG anchor nodes.",
                "tier_mode": tier_mode,
                "target_volume_id": target_volume_id or "",
                "story_id": story_id,
                "output_language": normalize_output_language(story_input.output_language),
                "branch_count_target": branch_count,
                "story": {"title": story_input.title, "premise": story_input.premise},
                "volumes": [v.model_dump(mode="json") for v in volumes],
                "existing_anchor_context": anchor_context,
                "cast": [
                    {"node_id": c.node_id, "canonical_name": c.canonical_name, "role": c.role}
                    for c in cast
                ],
                "user_subplot_hints": list(user_subplot_hints or []),
                "user_volume_goals": list(user_volume_goals or []),
                "requirements": requirements,
                "output_shape": {
                    "_planning": "String. STEP 1: State how many storylines you are generating. STEP 2: State exactly how many anchor nodes you will generate for each volume/storyline, and explicitly confirm it obeys the CRITICAL QUOTA.",
                    "storylines": [
                        {
                            "id": "string",
                            "type": "MAIN|S_TIER|A_TIER|B_TIER",
                            "title": "string",
                            "overall_goal": "string",
                            "involved_entities": ["string"],
                        }
                    ],
                    "anchor_nodes": [
                        {
                            "id": "string",
                            "storyline_ids": ["string"],
                            "volume_id": "string",
                            "node_kind": "NORMAL|FORK|MERGE|CHECKPOINT|ENDING",
                            "title": "string",
                            "description": "string",
                            "depends_on": ["string"],
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )

    def _sanitize_weave_output(
        self,
        *,
        storylines: list[Storyline],
        nodes: list[AnchorNode],
        volumes: list[VolumePlan],
        required_b_min_keep: int,
    ) -> tuple[list[Storyline], list[AnchorNode], dict[str, Any]]:
        by_storyline: dict[str, Storyline] = {s.id: s for s in storylines}
        vol_ids = {v.volume_id for v in volumes}
        dropped: list[str] = []

        def _nodes_for_storyline(sid: str) -> list[AnchorNode]:
            return [n for n in nodes if sid in n.storyline_ids]

        keep_storyline_ids: set[str] = set()
        for s in storylines:
            linked = _nodes_for_storyline(s.id)
            if not linked:
                dropped.append(f"{s.id}:no_anchor_nodes")
                continue
            if s.type == StorylineTier.USER_EDIT:
                keep_storyline_ids.add(s.id)
                continue
            if s.type == StorylineTier.S_TIER:
                ok = True
                for vid in vol_ids:
                    c = sum(1 for n in linked if n.volume_id == vid)
                    if c < 1 or c > 3:
                        ok = False
                        dropped.append(f"{s.id}:S_TIER volume {vid} count {c} not in [1,3]")
                        break
                if not ok:
                    continue
            elif s.type == StorylineTier.A_TIER:
                c = len(linked)
                if c < 2 or c > 4:
                    dropped.append(f"{s.id}:A_TIER count {c} not in [1,3]")
                    continue
            elif s.type == StorylineTier.B_TIER:
                c = len(linked)
                if c < 1 or c > 2:
                    dropped.append(f"{s.id}:B_TIER count {c} not in [1,2]")
                    continue
            keep_storyline_ids.add(s.id)

        filtered_storylines = [s for s in storylines if s.id in keep_storyline_ids]
        filtered_nodes: list[AnchorNode] = []
        for n in nodes:
            kept = [sid for sid in n.storyline_ids if sid in keep_storyline_ids]
            if not kept:
                continue
            filtered_nodes.append(n.model_copy(update={"storyline_ids": kept}))
        kept_b_count = sum(1 for s in filtered_storylines if s.type == StorylineTier.B_TIER)
        b_tier_insufficient = kept_b_count < max(1, required_b_min_keep)
        if b_tier_insufficient:
            dropped.append(
                f"B_TIER kept {kept_b_count} below required minimum {max(1, required_b_min_keep)}"
            )
        return filtered_storylines, filtered_nodes, {
            "dropped_storylines": dropped,
            "kept_b_count": kept_b_count,
            "required_b_min_keep": max(1, required_b_min_keep),
            "b_tier_insufficient": b_tier_insufficient,
        }

    @staticmethod
    def _weave_minimum_tier_counts(storylines: list[Storyline]) -> bool:
        tiers = {StorylineTier.MAIN: 0, StorylineTier.S_TIER: 0, StorylineTier.A_TIER: 0, StorylineTier.B_TIER: 0}
        for s in storylines:
            if s.type in tiers:
                tiers[s.type] += 1
        return (
            tiers[StorylineTier.MAIN] >= 1
            and tiers[StorylineTier.S_TIER] >= 1
            and tiers[StorylineTier.A_TIER] >= 1
            and tiers[StorylineTier.B_TIER] >= 1
        )

    @staticmethod
    def _classify_weave_error(message: str) -> str:
        msg = (message or "").lower()
        if "empty anchor_nodes" in msg:
            return "EMPTY_ANCHOR_NODES"
        if "empty storylines" in msg:
            return "EMPTY_STORYLINES"
        if "cycle detected" in msg:
            return "DAG_CYCLE"
        if "strict join failed" in msg:
            return "STRICT_JOIN"
        if "fork validation failed" in msg:
            return "FORK_MERGE"
        if "anchor convergence validation failed" in msg:
            return "CONVERGENCE"
        if "storyline count after sanitize" in msg:
            return "TIER_MINIMUM_NOT_MET"
        return "UNKNOWN"

    def _validate_single_tier_chunk(
        self,
        *,
        tier: StorylineTier,
        storylines: list[Storyline],
        nodes: list[AnchorNode],
        volumes: list[VolumePlan],
        branch_count: int,
        target_volume_id: str | None = None,
        target_pass_count: int | None = None,
    ) -> None:
        tier_storylines = [s for s in storylines if s.type == tier]
        if not tier_storylines:
            raise ValueError(f"{tier.value} call returned no {tier.value} storylines")
        tier_ids = {s.id for s in tier_storylines}
        tier_nodes = [n for n in nodes if any(sid in tier_ids for sid in n.storyline_ids)]
        if not tier_nodes:
            raise ValueError(f"{tier.value} call returned no anchor nodes for {tier.value} storylines")
        if tier == StorylineTier.S_TIER:
            vol_ids = {v.volume_id for v in volumes}
            for s in tier_storylines:
                for vid in vol_ids:
                    c = sum(1 for n in tier_nodes if n.volume_id == vid and s.id in n.storyline_ids)
                    if c < 1 or c > 3:
                        raise ValueError(f"{s.id}:S_TIER volume {vid} count {c} not in [1,3]")
        elif tier == StorylineTier.A_TIER:
            if target_volume_id:
                scoped_nodes = [n for n in tier_nodes if n.volume_id == target_volume_id]
                scoped_count = len(scoped_nodes)
                if scoped_count < 2 or scoped_count > 4:
                    raise ValueError(f"A_TIER volume {target_volume_id} count {scoped_count} not in [2,4]")
                if target_pass_count is not None and scoped_count < target_pass_count:
                    raise ValueError(
                        f"A_TIER volume {target_volume_id} count {scoped_count} below pass target {target_pass_count}"
                    )
            else:
                for s in tier_storylines:
                    c = sum(1 for n in tier_nodes if s.id in n.storyline_ids)
                    if c < 2 or c > 4:
                        raise ValueError(f"{s.id}:A_TIER count {c} not in [2,4]")
        elif tier == StorylineTier.B_TIER:
            b_storyline_count = len(tier_storylines)
            b_min = max(1, int(math.ceil(branch_count * 1.3)))
            b_max = max(b_min, int(math.ceil(branch_count * 1.5)))
            required_min = max(1, branch_count)
            if b_storyline_count < required_min:
                raise ValueError(
                    f"B_TIER storyline count {b_storyline_count} below required minimum {required_min}"
                )

    def _llm_generate_storylines_and_anchor_nodes(
        self,
        *,
        story_id: str,
        story_input: StoryInput,
        volumes: list[VolumePlan],
        anchors: list[StateAnchor],
        cast: list[StoryCastMemberStored],
        branch_count: int,
        llm_client: LLMClient | None,
    ) -> tuple[list[Storyline], list[AnchorNode], dict[str, Any]]:
        if llm_client is None or isinstance(llm_client, MockLLMClient):
            return [], [], {
                "attempts": 0,
                "max_attempts": 0,
                "fallback": True,
                "fallback_reason": "LLM client unavailable or mock",
                "failure_code": "LLM_UNAVAILABLE",
                "attempt_errors": [],
                "dropped_storylines": [],
            }
        profile = augment_profile_system_prompt(get_profile("macro_planner"), story_input.output_language)
        max_attempts = 5
        last_error = ""
        last_dropped: list[str] = []
        attempt_errors: list[dict[str, Any]] = []
        retries_used = 0
        completed_tiers: list[str] = []
        tier_outputs: dict[StorylineTier, tuple[list[Storyline], list[AnchorNode]]] = {}
        accumulated_nodes: list[Any] = list(anchors)

        # Pull wizard-supplied hints once so the per-tier prompts share a stable view.
        # `_build_weave_prompt` falls back to parsing on its own, but doing it here lets
        # us derive per-volume A-line slot counts (max(formula, user count)).
        raw_notes = getattr(story_input, "macro_author_notes", "") or ""
        user_subplot_hints = extract_user_subplot_hints(raw_notes)
        user_volume_goals = extract_user_volume_goals(raw_notes)
        user_tier_counts = _count_subplot_hints_by_tier(user_subplot_hints)
        # Per-volume A_TIER slot count: backend baseline is 1 per volume; lift to
        # ceil(user_a / volumes) when the user requested more A lines than volumes.
        a_slots_per_volume = max(
            1,
            math.ceil(user_tier_counts["A"] / max(1, branch_count)),
        )

        def _drafts_to_models(structured: _LLMWeavePlanOutput) -> tuple[list[Storyline], list[AnchorNode]]:
            storylines: list[Storyline] = []
            for s in structured.storylines:
                sid = s.id.strip()
                if not sid:
                    continue
                storylines.append(
                    Storyline(
                        id=sid,
                        type=s.type,
                        title=s.title.strip(),
                        overall_goal=s.overall_goal.strip(),
                        involved_entities=[str(x).strip() for x in s.involved_entities if str(x).strip()],
                    )
                )
            valid_storyline_ids = {s.id for s in storylines}
            nodes: list[AnchorNode] = []
            seen_node_ids: set[str] = set()
            for n in structured.anchor_nodes:
                nid = n.id.strip()
                if not nid or nid in seen_node_ids:
                    continue
                seen_node_ids.add(nid)
                sid = [x for x in n.storyline_ids if x in valid_storyline_ids]
                nodes.append(
                    AnchorNode(
                        id=nid,
                        storyline_ids=sid,
                        volume_id=n.volume_id.strip(),
                        node_kind=n.node_kind,
                        title=n.title.strip(),
                        description=n.description.strip(),
                        depends_on=[str(x).strip() for x in n.depends_on if str(x).strip()],
                        status=AnchorStatus.LOCKED,
                    )
                )
            return storylines, nodes

        def _fallback_a_volume_chunk(volume: VolumePlan, volume_index: int) -> tuple[list[Storyline], list[AnchorNode]]:
            storyline_id = f"{story_id}_a_tier_v{volume_index:02d}_fallback"
            storyline = Storyline(
                id=storyline_id,
                type=StorylineTier.A_TIER,
                title=f"{volume.title} fallback A-tier line",
                overall_goal=f"Fallback A-tier support line for {volume.title}.",
                involved_entities=[c.node_id for c in cast[:3]],
            )
            volume_main = sorted(
                [a for a in anchors if a.volume_id == volume.volume_id],
                key=lambda x: (x.priority, x.anchor_id),
            )
            first_main = volume_main[0].anchor_id if volume_main else ""
            n1_id = f"{volume.volume_id}_a_fallback_01"
            n2_id = f"{volume.volume_id}_a_fallback_02"
            n3_id = f"{volume.volume_id}_a_fallback_03"
            nodes = [
                AnchorNode(
                    id=n1_id,
                    storyline_ids=[storyline_id],
                    volume_id=volume.volume_id,
                    node_kind="NORMAL",
                    title=f"{volume.title} A fallback 1",
                    description="Fallback A-tier setup beat.",
                    depends_on=[first_main] if first_main else [],
                    status=AnchorStatus.LOCKED if first_main else AnchorStatus.UNLOCKED,
                ),
                AnchorNode(
                    id=n2_id,
                    storyline_ids=[storyline_id],
                    volume_id=volume.volume_id,
                    node_kind="NORMAL",
                    title=f"{volume.title} A fallback 2",
                    description="Fallback A-tier escalation beat.",
                    depends_on=[n1_id],
                    status=AnchorStatus.LOCKED,
                ),
                AnchorNode(
                    id=n3_id,
                    storyline_ids=[storyline_id],
                    volume_id=volume.volume_id,
                    node_kind="NORMAL",
                    title=f"{volume.title} A fallback 3",
                    description="Fallback A-tier payoff beat.",
                    depends_on=[n2_id],
                    status=AnchorStatus.LOCKED,
                ),
            ]
            return [storyline], nodes

        def _fallback_s_volume_chunk(volume: VolumePlan, volume_index: int) -> tuple[list[Storyline], list[AnchorNode]]:
            storyline_id = f"{story_id}_s_tier_v{volume_index:02d}_fallback"
            storyline = Storyline(
                id=storyline_id,
                type=StorylineTier.S_TIER,
                title=f"{volume.title} fallback S-tier line",
                overall_goal=f"Fallback S-tier pressure line for {volume.title}.",
                involved_entities=[c.node_id for c in cast[:3]],
            )
            volume_main = sorted(
                [a for a in anchors if a.volume_id == volume.volume_id],
                key=lambda x: (x.priority, x.anchor_id),
            )
            first_main = volume_main[0].anchor_id if volume_main else ""
            s1 = f"{volume.volume_id}_s_fallback_01"
            s2 = f"{volume.volume_id}_s_fallback_02"
            nodes = [
                AnchorNode(
                    id=s1,
                    storyline_ids=[storyline_id],
                    volume_id=volume.volume_id,
                    node_kind="NORMAL",
                    title=f"{volume.title} S fallback 1",
                    description="Fallback S-tier pressure setup.",
                    depends_on=[first_main] if first_main else [],
                    status=AnchorStatus.LOCKED if first_main else AnchorStatus.UNLOCKED,
                ),
                AnchorNode(
                    id=s2,
                    storyline_ids=[storyline_id],
                    volume_id=volume.volume_id,
                    node_kind="NORMAL",
                    title=f"{volume.title} S fallback 2",
                    description="Fallback S-tier pressure payoff.",
                    depends_on=[s1],
                    status=AnchorStatus.LOCKED,
                ),
            ]
            return [storyline], nodes

        for tier in (StorylineTier.S_TIER, StorylineTier.A_TIER, StorylineTier.B_TIER):
            if tier == StorylineTier.S_TIER:
                s_storylines: list[Storyline] = []
                s_nodes: list[AnchorNode] = []
                for volume_idx, volume in enumerate(volumes, start=1):
                    tier_done = False
                    while not tier_done and retries_used < max_attempts:
                        try:
                            base_prompt = self._build_weave_prompt(
                                story_id=story_id,
                                story_input=story_input,
                                volumes=volumes,
                                anchors=accumulated_nodes,
                                cast=cast,
                                branch_count=branch_count,
                                target_tier=tier,
                                target_volume_id=volume.volume_id,
                                user_subplot_hints=user_subplot_hints,
                                user_volume_goals=user_volume_goals,
                            )
                            tier_prompt = base_prompt
                            if last_error:
                                tier_prompt = (
                                    f"{base_prompt}\n\n"
                                    "Previous weave output failed validation. Regenerate a fully valid result.\n"
                                    f"Issue: {last_error}\n"
                                    f"Dropped storylines: {last_dropped}"
                                )
                            structured, _ = llm_client.invoke_json(tier_prompt, _LLMWeavePlanOutput, profile)
                            t_storylines, t_nodes = _drafts_to_models(structured)
                            # S-tier now retries per-volume; only validate the current volume's count window.
                            s_only = [s for s in t_storylines if s.type == StorylineTier.S_TIER]
                            s_ids = {s.id for s in s_only}
                            s_nodes_vol = [
                                n for n in t_nodes if n.volume_id == volume.volume_id and any(sid in s_ids for sid in n.storyline_ids)
                            ]
                            if not s_only or not s_nodes_vol:
                                raise ValueError(f"S_TIER volume {volume.volume_id} returned no valid nodes")
                            for s in s_only:
                                c = sum(1 for n in s_nodes_vol if s.id in n.storyline_ids)
                                if c < 1 or c > 3:
                                    raise ValueError(f"{s.id}:S_TIER volume {volume.volume_id} count {c} not in [1,3]")
                            s_storylines.extend(s_only)
                            s_nodes.extend(s_nodes_vol)
                            accumulated_nodes.extend([n for n in s_nodes_vol if n.node_kind == "NORMAL"])
                            tier_done = True
                        except Exception as exc:
                            retries_used += 1
                            last_error = str(exc)
                            attempt_errors.append(
                                {
                                    "attempt": retries_used,
                                    "tier": tier.value,
                                    "volume_id": volume.volume_id,
                                    "failure_code": self._classify_weave_error(last_error),
                                    "message": last_error[:600],
                                    "dropped_storylines": list(last_dropped),
                                }
                            )
                    if not tier_done:
                        fb_storylines, fb_nodes = _fallback_s_volume_chunk(volume, volume_idx)
                        s_storylines.extend(fb_storylines)
                        s_nodes.extend(fb_nodes)
                        accumulated_nodes.extend(fb_nodes)
                tier_outputs[tier] = (s_storylines, s_nodes)
                completed_tiers.append(tier.value)
                continue
            if tier == StorylineTier.A_TIER:
                a_storylines: list[Storyline] = []
                a_nodes: list[AnchorNode] = []
                for volume_idx, volume in enumerate(volumes, start=1):
                    # Slot loop: lift per-volume A count to max(formula=1, user-driven slots).
                    # Each slot still asks the LLM for a single NEW A_TIER storyline so the
                    # existing single-storyline validator (_validate_single_tier_chunk) still
                    # applies — we just call it multiple times, accumulating new lines.
                    for slot_idx in range(a_slots_per_volume):
                        tier_done = False
                        while not tier_done and retries_used < max_attempts:
                            try:
                                base_prompt = self._build_weave_prompt(
                                    story_id=story_id,
                                    story_input=story_input,
                                    volumes=volumes,
                                    anchors=accumulated_nodes,
                                    cast=cast,
                                    branch_count=branch_count,
                                    target_tier=tier,
                                    target_volume_id=volume.volume_id,
                                    user_subplot_hints=user_subplot_hints,
                                    user_volume_goals=user_volume_goals,
                                )
                                slot_suffix = ""
                                if a_slots_per_volume > 1:
                                    slot_suffix = (
                                        f"\n\nA-line slot {slot_idx + 1} of {a_slots_per_volume} for "
                                        f"target_volume_id={volume.volume_id}. Pick a DIFFERENT angle than any "
                                        "A_TIER storyline already present in existing_anchor_context for this volume."
                                    )
                                tier_prompt = base_prompt + slot_suffix
                                if last_error:
                                    tier_prompt = (
                                        f"{tier_prompt}\n\n"
                                        "Previous weave output failed validation. Regenerate a fully valid result.\n"
                                        f"Issue: {last_error}\n"
                                        f"Dropped storylines: {last_dropped}"
                                    )
                                structured, _ = llm_client.invoke_json(tier_prompt, _LLMWeavePlanOutput, profile)
                                t_storylines, t_nodes = _drafts_to_models(structured)
                                self._validate_single_tier_chunk(
                                    tier=tier,
                                    storylines=t_storylines,
                                    nodes=t_nodes,
                                    volumes=volumes,
                                    branch_count=branch_count,
                                    target_volume_id=volume.volume_id,
                                )
                                a_storylines.extend([s for s in t_storylines if s.type == StorylineTier.A_TIER])
                                a_nodes.extend([n for n in t_nodes if n.volume_id == volume.volume_id])
                                accumulated_nodes.extend([n for n in t_nodes if n.node_kind == "NORMAL"])
                                tier_done = True
                            except Exception as exc:
                                retries_used += 1
                                last_error = str(exc)
                                attempt_errors.append(
                                    {
                                        "attempt": retries_used,
                                        "tier": tier.value,
                                        "volume_id": volume.volume_id,
                                        "slot_index": slot_idx,
                                        "failure_code": self._classify_weave_error(last_error),
                                        "message": last_error[:600],
                                        "dropped_storylines": list(last_dropped),
                                    }
                                )
                        if not tier_done:
                            # Fallback only seeds one A line per volume — break the slot loop
                            # so we don't double-fallback for the same volume.
                            fb_storylines, fb_nodes = _fallback_a_volume_chunk(volume, volume_idx)
                            a_storylines.extend(fb_storylines)
                            a_nodes.extend(fb_nodes)
                            accumulated_nodes.extend(fb_nodes)
                            break
                tier_outputs[tier] = (a_storylines, a_nodes)
                completed_tiers.append(tier.value)
                continue
            tier_done = False
            while not tier_done and retries_used < max_attempts:
                try:
                    base_prompt = self._build_weave_prompt(
                        story_id=story_id,
                        story_input=story_input,
                        volumes=volumes,
                        anchors=accumulated_nodes,
                        cast=cast,
                        branch_count=branch_count,
                        target_tier=tier,
                        user_subplot_hints=user_subplot_hints,
                        user_volume_goals=user_volume_goals,
                    )
                    tier_prompt = base_prompt
                    if last_error:
                        tier_prompt = (
                            f"{base_prompt}\n\n"
                            "Previous weave output failed validation. Regenerate a fully valid result.\n"
                            f"Issue: {last_error}\n"
                            f"Dropped storylines: {last_dropped}"
                        )
                    structured, _ = llm_client.invoke_json(tier_prompt, _LLMWeavePlanOutput, profile)
                    t_storylines, t_nodes = _drafts_to_models(structured)
                    self._validate_single_tier_chunk(
                        tier=tier,
                        storylines=t_storylines,
                        nodes=t_nodes,
                        volumes=volumes,
                        branch_count=branch_count,
                    )
                    tier_outputs[tier] = (t_storylines, t_nodes)
                    completed_tiers.append(tier.value)
                    accumulated_nodes.extend([n for n in t_nodes if n.node_kind == "NORMAL"])
                    tier_done = True
                except Exception as exc:
                    retries_used += 1
                    last_error = str(exc)
                    attempt_errors.append(
                        {
                            "attempt": retries_used,
                            "tier": tier.value,
                            "failure_code": self._classify_weave_error(last_error),
                            "message": last_error[:600],
                            "dropped_storylines": list(last_dropped),
                        }
                    )
            if not tier_done:
                break

        # Merge completed tier outputs
        merged_storylines: list[Storyline] = []
        merged_nodes: list[AnchorNode] = []
        seen_storyline_ids: set[str] = set()
        merged_nodes_dict: dict[str, AnchorNode] = {}
        for tier in (StorylineTier.S_TIER, StorylineTier.A_TIER, StorylineTier.B_TIER):
            if tier not in tier_outputs:
                continue
            t_storylines, t_nodes = tier_outputs[tier]
            for s in t_storylines:
                if s.id in seen_storyline_ids:
                    continue
                seen_storyline_ids.add(s.id)
                merged_storylines.append(s)
            for n in t_nodes:
                if n.id in merged_nodes_dict:
                    existing = merged_nodes_dict[n.id]
                    existing.depends_on = list(dict.fromkeys([*(existing.depends_on or []), *(n.depends_on or [])]))
                    existing.storyline_ids = list(dict.fromkeys([*(existing.storyline_ids or []), *(n.storyline_ids or [])]))
                    if n.node_kind in ("CHECKPOINT", "ENDING", "MERGE") and existing.node_kind == "NORMAL":
                        existing.node_kind = n.node_kind
                else:
                    merged_nodes_dict[n.id] = n
        merged_nodes = list(merged_nodes_dict.values())

        if len(tier_outputs) == 3:
            storylines, nodes, sanitize_meta = self._sanitize_weave_output(
                storylines=merged_storylines,
                nodes=merged_nodes,
                volumes=volumes,
                required_b_min_keep=max(1, branch_count),
            )
            last_dropped = list(sanitize_meta.get("dropped_storylines") or [])
            # If B-tier is still insufficient after single-item pruning, call B weaver again to top up.
            while bool(sanitize_meta.get("b_tier_insufficient")) and retries_used < max_attempts:
                try:
                    retries_used += 1
                    base_prompt = self._build_weave_prompt(
                        story_id=story_id,
                        story_input=story_input,
                        volumes=volumes,
                        anchors=accumulated_nodes + nodes,
                        cast=cast,
                        branch_count=branch_count,
                        target_tier=StorylineTier.B_TIER,
                        user_subplot_hints=user_subplot_hints,
                        user_volume_goals=user_volume_goals,
                    )
                    tier_prompt = (
                        f"{base_prompt}\n\n"
                        "B_TIER top-up mode: generate additional valid B_TIER storylines/nodes only."
                    )
                    structured, _ = llm_client.invoke_json(tier_prompt, _LLMWeavePlanOutput, profile)
                    add_storylines, add_nodes = _drafts_to_models(structured)
                    add_storylines = [s for s in add_storylines if s.type == StorylineTier.B_TIER]
                    add_ids = {s.id for s in add_storylines}
                    add_nodes = [n for n in add_nodes if any(sid in add_ids for sid in n.storyline_ids)]
                    # Merge add-ons with de-dup and union deps/labels on same id.
                    by_s: dict[str, Storyline] = {s.id: s for s in storylines}
                    for s in add_storylines:
                        by_s[s.id] = s
                    by_n: dict[str, AnchorNode] = {n.id: n for n in nodes}
                    for n in add_nodes:
                        if n.id in by_n:
                            ex = by_n[n.id]
                            ex.depends_on = list(dict.fromkeys([*(ex.depends_on or []), *(n.depends_on or [])]))
                            ex.storyline_ids = list(dict.fromkeys([*(ex.storyline_ids or []), *(n.storyline_ids or [])]))
                        else:
                            by_n[n.id] = n
                    storylines = list(by_s.values())
                    nodes = list(by_n.values())
                    accumulated_nodes.extend([n for n in add_nodes if n.node_kind == "NORMAL"])
                    storylines, nodes, sanitize_meta = self._sanitize_weave_output(
                        storylines=storylines,
                        nodes=nodes,
                        volumes=volumes,
                        required_b_min_keep=max(1, branch_count),
                    )
                    last_dropped = list(sanitize_meta.get("dropped_storylines") or [])
                except Exception as exc:
                    last_error = str(exc)
                    attempt_errors.append(
                        {
                            "attempt": retries_used,
                            "tier": StorylineTier.B_TIER.value,
                            "mode": "top_up",
                            "failure_code": self._classify_weave_error(last_error),
                            "message": last_error[:600],
                            "dropped_storylines": list(last_dropped),
                        }
                    )
                    break
            if not self._weave_minimum_tier_counts(storylines):
                last_error = "storyline count after sanitize does not satisfy MAIN/S/A/B minimum tiers"
            elif not nodes:
                last_error = "anchor_nodes empty after sanitize"
            else:
                node_ids = {n.id for n in nodes}
                for n in nodes:
                    n.depends_on = [dep for dep in n.depends_on if dep in node_ids and dep != n.id]
                    if len(n.depends_on) == 0:
                        n.status = AnchorStatus.UNLOCKED
                v_checkpoints = {n.volume_id: n for n in nodes if n.node_kind == "CHECKPOINT"}
                a_or_s_storylines = {s.id for s in storylines if s.type in (StorylineTier.S_TIER, StorylineTier.A_TIER)}
                
                for n in nodes:
                    if n.node_kind == "NORMAL" and any(sid in a_or_s_storylines for sid in n.storyline_ids):
                        is_depended_on = any(n.id in other.depends_on for other in nodes if other.volume_id == n.volume_id)
                        
                        if not is_depended_on and n.volume_id in v_checkpoints:
                            cp = v_checkpoints[n.volume_id]
                            if n.id not in cp.depends_on:
                                cp.depends_on.append(n.id)
                self._validate_dag(nodes)
                self._ensure_tier_convergence(nodes, storylines)
                self._validate_fork_merge(nodes)
                self._validate_strict_join(nodes, storylines)
                return storylines, nodes, {
                    "attempts": retries_used,
                    "max_attempts": max_attempts,
                    "dropped_storylines": last_dropped,
                    "fallback": False,
                    "completed_tiers": completed_tiers,
                }
        logger.warning(
            "llm weave generation failed, fallback to deterministic weave",
            extra={
                "error": last_error,
                "dropped_storylines": last_dropped,
                "max_attempts": max_attempts,
                "completed_tiers": completed_tiers,
            },
        )
        return merged_storylines, merged_nodes, {
            "attempts": retries_used,
            "max_attempts": max_attempts,
            "fallback": True,
            "fallback_reason": last_error or "LLM weave exhausted retry budget",
            "failure_code": self._classify_weave_error(last_error),
            "attempt_errors": attempt_errors,
            "dropped_storylines": last_dropped,
            "completed_tiers": completed_tiers,
            "incomplete_tiers": [
                t.value
                for t in (StorylineTier.S_TIER, StorylineTier.A_TIER, StorylineTier.B_TIER)
                if t.value not in completed_tiers
            ],
        }

    def _validate_dag(self, nodes: list[AnchorNode]) -> None:
        graph: dict[str, list[str]] = {n.id: [] for n in nodes}
        indeg: dict[str, int] = {n.id: 0 for n in nodes}
        for n in nodes:
            for dep in n.depends_on:
                if dep in graph:
                    graph[dep].append(n.id)
                    indeg[n.id] += 1
        q = [nid for nid, d in indeg.items() if d == 0]
        seen = 0
        while q:
            cur = q.pop()
            seen += 1
            for nxt in graph.get(cur, []):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    q.append(nxt)
        if seen != len(nodes):
            raise ValueError("anchor DAG validation failed: cycle detected")

    def _ensure_tier_convergence(self, nodes: list[AnchorNode], storylines: list[Storyline]) -> None:
        storyline_by_id = {s.id: s for s in storylines}
        by_id = {n.id: n for n in nodes}
        reverse: dict[str, list[str]] = {n.id: [] for n in nodes}
        for n in nodes:
            for dep in n.depends_on:
                if dep in reverse:
                    reverse[dep].append(n.id)
        ending_ids = [n.id for n in nodes if "ending" in n.title.casefold() or "checkpoint" in n.title.casefold()]
        if not ending_ids and nodes:
            ending_ids = [nodes[-1].id]
        def _can_reach_end(start: str) -> bool:
            stack = [start]
            visited: set[str] = set()
            while stack:
                cur = stack.pop()
                if cur in ending_ids:
                    return True
                if cur in visited:
                    continue
                visited.add(cur)
                stack.extend(reverse.get(cur, []))
            return False
        for n in nodes:
            tiers = [storyline_by_id[sid].type for sid in n.storyline_ids if sid in storyline_by_id]
            if any(t in (StorylineTier.S_TIER, StorylineTier.A_TIER) for t in tiers):
                if not _can_reach_end(n.id):
                    raise ValueError(f"anchor convergence validation failed: {n.id} cannot reach ending/checkpoint")

    def _validate_strict_join(self, nodes: list[AnchorNode], storylines: list[Storyline]) -> None:
        by_id = {n.id: n for n in nodes}
        main_storylines = [s.id for s in storylines if s.type == StorylineTier.MAIN]
        side_storylines = [s.id for s in storylines if s.type in (StorylineTier.S_TIER, StorylineTier.A_TIER)]
        children: dict[str, list[str]] = {n.id: [] for n in nodes}
        for node in nodes:
            for dep in node.depends_on:
                if dep in children:
                    children[dep].append(node.id)

        def _tail_for_storyline(volume_id: str, storyline_id: str) -> str | None:
            scoped = [
                n
                for n in nodes
                if n.volume_id == volume_id
                and storyline_id in (n.storyline_ids or [])
                and n.node_kind not in ("CHECKPOINT", "ENDING")
            ]
            if not scoped:
                return None
            scoped_ids = {n.id for n in scoped}
            tails = [
                n.id
                for n in scoped
                if not any(
                    child_id in scoped_ids
                    and storyline_id in (by_id[child_id].storyline_ids or [])
                    for child_id in children.get(n.id, [])
                )
            ]
            return sorted(tails or [n.id for n in scoped])[-1]

        checkpoints = [n for n in nodes if n.node_kind in ("CHECKPOINT", "ENDING")]
        for cp in checkpoints:
            if cp.node_kind == "ENDING":
                continue
            if len(cp.depends_on) < 2:
                raise ValueError(f"strict join failed: checkpoint {cp.id} must depend on >=2 upstream nodes")
            required_nodes: list[str] = []
            if main_storylines:
                main_tail = _tail_for_storyline(cp.volume_id, main_storylines[0])
                if main_tail:
                    required_nodes.append(main_tail)
            for sid in side_storylines:
                tail = _tail_for_storyline(cp.volume_id, sid)
                if tail:
                    required_nodes.append(tail)
            missing = [nid for nid in sorted(set(required_nodes)) if nid not in cp.depends_on]
            if missing:
                raise ValueError(f"strict join failed: {cp.id} missing storyline-tail deps {missing[:5]}")

    def _validate_fork_merge(self, nodes: list[AnchorNode]) -> None:
        children: dict[str, list[str]] = {n.id: [] for n in nodes}
        by_id = {n.id: n for n in nodes}
        for n in nodes:
            for dep in n.depends_on:
                if dep in children:
                    children[dep].append(n.id)
        merges = {n.id for n in nodes if n.node_kind in ("MERGE", "CHECKPOINT", "ENDING")}
        for n in nodes:
            if n.node_kind == "FORK":
                outs = children.get(n.id, [])
                if len(outs) < 2:
                    raise ValueError(f"fork validation failed: {n.id} needs >=2 downstream paths")
                # each fork branch must eventually converge.
                for start in outs:
                    stack = [start]
                    seen: set[str] = set()
                    converged = False
                    while stack:
                        cur = stack.pop()
                        if cur in merges:
                            converged = True
                            break
                        if cur in seen:
                            continue
                        seen.add(cur)
                        stack.extend(children.get(cur, []))
                    if not converged:
                        raise ValueError(f"fork validation failed: branch from {n.id} does not converge")
        for n in nodes:
            if n.node_kind == "MERGE" and len(n.depends_on) < 2:
                raise ValueError(f"merge validation failed: {n.id} must have >=2 parents")

    def _validate_fishbone_dependencies(self, nodes: list[AnchorNode], storylines: list[Storyline]) -> None:
        by_storyline = {s.id: s.type for s in storylines}
        by_id = {n.id: n for n in nodes}
        for n in nodes:
            own_types = {by_storyline.get(sid) for sid in n.storyline_ids if sid in by_storyline}
            for dep in n.depends_on:
                dep_node = by_id.get(dep)
                if not dep_node:
                    continue
                dep_types = {by_storyline.get(sid) for sid in dep_node.storyline_ids if sid in by_storyline}
                own_side = any(t in {StorylineTier.S_TIER, StorylineTier.A_TIER, StorylineTier.B_TIER} for t in own_types)
                dep_side = any(t in {StorylineTier.S_TIER, StorylineTier.A_TIER, StorylineTier.B_TIER} for t in dep_types)
                # side arc can only depend on mainline or same storyline
                if own_side and dep_side:
                    if set(n.storyline_ids).isdisjoint(set(dep_node.storyline_ids)):
                        raise ValueError(f"fishbone dependency violation: {n.id} depends on cross-side node {dep}")

    def _derive_thread_descriptions(
        self,
        volume: VolumePlan,
        volume_draft: MacroVolumePlanDraft | None,
        *,
        series_pressure_hint: str,
    ) -> dict[str, str]:
        draft = volume_draft
        summary = (draft.summary if draft else volume.summary) or ""
        nested = list(draft.anchors or []) if draft else []
        anchor_lines = [a.description.strip() for a in nested if (a.description or "").strip()]
        top_line = anchor_lines[0] if anchor_lines else summary
        second_line = anchor_lines[1] if len(anchor_lines) > 1 else top_line
        summary_trim = summary.strip()[:220]
        return {
            "a_thread_desc": (
                f"{volume.title}: {top_line[:260]} "
                f"Side thread must materially impact this volume's mainline choices."
            ).strip(),
            "s_thread_desc": (
                f"{volume.title}: Carry forward long-horizon pressure - {series_pressure_hint[:220] or summary_trim or top_line[:180]}."
            ).strip(),
            "b_thread_desc": (
                f"{volume.title}: Short local beat around '{second_line[:120]}' that adds texture without derailing the arc."
            ).strip(),
        }

    def _build_anchor_nodes(
        self,
        anchors: list[StateAnchor],
        storylines: list[Storyline],
        volume_thread_desc: dict[str, dict[str, str]] | None = None,
    ) -> list[AnchorNode]:
        main_id = next((s.id for s in storylines if s.type == StorylineTier.MAIN), "")
        ordered = sorted(anchors, key=lambda a: (a.priority, a.anchor_id))
        nodes: list[AnchorNode] = []
        s_tier_id = next((s.id for s in storylines if s.type == StorylineTier.S_TIER), "")
        a_tier_ids = [s.id for s in storylines if s.type == StorylineTier.A_TIER]
        b_tier_ids = [s.id for s in storylines if s.type == StorylineTier.B_TIER]
        by_volume: dict[str, list[StateAnchor]] = {}
        for a in ordered:
            by_volume.setdefault(a.volume_id, []).append(a)
        prev_checkpoint: str | None = None
        prev_s_node: str | None = None
        for v_idx, (volume_id, volume_anchors) in enumerate(by_volume.items(), start=1):
            thread_desc = (volume_thread_desc or {}).get(volume_id) or {}
            for idx, a in enumerate(volume_anchors):
                depends: list[str] = []
                if idx == 0 and prev_checkpoint:
                    depends.append(prev_checkpoint)
                elif idx > 0:
                    depends.append(volume_anchors[idx - 1].anchor_id)
                nodes.append(
                    AnchorNode(
                        id=a.anchor_id,
                        storyline_ids=[x for x in [main_id] if x],
                        volume_id=volume_id,
                        node_kind="NORMAL",
                        title=a.title,
                        description=a.description,
                        depends_on=depends,
                        status=AnchorStatus.UNLOCKED if not depends else AnchorStatus.LOCKED,
                    )
                )
            first_main = volume_anchors[0].anchor_id
            last_main = volume_anchors[-1].anchor_id
            fork_id = f"{volume_id}_fork"
            nodes.append(
                AnchorNode(
                    id=fork_id,
                    storyline_ids=[x for x in [main_id] if x],
                    volume_id=volume_id,
                    node_kind="FORK",
                    title=f"{volume_id} fork",
                    description="Branching point for side threads.",
                    depends_on=[first_main],
                    status=AnchorStatus.LOCKED,
                )
            )
            a_line = a_tier_ids[(v_idx - 1) % len(a_tier_ids)] if a_tier_ids else ""
            a_node_id = f"{volume_id}_a_thread"
            if a_line:
                nodes.append(
                    AnchorNode(
                        id=a_node_id,
                        storyline_ids=[a_line],
                        volume_id=volume_id,
                        node_kind="NORMAL",
                        title=f"{volume_id} A-tier thread",
                        description=str(
                            thread_desc.get("a_thread_desc")
                            or f"Resolve one concrete side-thread payoff tied to {volume_id}."
                        ),
                        depends_on=[fork_id],
                        status=AnchorStatus.LOCKED,
                    )
                )
            s_node_id = f"{volume_id}_s_thread"
            s_deps = [fork_id]
            if prev_s_node:
                s_deps.append(prev_s_node)
            if prev_s_node and prev_checkpoint:
                s_deps.append(prev_checkpoint)
            if s_tier_id:
                nodes.append(
                    AnchorNode(
                        id=s_node_id,
                        storyline_ids=[s_tier_id],
                        volume_id=volume_id,
                        node_kind="NORMAL",
                        title=f"{volume_id} S-tier thread",
                        description=str(
                            thread_desc.get("s_thread_desc")
                            or f"Advance a long-horizon S-tier thread through {volume_id}."
                        ),
                        depends_on=list(dict.fromkeys(s_deps)),
                        status=AnchorStatus.LOCKED,
                    )
                )
                prev_s_node = s_node_id
            if b_tier_ids:
                b_node_id = f"{volume_id}_b_scatter"
                nodes.append(
                    AnchorNode(
                        id=b_node_id,
                        storyline_ids=[b_tier_ids[(v_idx - 1) % len(b_tier_ids)]],
                        volume_id=volume_id,
                        node_kind="NORMAL",
                        title=f"{volume_id} B-tier scatter",
                        description=str(
                            thread_desc.get("b_thread_desc")
                            or f"Inject a short local beat that still supports {volume_id} trajectory."
                        ),
                        depends_on=[fork_id],
                        status=AnchorStatus.LOCKED,
                    )
                )
            merge_deps = [last_main]
            if a_line:
                merge_deps.append(a_node_id)
            if s_tier_id:
                merge_deps.append(s_node_id)
            merge_id = f"{volume_id}_merge"
            nodes.append(
                AnchorNode(
                    id=merge_id,
                    storyline_ids=[x for x in [main_id] if x],
                    volume_id=volume_id,
                    node_kind="MERGE",
                    title=f"{volume_id} merge",
                    description="Volume branch convergence merge point.",
                    depends_on=merge_deps,
                    status=AnchorStatus.LOCKED,
                )
            )
            chk_id = f"{volume_id}_checkpoint"
            nodes.append(
                AnchorNode(
                    id=chk_id,
                    storyline_ids=[x for x in [main_id] if x],
                    volume_id=volume_id,
                    node_kind="CHECKPOINT",
                    title=f"{volume_id} checkpoint",
                    description="Volume convergence checkpoint.",
                    depends_on=[merge_id] + ([a_node_id] if a_line else []) + ([s_node_id] if s_tier_id else []),
                    status=AnchorStatus.LOCKED,
                )
            )
            prev_checkpoint = chk_id
        if nodes:
            nodes.append(
                AnchorNode(
                    id=f"{ordered[-1].story_id}_ending",
                    storyline_ids=[main_id] if main_id else [],
                    volume_id=ordered[-1].volume_id,
                    node_kind="ENDING",
                    title="Final ending",
                    description="Series final convergence ending node.",
                    depends_on=[n.id for n in nodes if n.node_kind == "CHECKPOINT"],
                    status=AnchorStatus.LOCKED,
                )
            )
        self._validate_dag(nodes)
        self._ensure_tier_convergence(nodes, storylines)
        self._validate_fork_merge(nodes)
        self._validate_strict_join(nodes, storylines)
        return nodes

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

    @staticmethod
    def _truncate_text_for_prompt(text: str, max_len: int) -> str:
        s = (text or "").strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    @staticmethod
    def _parse_a_tier_volume_index(storyline_id: str) -> int | None:
        """Pull the 1-indexed volume out of an A_TIER storyline id (``..._a_tier_vNN_..``).

        Returns ``None`` when the id wasn't produced by the fishbone builder
        (e.g. user-edit storylines), in which case we don't try to match by
        volume.
        """
        match = re.search(r"_a_tier_v(\d+)_", storyline_id or "")
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _match_user_subplot_hints_to_storylines(
        self,
        *,
        storylines: list[Storyline],
        volumes: list[VolumePlan],
        user_subplot_hints: list[dict[str, Any]] | None,
        b_storyline_volume_by_id: dict[str, str] | None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Pair each A/B (and S) storyline with the wizard's matching hint.

        Returns ``(user_hint_by_storyline_id, storyline_volume_id_by_id)``:

        - For S_TIER, hints are consumed in source order (S spans the book so
          there is no volume to match on).
        - For A_TIER, the id (``..._a_tier_vNN_..``) tells us which volume the
          storyline belongs to. We first consume hints whose ``volume`` matches
          that volume index in source order, then fall back to volume-less [A]
          hints to fill any leftover slots.
        - For B_TIER, we use ``b_storyline_volume_by_id`` (built upstream from
          user [B] hints) to know the storyline's target volume, then match
          hints by volume in source order, falling back to volume-less hints.

        Storylines without a matched hint are simply omitted from the result —
        their slot-fill row keeps the original "invent from scratch" behaviour.
        """
        volumes_by_index = {i + 1: v.volume_id for i, v in enumerate(volumes)}
        hints = list(user_subplot_hints or [])
        b_volume_by_storyline = dict(b_storyline_volume_by_id or {})

        # Bucket hints by tier first, then by volume (None = volume-less hint).
        # We preserve in-source order within each (tier, volume) bucket so the
        # wizard's display order maps to the storyline numbering 01, 02, ...
        buckets: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for h in hints:
            tier = str(h.get("tier", "")).upper()
            if tier not in ("S", "A", "B"):
                continue
            vol = h.get("volume") if tier in ("A", "B") else None
            buckets.setdefault((tier, vol if isinstance(vol, int) else None), []).append(h)

        user_hint_by_storyline_id: dict[str, dict[str, Any]] = {}
        storyline_volume_id_by_id: dict[str, str] = {}

        def _consume(tier: str, volume_idx: int | None) -> dict[str, Any] | None:
            """Pop the next unconsumed hint for (tier, volume) — fall back to volume-less."""
            if volume_idx is not None:
                primary = buckets.get((tier, volume_idx))
                if primary:
                    return primary.pop(0)
            floating = buckets.get((tier, None))
            if floating:
                return floating.pop(0)
            return None

        # Group A_TIER storylines by their volume so we consume hints per-volume
        # in id order, mirroring the deterministic storyline numbering.
        a_by_volume: dict[int, list[Storyline]] = {}
        s_storylines: list[Storyline] = []
        b_storylines: list[Storyline] = []
        for s in storylines:
            stype = s.type
            if stype == StorylineTier.S_TIER:
                s_storylines.append(s)
            elif stype == StorylineTier.A_TIER:
                vol_idx = self._parse_a_tier_volume_index(s.id)
                if vol_idx is None:
                    continue
                a_by_volume.setdefault(vol_idx, []).append(s)
                vol_id = volumes_by_index.get(vol_idx)
                if vol_id:
                    storyline_volume_id_by_id[s.id] = vol_id
            elif stype == StorylineTier.B_TIER:
                b_storylines.append(s)
                vol_id = b_volume_by_storyline.get(s.id)
                if vol_id:
                    storyline_volume_id_by_id[s.id] = vol_id

        for s in s_storylines:
            hint = _consume("S", None)
            if hint:
                user_hint_by_storyline_id[s.id] = hint

        for vol_idx in sorted(a_by_volume.keys()):
            for s in a_by_volume[vol_idx]:
                hint = _consume("A", vol_idx)
                if hint:
                    user_hint_by_storyline_id[s.id] = hint

        for s in b_storylines:
            vol_id = storyline_volume_id_by_id.get(s.id)
            vol_idx: int | None = None
            if vol_id:
                # Reverse-lookup volume index from volume_id so we can match
                # hints by 1-indexed `volume` field.
                vol_idx = next((i for i, vid in volumes_by_index.items() if vid == vol_id), None)
            hint = _consume("B", vol_idx)
            if hint:
                user_hint_by_storyline_id[s.id] = hint

        return user_hint_by_storyline_id, storyline_volume_id_by_id

    def _build_macro_narrative_context(
        self,
        *,
        storylines: list[Storyline],
        bible: dict[str, Any],
        volumes: list[VolumePlan],
        cast_stored: list[StoryCastMemberStored],
        audience: Literal["all", "mainline"] = "all",
    ) -> dict[str, Any]:
        if audience == "mainline":
            visible_storylines = [s for s in storylines if s.type == StorylineTier.MAIN]
        else:
            visible_storylines = list(storylines)
        return {
            "storylines": [
                {
                    "id": s.id,
                    "type": s.type.value if hasattr(s.type, "value") else str(s.type),
                    "title": s.title,
                    "overall_goal": s.overall_goal,
                    "involved_entities": list(s.involved_entities or []),
                }
                for s in visible_storylines
            ],
            "bible_excerpt": self._truncate_text_for_prompt(
                json.dumps(bible, ensure_ascii=False, default=str), 4500
            ),
            "volumes": [
                {
                    "volume_id": v.volume_id,
                    "title": v.title,
                    "summary": v.summary,
                    "chapter_start": v.chapter_start,
                    "chapter_end": v.chapter_end,
                }
                for v in volumes
            ],
            "cast": [
                {
                    "node_id": c.node_id,
                    "canonical_name": c.canonical_name,
                    "role": c.role,
                    "short_bio": self._truncate_text_for_prompt(c.short_bio or "", 200),
                }
                for c in cast_stored
            ],
        }

    def _storyline_slot_fill_prompt(
        self,
        *,
        story_input: StoryInput,
        storylines: list[Storyline],
        allowed_cast_node_ids: list[str],
        bible: dict[str, Any],
        volumes: list[VolumePlan],
        cast_stored: list[StoryCastMemberStored],
        user_hint_by_storyline_id: dict[str, dict[str, Any]] | None = None,
        storyline_volume_id_by_id: dict[str, str] | None = None,
    ) -> str:
        user_hint_by_storyline_id = user_hint_by_storyline_id or {}
        storyline_volume_id_by_id = storyline_volume_id_by_id or {}
        rows: list[dict[str, Any]] = []
        has_any_user_hint = False
        for s in storylines:
            row: dict[str, Any] = {
                "storyline_id": s.id,
                "type": s.type.value if hasattr(s.type, "value") else str(s.type),
                "seed_title": s.title,
                "seed_overall_goal": s.overall_goal,
                "seed_involved_entities": list(s.involved_entities or []),
            }
            vol_id = storyline_volume_id_by_id.get(s.id)
            if vol_id:
                # Surface the per-storyline volume binding so the model can
                # ground A/B side arcs in that volume's setup.
                row["volume_id"] = vol_id
            hint = user_hint_by_storyline_id.get(s.id)
            if hint:
                has_any_user_hint = True
                row["user_hint"] = {
                    "title": str(hint.get("title") or ""),
                    "goal": str(hint.get("goal") or ""),
                }
                vol_hint = hint.get("volume")
                if isinstance(vol_hint, int):
                    row["user_hint"]["volume"] = vol_hint
            rows.append(row)

        rules = [
            "You can only fill title, overall_goal, and involved_entities for each storyline_id.",
            "Do not add, remove, or rename storyline rows; keep storyline_id values exactly as given.",
            "involved_entities MUST be a subset of allowed_cast_node_ids (use those exact strings).",
            "S_TIER: book-spanning important side service to the main spine; A_TIER: volume-scoped support; B_TIER: short texture beats.",
            "Write in the configured output_language. No plot spoilers of the final ending.",
        ]
        if has_any_user_hint:
            # When the wizard pinned an A/B subplot to this volume we want the
            # model to refine the user's seed rather than invent a fresh angle;
            # storylines without a user_hint should still follow the original
            # auto-generation path so we don't lose texture coverage.
            rules.extend([
                "Some rows include a `user_hint` object containing the wizard's title/goal seed for that A/B subplot (and the volume it targets). For those rows you MUST treat the hint as the source of truth: keep its intent, refine wording, and tighten alignment with bible/volume context; do NOT replace the user's premise with a different idea.",
                "Rows without `user_hint` follow the original behaviour — invent the title/overall_goal from scratch, grounded in volume context and the storyline tier.",
                "If a row has both `volume_id` and `user_hint.volume`, anchor the goal inside that volume's narrative beats.",
            ])
        return json.dumps(
            {
                "task": "Fill storyline content slots only; do not change storyline ids or tier types.",
                "output_language": normalize_output_language(story_input.output_language),
                "rules": rules,
                "allowed_cast_node_ids": allowed_cast_node_ids,
                "bible_excerpt": self._truncate_text_for_prompt(
                    json.dumps(bible, ensure_ascii=False, default=str), 4500
                ),
                "volumes": [
                    {
                        "volume_id": v.volume_id,
                        "title": v.title,
                        "summary": v.summary,
                        "chapter_start": v.chapter_start,
                        "chapter_end": v.chapter_end,
                    }
                    for v in volumes
                ],
                "cast": [
                    {
                        "node_id": c.node_id,
                        "canonical_name": c.canonical_name,
                        "role": c.role,
                        "short_bio": self._truncate_text_for_prompt(c.short_bio or "", 200),
                    }
                    for c in cast_stored
                ],
                "storylines": rows,
                "output_shape": {
                    "items": [
                        {
                            "storyline_id": "string",
                            "title": "string",
                            "overall_goal": "string",
                            "involved_entities": ["cast node_id"],
                        }
                    ]
                },
            },
            ensure_ascii=False,
        )

    def _fill_storyline_slots(
        self,
        *,
        story_input: StoryInput,
        llm_client: LLMClient | None,
        storylines: list[Storyline],
        cast_stored: list[StoryCastMemberStored],
        volumes: list[VolumePlan],
        bible: dict[str, Any],
        user_subplot_hints: list[dict[str, Any]] | None = None,
        b_storyline_volume_by_id: dict[str, str] | None = None,
    ) -> tuple[list[Storyline], dict[str, Any]]:
        if llm_client is None or isinstance(llm_client, MockLLMClient):
            return storylines, {"storyline_slot_fill_skipped": True, "storyline_slot_fill_retries": 0}
        allowed = {c.node_id for c in cast_stored}
        if not storylines or not allowed:
            return storylines, {"storyline_slot_fill_skipped": True, "storyline_slot_fill_retries": 0}
        user_hint_by_storyline_id, storyline_volume_id_by_id = self._match_user_subplot_hints_to_storylines(
            storylines=storylines,
            volumes=volumes,
            user_subplot_hints=user_subplot_hints,
            b_storyline_volume_by_id=b_storyline_volume_by_id,
        )
        profile = augment_profile_system_prompt(get_profile("macro_planner"), story_input.output_language)
        by_id = {s.id: s for s in storylines}
        pending_ids = set(by_id.keys())
        retries = 0
        violations = 0

        for _ in range(2):
            if not pending_ids:
                break
            pending_ordered = [by_id[sid] for sid in (s.id for s in storylines) if sid in pending_ids]
            prompt = self._storyline_slot_fill_prompt(
                story_input=story_input,
                storylines=pending_ordered,
                allowed_cast_node_ids=sorted(allowed),
                bible=bible,
                volumes=volumes,
                cast_stored=cast_stored,
                user_hint_by_storyline_id=user_hint_by_storyline_id,
                storyline_volume_id_by_id=storyline_volume_id_by_id,
            )
            try:
                structured, _ = llm_client.invoke_json(prompt, _LLMStorylineSlotOutput, profile)
            except Exception:
                break
            for item in structured.items:
                sid = (item.storyline_id or "").strip()
                if sid not in pending_ids or sid not in by_id:
                    continue
                title = (item.title or "").strip()
                goal = (item.overall_goal or "").strip()
                ents = [e for e in (item.involved_entities or []) if e in allowed]
                if not title or not goal:
                    violations += 1
                    continue
                if not ents and (by_id[sid].involved_entities or []):
                    ents = [e for e in (by_id[sid].involved_entities or []) if e in allowed][:5]
                if not ents and allowed:
                    ents = [sorted(allowed)[0]]
                by_id[sid] = by_id[sid].model_copy(
                    update={"title": title, "overall_goal": goal, "involved_entities": ents[:8]}
                )
                pending_ids.discard(sid)
            if not pending_ids:
                break
            retries += 1
        return [by_id[s.id] for s in storylines], {
            "storyline_slot_fill_skipped": False,
            "storyline_slot_fill_retries": retries,
            "storyline_slot_policy_violations": violations,
            "storyline_slot_pending_ids": sorted(pending_ids),
            "storyline_user_hint_matches": len(user_hint_by_storyline_id),
            "storyline_user_hint_matched_ids": sorted(user_hint_by_storyline_id.keys()),
        }

    def _slot_fill_prompt(
        self,
        *,
        story_input: StoryInput,
        stage_label: str,
        node_rows: list[dict[str, Any]],
        context_summary: str = "",
        narrative_context: dict[str, Any] | None = None,
        prior_main_batch_summaries: list[dict[str, Any]] | None = None,
        batch_hint: dict[str, Any] | None = None,
        main_batch_summaries: list[dict[str, Any]] | None = None,
        expect_batch_summary: bool = False,
        extra_rules: list[str] | None = None,
    ) -> str:
        base_rules = [
            "You can only fill title and description.",
            "Do not invent or modify node_id, depends_on, node_kind, storyline_ids, volume_id.",
            "Return one item for each input node_id.",
            "Use narrative_context (storylines, bible_excerpt, volumes, cast) to keep anchors aligned with the macro plan and each storyline's overall_goal.",
            "Each node description must strictly match the spatiotemporal context implied by its depends_on predecessors.",
            "No deterministic breakthrough ahead of mainline schedule.",
            "If any rule is violated, rewrite the offending item and keep topology unchanged.",
        ]
        rules = list(base_rules)
        if extra_rules:
            rules.extend(extra_rules)
        output_shape: dict[str, Any] = {
            "items": [{"node_id": "string", "title": "string", "description": "string"}]
        }

        if expect_batch_summary:
            rules.extend([
                "Additionally output batch_summary: one concise recap of the mainline beats filled in THIS batch only.",
                f"batch_summary must be under ~{MAIN_SLOT_BATCH_SUMMARY_MAX} characters and in output_language.",
                "prior_main_batch_summaries summarizes earlier mainline batches; stay consistent with it.",
            ])
            output_shape["batch_summary"] = (
                f"string (concise recap of this batch mainline beats, max ~{MAIN_SLOT_BATCH_SUMMARY_MAX} chars)"
            )

        if main_batch_summaries is not None:
            rules.extend([
                "main_batch_summaries lists recap per completed mainline batch (batch_index, volume_id, summary). Honor series pacing.",
                "Each node row includes attachment_context (program-supplied): use spine_windows, main_spine_mount_nodes, and depends_on_context together.",
                "Do not contradict attachment_context mount windows or earlier batch summaries.",
            ])

        payload: dict[str, Any] = {
            "task": "Fill content slots only; never modify topology fields.",
            "stage": stage_label,
            "output_language": normalize_output_language(story_input.output_language),
            "rules": rules,
            "context_summary": context_summary,
            "narrative_context": narrative_context or {},
            "nodes": node_rows,
            "output_shape": output_shape,
        }
        if prior_main_batch_summaries is not None:
            payload["prior_main_batch_summaries"] = prior_main_batch_summaries
        if batch_hint is not None:
            payload["batch_hint"] = batch_hint
        if main_batch_summaries is not None:
            payload["main_batch_summaries"] = main_batch_summaries
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _partition_mainline_batches(
        main_nodes: list[AnchorNode], volumes: list[VolumePlan]
    ) -> list[list[AnchorNode]]:
        by_vol: dict[str, list[AnchorNode]] = {}
        for n in main_nodes:
            by_vol.setdefault(n.volume_id, []).append(n)
        return [by_vol[v.volume_id] for v in volumes if v.volume_id in by_vol]

    @staticmethod
    def _main_spine_sequence(main_nodes: list[AnchorNode], volumes: list[VolumePlan]) -> list[str]:
        vol_rank = {v.volume_id: i for i, v in enumerate(volumes)}
        indices = sorted(range(len(main_nodes)), key=lambda i: (vol_rank.get(main_nodes[i].volume_id, 9999), i))
        return [main_nodes[i].id for i in indices]

    @staticmethod
    def _chunk_list_evenly(items: list[Any], max_chunks: int) -> list[list[Any]]:
        if not items:
            return []
        k = min(max(max_chunks, 1), len(items))
        n = len(items)
        base, rem = divmod(n, k)
        chunks: list[list[Any]] = []
        idx = 0
        for i in range(k):
            sz = base + (1 if i < rem else 0)
            chunks.append(items[idx : idx + sz])
            idx += sz
        return chunks

    def _fallback_batch_summary_for_nodes(self, batch: list[AnchorNode], by_id: dict[str, AnchorNode]) -> str:
        titles: list[str] = []
        for n in batch:
            row = by_id.get(n.id)
            if row and str(row.title or "").strip():
                titles.append(str(row.title).strip())
        s = "; ".join(titles) if titles else "Mainline batch pacing recap."
        return s[:MAIN_SLOT_BATCH_SUMMARY_MAX]

    def _build_side_attachment_context(
        self,
        node: AnchorNode,
        *,
        by_id: dict[str, AnchorNode],
        main_node_ids: set[str],
        main_spine_sequence: list[str],
    ) -> dict[str, Any]:
        mount_ids = [str(d).strip() for d in (node.depends_on or []) if str(d).strip() in main_node_ids]
        spine_windows: list[dict[str, Any]] = []
        idx_map = {nid: i for i, nid in enumerate(main_spine_sequence)}

        def snapshot(nid: str) -> dict[str, str]:
            row = by_id.get(nid)
            if not row:
                return {"node_id": nid, "title": "", "description": "", "volume_id": ""}
            return {
                "node_id": row.id,
                "title": str(row.title or ""),
                "description": str(row.description or ""),
                "volume_id": str(row.volume_id or ""),
            }

        for m in mount_ids:
            idx = idx_map.get(m)
            if idx is None:
                spine_windows.append({"mount_id": m, "window_node_ids": [m], "nodes": [snapshot(m)]})
                continue
            if idx >= 2:
                wids = main_spine_sequence[idx - 2 : idx + 1]
            else:
                wids = [m]
            spine_windows.append(
                {"mount_id": m, "window_node_ids": wids, "nodes": [snapshot(x) for x in wids if x in by_id]}
            )

        flat_mount_nodes: list[dict[str, str]] = []
        seen_flat: set[str] = set()
        for w in spine_windows:
            for node_row in w.get("nodes") or []:
                nid = str(node_row.get("node_id") or "")
                if nid and nid not in seen_flat:
                    seen_flat.add(nid)
                    flat_mount_nodes.append(node_row)

        non_main = [
            str(d).strip()
            for d in (node.depends_on or [])
            if str(d).strip() and str(d).strip() not in main_node_ids
        ]
        attachment_summary = ""
        if mount_ids:
            attachment_summary = (
                f"Side beat in volume {node.volume_id}; main spine mount ids: {', '.join(mount_ids)}."
            )
        elif non_main:
            attachment_summary = (
                f"Side beat in volume {node.volume_id}; depends on non-main predecessors only."
            )

        return {
            "spine_windows": spine_windows,
            "main_spine_mount_nodes": flat_mount_nodes,
            "non_main_predecessors": non_main,
            "storyline_ids": list(node.storyline_ids or []),
            "volume_id": str(node.volume_id or ""),
            "attachment_summary": attachment_summary,
        }

    def _slot_fill_policy_violations(self, text: str) -> int:
        t = (text or "").strip().lower()
        if not t:
            return 1
        violations = 0
        spoiler_hints = ("ending", "true mastermind", "all mysteries solved", "最終真相", "終局", "真兇揭露")
        if any(k in t for k in spoiler_hints):
            violations += 1
        # coarse anti-jump check for deterministic breakthroughs.
        premature_hints = ("definitively resolved", "completely solved", "徹底解決", "最終擊敗")
        if any(k in t for k in premature_hints):
            violations += 1
        return violations

    def _fill_anchor_slots(
        self,
        *,
        story_input: StoryInput,
        llm_client: LLMClient | None,
        anchor_nodes: list[AnchorNode],
        storylines: list[Storyline] | None = None,
        bible: dict[str, Any] | None = None,
        volumes: list[VolumePlan] | None = None,
        cast_stored: list[StoryCastMemberStored] | None = None,
    ) -> tuple[list[AnchorNode], dict[str, Any]]:
        if llm_client is None or isinstance(llm_client, MockLLMClient):
            return anchor_nodes, {"slot_fill_skipped": True, "slot_fill_retries": 0}
        profile = augment_profile_system_prompt(get_profile("macro_planner"), story_input.output_language)
        by_id = {n.id: n for n in anchor_nodes}
        main_nodes = [
            n
            for n in anchor_nodes
            if n.node_kind == "NORMAL" and any(sid.endswith("_main") for sid in n.storyline_ids)
        ]
        side_nodes = [n for n in anchor_nodes if n.node_kind == "NORMAL" and n.id not in {m.id for m in main_nodes}]
        main_node_ids = {n.id for n in main_nodes}
        narrative_block_mainline: dict[str, Any] | None = None
        narrative_block_side: dict[str, Any] | None = None
        if storylines is not None and bible is not None and volumes is not None and cast_stored is not None:
            narrative_block_mainline = self._build_macro_narrative_context(
                storylines=storylines,
                bible=bible,
                volumes=volumes,
                cast_stored=cast_stored,
                audience="mainline",
            )
            narrative_block_side = self._build_macro_narrative_context(
                storylines=storylines,
                bible=bible,
                volumes=volumes,
                cast_stored=cast_stored,
                audience="all",
            )

        mainline_extra_rules = [
            "These nodes are MAIN spine anchors only; describe only mainline conflict beats.",
            "narrative_context.storylines is filtered to MAIN-tier only. Treat side-arc / subplot threads as out of scope: never reference, hint at, or invent S_TIER / A_TIER / B_TIER material in title or description, even if such themes appear elsewhere (bible_excerpt, volume summaries, author notes).",
            "Do not introduce side-character personal storylines, subplot premises, or wizard-supplied side-arc seeds in mainline anchors.",
        ]
        side_extra_rules = [
            "S_TIER is a book-spanning important side arc (identity mystery, long-term growth) and must serve the mainline.",
            "A_TIER is a volume-scoped side arc (e.g., key item/ability acquisition) and must serve this volume mainline.",
            "B_TIER is a short side beat for texture and character charm, never a decisive plotline.",
            "No spoilers and no repetition: side-arc content must not duplicate mainline events.",
        ]

        vol_list = volumes or []
        main_batches = (
            self._partition_mainline_batches(main_nodes, vol_list) if vol_list else ([main_nodes] if main_nodes else [])
        )
        main_spine_sequence = (
            self._main_spine_sequence(main_nodes, vol_list) if vol_list else [n.id for n in main_nodes]
        )

        prior_summaries: list[dict[str, Any]] = []
        batch_summary_fallback_flags: list[bool] = []
        retries_main = 0
        violations_main = 0

        for batch_index, batch in enumerate(main_batches):
            if not batch:
                continue
            pending_ids = {n.id for n in batch}
            structured_out: _LLMSlotFillOutput | None = None
            for _attempt in range(2):
                payload_rows = [
                    {
                        "node_id": n.id,
                        "title": n.title,
                        "description": n.description,
                        "volume_id": n.volume_id,
                        "depends_on": list(n.depends_on or []),
                        "depends_on_context": [
                            {
                                "node_id": dep,
                                "title": str((by_id.get(dep) or n).title or ""),
                                "description": str((by_id.get(dep) or n).description or ""),
                            }
                            for dep in (n.depends_on or [])
                            if dep in by_id
                        ],
                    }
                    for n in batch
                    if n.id in pending_ids
                ]
                if not payload_rows:
                    break
                vol_hint = str(batch[0].volume_id or "") if batch else ""
                prompt = self._slot_fill_prompt(
                    story_input=story_input,
                    stage_label=f"stage3.1_mainline.batch{batch_index}",
                    node_rows=payload_rows,
                    context_summary="",
                    narrative_context=narrative_block_mainline,
                    prior_main_batch_summaries=list(prior_summaries),
                    batch_hint={"batch_index": batch_index, "volume_id": vol_hint},
                    expect_batch_summary=True,
                    extra_rules=mainline_extra_rules,
                )
                try:
                    structured_out, _ = llm_client.invoke_json(prompt, _LLMSlotFillOutput, profile)
                except Exception:
                    structured_out = None
                    break
                if structured_out:
                    for item in structured_out.items:
                        node_id = (item.node_id or "").strip()
                        if node_id not in pending_ids or node_id not in by_id:
                            continue
                        title = (item.title or "").strip()
                        desc = (item.description or "").strip()
                        policy_hits = self._slot_fill_policy_violations(f"{title}\n{desc}")
                        if policy_hits > 0:
                            violations_main += policy_hits
                            continue
                        if title and desc:
                            by_id[node_id] = by_id[node_id].model_copy(update={"title": title, "description": desc})
                            pending_ids.discard(node_id)
                if not pending_ids:
                    break
                retries_main += 1

            summary_fallback = False
            bs = (structured_out.batch_summary or "").strip() if structured_out else ""
            if not bs:
                bs = self._fallback_batch_summary_for_nodes(batch, by_id)
                summary_fallback = True
            else:
                bs = bs[:MAIN_SLOT_BATCH_SUMMARY_MAX]
            vol_hint = str(batch[0].volume_id or "") if batch else ""
            prior_summaries.append({"batch_index": batch_index, "volume_id": vol_hint, "summary": bs})
            batch_summary_fallback_flags.append(summary_fallback)

        side_context = " ".join([n.description for n in main_nodes[:8]])
        retries_side = 0
        violations_side = 0
        side_parallel_chunks_max = 0
        side_slot_workers_cap = get_settings().side_slot_fill_max_workers
        if side_nodes:
            pending_side = {n.id for n in side_nodes}

            def _run_side_slot_chunk(
                chunk_idx: int, chunk: list[AnchorNode]
            ) -> tuple[list[tuple[str, str, str]], int]:
                """Returns accepted (node_id, title, desc) pairs and policy violation count."""
                violations_local = 0
                payload = [
                    {
                        "node_id": n.id,
                        "title": n.title,
                        "description": n.description,
                        "volume_id": n.volume_id,
                        "depends_on": list(n.depends_on or []),
                        "depends_on_context": [
                            {
                                "node_id": dep,
                                "title": str((by_id.get(dep) or n).title or ""),
                                "description": str((by_id.get(dep) or n).description or ""),
                            }
                            for dep in (n.depends_on or [])
                            if dep in by_id
                        ],
                        "attachment_context": self._build_side_attachment_context(
                            n,
                            by_id=by_id,
                            main_node_ids=main_node_ids,
                            main_spine_sequence=main_spine_sequence,
                        ),
                    }
                    for n in chunk
                ]
                if not payload:
                    return [], 0
                side_prompt = self._slot_fill_prompt(
                    story_input=story_input,
                    stage_label=f"stage3.3_side_arcs.p{chunk_idx}",
                    node_rows=payload,
                    context_summary=side_context[:2000],
                    narrative_context=narrative_block_side,
                    main_batch_summaries=list(prior_summaries),
                    extra_rules=side_extra_rules,
                )
                try:
                    structured_side, _ = llm_client.invoke_json(side_prompt, _LLMSlotFillOutput, profile)
                except Exception:
                    logger.exception("side slot-fill invoke_json failed chunk_index=%s", chunk_idx)
                    return [], 0
                accepted: list[tuple[str, str, str]] = []
                for item in structured_side.items:
                    node_id = (item.node_id or "").strip()
                    title = (item.title or "").strip()
                    desc = (item.description or "").strip()
                    policy_hits = self._slot_fill_policy_violations(f"{title}\n{desc}")
                    if policy_hits > 0:
                        violations_local += policy_hits
                        continue
                    if title and desc:
                        accepted.append((node_id, title, desc))
                return accepted, violations_local

            for _attempt in range(2):
                if not pending_side:
                    break
                pending_ordered = [n for n in side_nodes if n.id in pending_side]
                chunk_lists = self._chunk_list_evenly(pending_ordered, side_slot_workers_cap)
                side_parallel_chunks_max = max(side_parallel_chunks_max, len(chunk_lists))
                merged_updates: list[tuple[list[tuple[str, str, str]], int]] = []
                with ThreadPoolExecutor(max_workers=len(chunk_lists)) as executor:
                    futures = [
                        executor.submit(_run_side_slot_chunk, idx, ch)
                        for idx, ch in enumerate(chunk_lists)
                    ]
                    for fut in as_completed(futures):
                        try:
                            merged_updates.append(fut.result())
                        except Exception:
                            logger.exception("side slot-fill worker raised")
                            merged_updates.append(([], 0))
                for updates, vloc in merged_updates:
                    violations_side += vloc
                    for node_id, title, desc in updates:
                        if node_id not in pending_side or node_id not in by_id:
                            continue
                        policy_hits = self._slot_fill_policy_violations(f"{title}\n{desc}")
                        if policy_hits > 0:
                            violations_side += policy_hits
                            continue
                        by_id[node_id] = by_id[node_id].model_copy(update={"title": title, "description": desc})
                        pending_side.discard(node_id)
                if not pending_side:
                    break
                retries_side += 1

        return [by_id[n.id] for n in anchor_nodes], {
            "slot_fill_skipped": False,
            "slot_fill_retries": retries_main + retries_side,
            "slot_fill_policy_violations": violations_main + violations_side,
            "slot_fill_mainline_count": len(main_nodes),
            "slot_fill_side_count": len(side_nodes),
            "main_batch_summaries": prior_summaries,
            "main_batch_count": len(prior_summaries),
            "batch_summary_fallback_flags": batch_summary_fallback_flags,
            "side_slot_fill_parallel_workers_cap": side_slot_workers_cap,
            "side_slot_fill_parallel_chunks_max": side_parallel_chunks_max,
        }

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
                story_id, structured_output, fixed_total_chapters, story_input.target_total_words, story_input, llm_client
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
        return self._normalize_macro_plan(
            story_id,
            plan,
            total_chapters,
            story_input.target_total_words,
            story_input,
            None,
        )

    def _fallback_bible_from_premise(self, story_input: StoryInput) -> dict[str, Any]:
        premise = (story_input.premise or "")[:800]
        lore = (
            f"## Premise seed\n\n{premise}\n\n"
            "## Defaults\n\n"
            "- Clear narration, steady pacing\n"
            "- Third-person limited\n"
            "- Tone derives naturally from premise\n"
            "- World rules and factions emerge as chapters progress\n"
        )
        return {
            "story_genre": "unspecified",
            "general_world_lore": lore.strip(),
        }

    def _normalize_generated_bible(self, story_input: StoryInput, output: MacroPlanOutput) -> dict[str, Any]:
        from app.services.workflow.bible_general_lore import synthesize_general_world_lore_from_legacy

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
            if not str(out.get("general_world_lore") or "").strip():
                out["general_world_lore"] = synthesize_general_world_lore_from_legacy(out)
            for k in ("tone", "theme", "narrative_pov", "writing_style", "world_rules", "factions", "writing_note"):
                out.pop(k, None)
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
                chapter_target=0,
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
        tri_language_rules: list[str] = [
            self._tri_instruction(
                "所有自然語言欄位（bible、cast、volumes、anchors 的 title/summary/description/notes）必須完全使用故事設定語言，不可混用其他語言；JSON key 與 enum 值維持英文。",
                "所有自然语言字段（bible、cast、volumes、anchors 的 title/summary/description/notes）必须完全使用故事设定语言，不可混用其他语言；JSON key 与 enum 值保持英文。",
                "All natural-language fields (bible, cast, volumes, anchors title/summary/description/notes) must be entirely in the story output language; keep JSON keys and enum values in English.",
            ),
            self._tri_instruction(
                "不要把指令語言視為輸出語言；即使看到三語說明，你仍只可用 output_language 產出內容。",
                "不要把指令语言当作输出语言；即使看到三语说明，你仍只可用 output_language 产出内容。",
                "Do not treat instruction language as output language; even with trilingual instructions, produce content only in output_language.",
            ),
            self._tri_instruction(
                "主線與副線定義：MAIN 是主衝突骨幹；S_TIER 是全書長弧壓力線；A_TIER 是每卷服務主線的關鍵支線；B_TIER 是短支線/微事件，只能加質感不可偏離主線。",
                "主线与副线定义：MAIN 是主冲突骨干；S_TIER 是全书长弧压力线；A_TIER 是每卷服务主线的关键支线；B_TIER 是短支线/微事件，只能加质感不可偏离主线。",
                "Main/side definitions: MAIN is the core conflict spine; S_TIER is series-long pressure arc; A_TIER is per-volume key side thread serving the volume mainline; B_TIER is short micro-beat adding texture without derailing the mainline.",
            ),
            self._tri_instruction(
                "支線規則：所有副線（S/A/B）都必須服務主線推進，且事件範圍不得超出所屬卷的劇情邊界。",
                "支线规则：所有副线（S/A/B）都必须服务主线推进，且事件范围不得超出所属卷的剧情边界。",
                "Side-thread rule: every S/A/B thread must advance the mainline and stay within its volume narrative scope.",
            ),
            self._tri_instruction(
                "Anchor 事件規則：每個 anchor 必須是可在單章內完成的具體物理事件，描述可驗證且可結算。",
                "Anchor 事件规则：每个 anchor 必须是可在单章内完成的具体物理事件，描述可验证且可结算。",
                "Anchor event rule: each anchor must be a concrete, physically verifiable event achievable within one chapter.",
            ),
        ]
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
                        "general_world_lore": "string (markdown; genre, tone, POV, style, rules, factions, craft notes)",
                        "extra": "optional object - custom world metadata only; do not duplicate general_world_lore here",
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
                                    "dag_order": "int optional",
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
                    "anchor order is defined by DAG dependency and priority, not chapter target.",
                    "You must output bible: concrete, executable, and consistent with volumes, anchors, and cast; you may add reasonable extra keys inside bible.",
                    "Put narrative craft and world tone in bible.general_world_lore as markdown; optional bible.story_genre for classification.",
                    "extra may only hold other supplemental keys; do not duplicate general_world_lore (backend will drop duplicate keys from extra).",
                    "When macro_author_notes is non-empty, bible and plot planning must respect it.",
                    "When macro_author_notes is non-empty: each cast member notes_links must be a non-empty array whose entries are only ids from notes_keypoints (e.g. KP1, KP2); "
                    "each volume anchor notes_links must likewise be non-empty and drawn only from notes_keypoints ids.",
                    "Each anchor.target_state must be concrete and trackable.",
                    "Do not place anchors outside volumes; nest anchors only inside their owning volume.",
                    *script_shape_req,
                    *cast_req,
                    "speech_style / quirks_and_habits are occasional flavor - do not design them as every-line catchphrases.",
                    *tri_language_rules,
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
        llm_client: LLMClient | None = None,
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

        staged.sort(key=lambda row: (row[1].priority, row[1].title))
        anchors: list[StateAnchor] = []
        for index, (volume, draft) in enumerate(staged, start=1):
            anchors.append(
                StateAnchor(
                    anchor_id=f"{story_id}_anchor_{index:02d}",
                    story_id=story_id,
                    volume_id=volume.volume_id,
                    title=draft.title,
                    description=draft.description,
                    target_state=dict(draft.target_state or {}),
                    chapter_target=0,
                    priority=draft.priority,
                )
            )
        cast_stored = self._normalize_cast_output(story_id, output.cast, story_input)
        compile_warnings: list[str] = []
        user_subplot_hints = extract_user_subplot_hints(
            getattr(story_input, "macro_author_notes", "") or ""
        )
        storylines, fishbone_meta = self._build_fishbone_storylines(
            story_id, volumes, cast_stored, user_subplot_hints=user_subplot_hints
        )
        b_storyline_volume_by_id = dict(
            fishbone_meta.get("b_storyline_volume_by_id") or {}
        )
        storylines, storyline_slot_meta = self._fill_storyline_slots(
            story_input=story_input,
            llm_client=llm_client,
            storylines=storylines,
            cast_stored=cast_stored,
            volumes=volumes,
            bible=bible_out,
            user_subplot_hints=user_subplot_hints,
            b_storyline_volume_by_id=b_storyline_volume_by_id,
        )
        anchor_nodes = self._build_fishbone_anchor_nodes(
            story_id=story_id,
            anchors=anchors,
            storylines=storylines,
            volumes=volumes,
            a_lines_per_volume=dict(fishbone_meta.get("a_lines_per_volume") or {}),
            b_storyline_volume_by_id=b_storyline_volume_by_id,
        )
        self._validate_dag(anchor_nodes)
        self._ensure_tier_convergence(anchor_nodes, storylines)
        self._validate_fork_merge(anchor_nodes)
        self._validate_strict_join(anchor_nodes, storylines)
        self._validate_fishbone_dependencies(anchor_nodes, storylines)
        anchor_nodes, slot_meta = self._fill_anchor_slots(
            story_input=story_input,
            llm_client=llm_client,
            anchor_nodes=anchor_nodes,
            storylines=storylines,
            bible=bible_out,
            volumes=volumes,
            cast_stored=cast_stored,
        )
        weave_meta = {
            "topology_mode": "fixed_fishbone",
            "llm_topology_generation": False,
            "fishbone_meta": fishbone_meta,
            **storyline_slot_meta,
            **slot_meta,
        }
        branch_count = self._branch_count_for_story(story_input)
        # Keep topology in compile output payload for service-layer persistence;
        # StoryRepository strips these out of bible_json and stores them in dedicated columns.
        bible_out["storylines"] = [s.model_dump(mode="json") for s in storylines]
        bible_out["anchor_nodes"] = [n.model_dump(mode="json") for n in anchor_nodes]
        bible_out["branch_count_final"] = branch_count
        bible_out["llm_weave_debug"] = weave_meta
        if compile_warnings:
            bible_out["compile_warnings"] = compile_warnings
        return volumes, anchors, cast_stored, [], bible_out

    def _coerce_volume_anchors(self, volume: VolumePlan, raw: list[MacroNestedAnchorDraft]) -> list[MacroNestedAnchorDraft]:
        clamped: list[MacroNestedAnchorDraft] = []
        for a in sorted(raw, key=lambda x: (x.priority, x.title)):
            clamped.append(a.model_copy(update={"chapter_target": 0}))

        if len(clamped) > MAX_ANCHORS_PER_VOLUME:
            clamped = clamped[:MAX_ANCHORS_PER_VOLUME]

        pad_i = 0
        while len(clamped) < MIN_ANCHORS_PER_VOLUME:
            span = volume.chapter_end - volume.chapter_start + 1
            step = max(1, span // (MIN_ANCHORS_PER_VOLUME + 1))
            clamped.append(
                MacroNestedAnchorDraft(
                    title=f"{volume.title} padding beat {pad_i + 1}",
                    description=f"Plot beat placeholder inside {volume.title} (system-padded).",
                    target_state={"volume.placeholder": pad_i + 1},
                    chapter_target=0,
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
