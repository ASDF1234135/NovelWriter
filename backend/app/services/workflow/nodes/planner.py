from __future__ import annotations

import json

from app.core.config import get_settings
from app.domain.schema import BStorySeed, EventOutline, NodeType, PlannerOutput, ProposedGraphNode
from app.domain.state import SafePlannerPayload
from app.services.llm import MockLLMClient
from app.services.workflow.chapter_words import clamp_chapter_word_count
from app.services.workflow.context import WorkflowContext
from app.services.workflow.constants import (
    PLANNER_BIBLE_CONTEXT_CAP,
    PLANNER_CONTINUITY_NOTE_MAX_CHARS,
    PLANNER_CONTINUITY_NOTE_MAX_ITEMS,
    PLANNER_ENTITY_NAME_MAX_CHARS,
    PLANNER_ENTITY_NAME_MAX_ITEMS,
    PLANNER_GRAPH_CONTEXT_CAP,
    PLANNER_PREVIOUS_CHAPTER_SUMMARY_CAP,
    PLANNER_PREVIOUS_NARRATIVE_CAP,
    PLANNER_PRIOR_FEEDBACK_MAX_ITEMS,
    PLANNER_RECENT_CHAPTER_CONTEXT_CAP,
    PLANNER_UPCOMING_ANCHORS_JSON_CAP,
    PLANNER_VECTOR_CONTEXT_CAP,
    PLANNER_VOLUME_SUMMARY_CAP,
)
from app.services.workflow.masking import build_planner_payload
from app.services.workflow.profiles import get_profile


def _mock_author_safe_continuity_notes(raw: list[str]) -> list[str]:
    """Mock path: drop vector unresolved-thread lines; keep other continuity strings."""
    safe: list[str] = []
    for line in raw or []:
        text = (line or "").strip()
        if not text:
            continue
        if "未解線索" in text or "章未解" in text:
            continue
        safe.append(text)
        if len(safe) >= 4:
            break
    return safe


def _clip(text: str, max_len: int) -> str:
    if not text:
        return text
    return text[:max_len] if len(text) > max_len else text


def _clip_note_lines(notes: list[str]) -> list[str]:
    out: list[str] = []
    for raw in (notes or [])[:PLANNER_CONTINUITY_NOTE_MAX_ITEMS]:
        line = (raw or "").strip()
        if not line:
            continue
        out.append(_clip(line, PLANNER_CONTINUITY_NOTE_MAX_CHARS))
    return out


def _clip_entity_names(names: list[str]) -> list[str]:
    out: list[str] = []
    for raw in (names or [])[:PLANNER_ENTITY_NAME_MAX_ITEMS]:
        n = (raw or "").strip()
        if not n:
            continue
        out.append(_clip(n, PLANNER_ENTITY_NAME_MAX_CHARS))
    return out


def run_planner(state: dict, context: WorkflowContext) -> tuple[dict, dict, int, int]:
    settings = get_settings()
    story = context.story_repository.get_story(state["story_id"]) or {}
    volumes = context.story_repository.list_volumes(state["story_id"])
    payload = build_planner_payload(state, story=story, volumes=volumes)
    prompt = _build_planner_prompt(payload)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("planner")
        structured_output, llm_result = context.llm_client.invoke_json(prompt, PlannerOutput, profile)
        clamped = clamp_chapter_word_count(
            structured_output.target_word_count,
            settings.chapter_word_min,
            settings.chapter_word_max,
        )
        nodes = list(structured_output.proposed_new_nodes)[:3]
        seeds = list(structured_output.new_active_b_stories)[:2]
        out = structured_output.model_dump(mode="json")
        out["proposed_new_nodes"] = [n.model_dump(mode="json") if isinstance(n, ProposedGraphNode) else n for n in nodes]
        out["new_active_b_stories"] = [
            s.model_dump(mode="json") if isinstance(s, BStorySeed) else s for s in seeds
        ]
        out["target_word_count"] = clamped
        return out, payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms

    llm_result = context.llm_client.invoke(prompt)
    anchor_hint = payload.target_anchor_id or "無特定錨點"
    continuity_hint = f"承接上一章：{payload.previous_chapter_summary}。" if payload.previous_chapter_summary else ""
    continuity_notes = " ".join(payload.continuity_notes[:2])
    start_location = payload.last_known_location or "延續上一場景"
    end_location = payload.last_known_location or "當前行動場景"
    boundary_rule = f"本章最遠只能收束在 {end_location}；若需要進入下一個完整場景、室內空間或新任務節點，必須留到下一章。"
    mock_target = clamp_chapter_word_count(
        payload.default_chapter_words,
        settings.chapter_word_min,
        settings.chapter_word_max,
    )
    mock_nodes: list[ProposedGraphNode] = []
    for label in (payload.new_elements_to_introduce or [])[:3]:
        if not (label or "").strip():
            continue
        mock_nodes.append(
            ProposedGraphNode(
                node_id=f"char_gen_{state['chapter_id']}_{len(mock_nodes) + 1}",
                node_type=NodeType.CHARACTER,
                role=str(label)[:80],
                canonical_name=str(label)[:80],
                writing_brief="請在正文以可辨識特徵寫出此角色。",
                mandatory=True,
            )
        )
    output = PlannerOutput(
        ground_truth_events=[
            EventOutline(
                event_id=f"event_ch{state['chapter_id']}_01",
                description=f"主角在 {start_location} 接收到指向 {anchor_hint} 的新線索，開始採取新的行動。",
                caused_by_event_id=None,
            ),
            EventOutline(
                event_id=f"event_ch{state['chapter_id']}_02",
                description=f"主角在壓力下做出具風險的推進決定，局勢因此改變，章末停留在 {end_location}。",
                caused_by_event_id=f"event_ch{state['chapter_id']}_01",
            ),
        ],
        narrative_script=(
            f"{continuity_hint}"
            f"本章開場延續 {start_location} 的局勢，先讓主角處理新的線索或新的阻力，"
            f"再把場面推向下一步。若要切換場景，必須寫出移動或過渡。"
            f"章節必須朝向 {anchor_hint} 推進，不能只是重講上一章。"
            f"{continuity_notes}"
        ),
        target_word_count=mock_target,
        chapter_start_location=start_location,
        author_goal="讓本章完成一個可見的劇情推進，並把主角推向下一步行動。",
        must_include_beats=[
            "主角必須採取一個具體行動，而不是只觀察或回想。",
            "本章必須新增至少一個可被讀者感知的發現或證據。",
            "若場景切換，必須先交代移動或過渡，再進入新地點。",
            "章末必須讓局勢、認知或風險相較章初出現明確變化。",
        ],
        reader_visible_facts=[
            f"讀者應清楚感受到本章正朝 {anchor_hint} 推進。",
        ],
        reader_unresolved_questions=[
            "真相尚未完整揭露，讀者只能看到局部線索與表面矛盾。",
        ],
        private_facts_or_secret_actions=[
            "若本章存在秘密行動或私下觀察，必須保留為非公開資訊，不可寫成人人皆知的常識。",
        ],
        ending_state_shift="章末時主角必須比章初更接近真相，也更接近新的風險。",
        chapter_end_location_hint=end_location,
        ending_boundary_rule=boundary_rule,
        forbidden_next_scene_actions=[
            "不要在本章跨出章末有效位置之後，再進入新的場景或新地點。",
            "不要在本章提前解除懸念、完成下一章才應發生的會面、進屋或轉場。",
        ],
        forbidden_reveals=[
            "不要直接揭露尚未到揭曉時機的底層真相。",
            "不要新增與當前章節任務無關的新機關、新謎團或新世界規則。",
        ],
        author_safe_continuity_notes=_mock_author_safe_continuity_notes(payload.continuity_notes),
        proposed_new_nodes=mock_nodes,
        new_active_b_stories=[],
    )
    dumped = output.model_dump(mode="json")
    dumped["proposed_new_nodes"] = [n.model_dump(mode="json") for n in mock_nodes[:3]]
    dumped["new_active_b_stories"] = []
    return dumped, payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms


def _build_planner_prompt(payload: SafePlannerPayload) -> str:
    upcoming_json = json.dumps(payload.upcoming_unachieved_anchors, ensure_ascii=False)
    upcoming_json = _clip(upcoming_json, PLANNER_UPCOMING_ANCHORS_JSON_CAP)
    prior_fb = (payload.prior_feedback or [])[-PLANNER_PRIOR_FEEDBACK_MAX_ITEMS:]
    prev_events = [event.model_dump(mode="json") for event in payload.previous_attempt_ground_truth_events]
    return (
        "請依照以下安全載荷產出底層真實大綱與表層敘事劇本。\n\n"
        "## 字數與本章內容（必做）\n"
        f"- default_chapter_words: {payload.default_chapter_words}（僅作參考起點，**非**卷字數攤分或硬性配額）\n"
        f"- 允許的 target_word_count 硬邊界：{payload.chapter_word_min} ~ {payload.chapter_word_max}（後端會截斷越界值）\n"
        "- 你必須輸出 `target_word_count`（整數）。請依本章 **ground_truth_events 複雜度、場景轉換、對白與動作量、must_include_beats 數量** 決定；\n"
        "  字數必須足以讓所列 beats 在正文中有空間展開，又不得明顯過長以免灌水。\n"
        "- 若大綱極簡卻字數極大、或節點極多卻字數極小，後續審核會退件，請自行避免。\n\n"
        "## 前情提要\n"
        f"- previous_chapter_summary: {_clip(payload.previous_chapter_summary, PLANNER_PREVIOUS_CHAPTER_SUMMARY_CAP)}\n"
        f"- recent_chapter_context: {_clip(payload.recent_chapter_context, PLANNER_RECENT_CHAPTER_CONTEXT_CAP)}\n"
        f"- last_known_location: {payload.last_known_location}\n"
        f"- continuity_notes: {_clip_note_lines(list(payload.continuity_notes))}\n"
        f"- recent_entities: {_clip_entity_names(list(payload.recent_entity_names))}\n\n"
        "## 本章劇情發展方向\n"
        f"- directive: {payload.narrative_directive}\n"
        f"- active_epoch: {payload.active_epoch_id}\n"
        f"- pov_character: {payload.pov_character_id}\n"
        f"- current_volume_title: {payload.current_volume_title}\n"
        f"- current_volume_summary: {_clip(payload.current_volume_summary, PLANNER_VOLUME_SUMMARY_CAP)}\n"
        f"- current_anchor_id: {payload.target_anchor_id}\n"
        f"- current_anchor_title: {payload.current_anchor_title}\n"
        f"- current_anchor_description: {payload.current_anchor_description}\n"
        "- upcoming_unachieved_anchors: 以下為「最近數個」未完成錨點（滑動視窗，含 id／title／chapter_target）；"
        "**以 current_anchor 為本章主目標**，其餘僅供節奏參考，勿替更遠錨點寫出具體橋段或結局。\n"
        f"- upcoming_unachieved_anchors: {upcoming_json}\n\n"
        "## 世界與檢索背景\n"
        f"- story_premise: {payload.story_premise}\n"
        f"- bible_context: {_clip(payload.bible_context, PLANNER_BIBLE_CONTEXT_CAP)}\n"
        f"- graph_context: {_clip(payload.graph_context, PLANNER_GRAPH_CONTEXT_CAP)}\n"
        f"- vector_context: {_clip(payload.vector_context, PLANNER_VECTOR_CONTEXT_CAP)}\n\n"
        "## 上一版規劃（供修正參考）\n"
        f"- previous_attempt_ground_truth_events: {prev_events}\n"
        f"- previous_attempt_narrative_script: {_clip(payload.previous_attempt_narrative_script, PLANNER_PREVIOUS_NARRATIVE_CAP)}\n\n"
        "## 前次規劃回饋\n"
        f"- prior_feedback: {prior_fb}\n\n"
        "## 導演指令（本章類型與創世）\n"
        f"- chapter_type: {payload.chapter_type}\n"
        f"- b_story_directive: {payload.b_story_directive or ''}\n"
        f"- new_elements_to_introduce: {payload.new_elements_to_introduce}\n"
        f"- distance_to_anchor: {payload.distance_to_anchor}\n"
        f"- active_b_stories: {json.dumps(payload.active_b_stories, ensure_ascii=False)[:800]}\n"
        "- 若有 b_story_directive，必須編入 narrative_script；must_include_beats 至少一條為與主線解謎無關的生活或感官細節。\n"
        "- 對 new_elements_to_introduce 每一項，在 proposed_new_nodes 輸出對應條目（node_id、node_type、role、canonical_name），"
        "最多 3 條，並在 ground_truth_events 安排與其互動。\n"
        "- new_active_b_stories：若本章**新開一條**獨立副線（需穩定 id），最多 2 條，每條含 id 與 desc；"
        "若無則輸出空陣列。成功定稿後系統會併入 bible；不要與既有 active_b_stories id 重複。\n\n"
        "## 你的輸出要求\n"
        "- 若上方已提供 previous_attempt_ground_truth_events 或 previous_attempt_narrative_script，代表這次是修稿，不是從零重做。\n"
        "- 若上一版只有局部違規，優先保留已經合理的事件鏈與章節方向，只修正被 feedback 指出的段落、事件或位置欄位。\n"
        "- 不要因為單一退件點就把整章主軸完全換掉；除非上一版已經整體失效，否則應維持同一章的核心任務與因果方向。\n"
        "- 這一章必須帶來新的因果推進，不能只是重述上一章。\n"
        "- 不得把上一章已完成的交易、發現、對話或衝突，重新包裝成本章的新事件。\n"
        "- ground_truth_events 每一條都必須代表本章新增的狀態變化，而不是前情摘要重寫。\n"
        "- narrative_script 必須清楚區分：哪些是承接上一章，哪些是本章新增的行動、發現、衝突與章末變化。\n"
        "- 你必須輸出 chapter_start_location；若沒有明確切景，應默認延續 last_known_location。\n"
        "- 若 chapter_start_location 與 last_known_location 不同，ground_truth_events 與 narrative_script 必須先規劃移動、撤離、趕路、換場或其他可抽取的過渡。\n"
        "- 你還要額外產出一份給 author 使用的安全任務卡，但不能洩漏底層真相。\n"
        "- author_goal: 用 1-2 句說明本章主筆作者真正要完成的戲劇任務。\n"
        "- must_include_beats: 列出 3-5 個本章必須寫到的表層情節節點，必須具體、可觀察、可落筆。\n"
        "- reader_visible_facts: 列出本章結束後讀者應該已經明確認知的事實，這些事實必須能從正文直接觀察到，不能混入秘密行動。\n"
        "- reader_unresolved_questions: 列出本章結束後仍應保留的懸念或未知，利用資訊差製造張力，但不要透露真相答案。\n"
        "- private_facts_or_secret_actions: 列出本章真實存在但不屬於大眾常識的秘密行動、私下發現、暗中監視或內部謀劃。這些內容提供給 extractor 判斷 is_public=false，不會直接給 author。\n"
        "- ending_state_shift: 用 1 句說明章末相較章初必須發生的狀態變化。\n"
        "- chapter_start_location: 用 1 句指出本章開場時 POV 或主要角色所在位置；若延續上一場景，就直接寫上一章章末位置。\n"
        "- chapter_end_location_hint: 用 1 句指出章末 POV 或主要角色有效停留的位置；若本章沒有明確移動，也要說明仍停留在哪裡。\n"
        "- ending_boundary_rule: 用 1-2 句寫出本章最遠只能停在哪個邊界，哪些後續行動必須保留到下一章。\n"
        "- forbidden_next_scene_actions: 列出 2-4 條本章不可跨過的後續動作，例如進屋、會面、切到下一地點、提前揭曉等。\n"
        "- forbidden_reveals: 列出 2-4 條 author 不可提前揭露、也不可擅自新增的內容；不可包含真相答案本身，只能描述邊界。\n"
        "- 這份 author 任務卡只能包含表層可寫資訊，不能直接暴露 ground_truth_events 中尚未被角色或讀者觀察到的真相。\n"
        "- 若本章存在移動，must_include_beats、reader_visible_facts、chapter_start_location、chapter_end_location_hint 與 ending_boundary_rule 之間必須彼此一致。\n"
        "- author_safe_continuity_notes: 輸出 0-4 條短句，供主筆 author 作「連續性提醒」專用。\n"
        "  * 上方 continuity_notes 可能含 RAG／抽取產生的「未解線索」，常含讀者或 POV 尚未正當得知的專名與後續劇情，**不可原句貼給 author**。\n"
        "  * 你必須依 pov_character、previous_chapter_summary、recent_chapter_context、ground_truth_events 與 reader_visible_facts 的邊界，"
        "改寫成角色當下可感知、可延續的表層懸念；無安全內容時輸出空陣列 []。\n"
        "  * 可匿名化（例如「是否有外部勢力在追蹤？」）或延後到 reader_unresolved_questions 處理，但不要在此欄引入本章尚未核准的新專名。\n"
    )
