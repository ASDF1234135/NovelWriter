from __future__ import annotations

from app.domain.schema import AuthorOutput
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_author_payload
from app.services.workflow.profiles import get_profile
from app.services.workflow.utils import normalized_text_length


def _format_author_safe_continuity(notes: list[str]) -> str:
    cleaned = [(line or "").strip() for line in notes if (line or "").strip()]
    if not cleaned:
        return "無"
    return "\n".join(f"- {line}" for line in cleaned)


def run_author(state: dict, context: WorkflowContext) -> tuple[dict, dict, int, int]:
    payload = build_author_payload(state)
    prompt = _build_author_prompt(payload)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = get_profile("author")
        llm_result = context.llm_client.invoke_text(prompt, profile)
        chapter_content = _ensure_chapter_heading(state["chapter_id"], llm_result.content)
        token_usage = llm_result.token_usage
        latency_ms = llm_result.latency_ms
        chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
            state["chapter_id"],
            payload,
            chapter_content,
            context,
            profile,
        )
        token_usage += repair_tokens
        latency_ms += repair_latency

        compression_round = 0
        while normalized_text_length(chapter_content) > payload.normalized_length_max and compression_round < 2:
            compression_round += 1
            over_length = normalized_text_length(chapter_content) - payload.normalized_length_max
            compression_prompt = _build_compression_prompt(payload, chapter_content, over_length)
            compression_result = context.llm_client.invoke_text(compression_prompt, profile)
            compressed_content = _ensure_chapter_heading(state["chapter_id"], compression_result.content)
            if compressed_content.strip() == chapter_content.strip():
                break
            chapter_content = compressed_content
            token_usage += compression_result.token_usage
            latency_ms += compression_result.latency_ms
            chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
                state["chapter_id"],
                payload,
                chapter_content,
                context,
                profile,
            )
            token_usage += repair_tokens
            latency_ms += repair_latency

        expansion_round = 0
        while normalized_text_length(chapter_content) < payload.normalized_length_min and expansion_round < 2:
            expansion_round += 1
            missing_length = payload.normalized_length_min - normalized_text_length(chapter_content)
            continuation_prompt = _build_expansion_prompt(payload, chapter_content, missing_length)
            continuation_result = context.llm_client.invoke_text(continuation_prompt, profile)
            continuation = _strip_chapter_heading(continuation_result.content)
            if not continuation:
                break
            chapter_content = f"{chapter_content.rstrip()}\n\n{continuation.strip()}"
            token_usage += continuation_result.token_usage
            latency_ms += continuation_result.latency_ms
            chapter_content, repair_tokens, repair_latency = _repair_boundary_if_needed(
                state["chapter_id"],
                payload,
                chapter_content,
                context,
                profile,
            )
            token_usage += repair_tokens
            latency_ms += repair_latency

        output = AuthorOutput(
            chapter_content=chapter_content,
            word_count=normalized_text_length(chapter_content),
        )
        return output.model_dump(mode="json"), payload.model_dump(mode="json"), token_usage, latency_ms

    llm_result = context.llm_client.invoke(prompt)
    base_paragraphs = [
        f"他清楚記得上一章留下的局勢：{payload.previous_chapter_summary}" if payload.previous_chapter_summary else "",
        f"上一章結束時，他最後確定的位置是：{payload.last_known_location}" if payload.last_known_location else "",
        f"這一章開場時，他人就在：{payload.chapter_start_location}" if payload.chapter_start_location else "",
        f"這一章的主筆任務是：{payload.author_goal}" if payload.author_goal else "",
        f"這一章必須完成：{'、'.join(payload.must_include_beats)}" if payload.must_include_beats else "",
        f"本章必須延續的線索包括：{'、'.join(payload.author_safe_continuity_notes)}"
        if payload.author_safe_continuity_notes
        else "",
        f"此刻牽動局勢的關鍵實體有：{'、'.join(payload.recent_entity_names)}" if payload.recent_entity_names else "",
        f"讀者在本章應該明確認知：{'、'.join(payload.reader_visible_facts)}" if payload.reader_visible_facts else "",
        f"但本章仍需保留未知：{'、'.join(payload.reader_unresolved_questions)}" if payload.reader_unresolved_questions else "",
        f"章末位置必須收束到：{payload.chapter_end_location_hint}" if payload.chapter_end_location_hint else "",
        "他知道今晚只能先停在預定的安全邊界，不能再多走一步。" if payload.ending_boundary_rule else "",
        "有些事現在還不能做，否則就會太早踏進下一段局勢。" if payload.forbidden_next_scene_actions else "",
        "街上很安靜，主角沒有時間發呆。他知道自己再慢一步，線索就會斷掉。",
        "他先看眼前能做的事，再決定下一步，不讓情緒把行動拖住。",
        "現場每一句話、每一個表情、每一次停頓，都可能把他推向新的麻煩。",
        f"{payload.narrative_script}",
        "他沒有把事情想得太遠，只先抓住手上已經出現的變化。",
        f"到章末時，局勢應該已經變了：{payload.ending_state_shift}" if payload.ending_state_shift else "到章末時，他已經被推進下一步，風險也比一開始更高。",
        "他知道這一章不能停在原地，所以最後一定要把人和局勢推到新的位置。",
    ]
    chapter_content = f"第{state['chapter_id']}章\n\n"
    while normalized_text_length(chapter_content) < payload.normalized_length_min:
        chapter_content += "\n\n" + "\n".join(paragraph for paragraph in base_paragraphs if paragraph)
    output = AuthorOutput(
        chapter_content=chapter_content,
        word_count=normalized_text_length(chapter_content),
    )
    return output.model_dump(mode="json"), payload.model_dump(mode="json"), llm_result.token_usage, llm_result.latency_ms


def _build_author_prompt(payload) -> str:
    draft_feedback_text = _format_feedback_entries(payload.draft_feedback, "draft")
    reader_feedback_text = _format_feedback_entries(payload.reader_feedback, "reader")
    previous_attempt_draft = _truncate_previous_attempt_draft(payload.previous_attempt_draft)
    return f"""
你是本章主筆作者。請只根據以下表層劇本寫作，不得猜測額外真相。
請直接輸出小說正文，不要輸出 JSON、標題解釋、欄位名稱或額外註解。

## 寫作目標
節奏與情緒：{payload.tone_direction}
目標字數參考：{payload.target_word_count}
實際審核字數下限：正規化後至少 {payload.normalized_length_min}
實際審核允許範圍：{payload.normalized_length_min} - {payload.normalized_length_max}

## 字數修訂模式
本次長度指令：{payload.length_adjustment}
當 `length_adjustment=EXPAND` 時，代表上一版太短，請補入新的有效行動、對話、反應或推進。
當 `length_adjustment=COMPRESS` 時，代表上一版太長，請保留核心事件與節點，但刪去重複等待、重複心理描寫與無效環境鋪陳。
當 `length_adjustment=NONE` 時，照正常章節寫作，但仍須落在允許範圍內。

主筆任務：
{payload.author_goal}

## 前情提要
上一章摘要：
{payload.previous_chapter_summary}

上一章已知位置：
{payload.last_known_location}

本章開場位置：
{payload.chapter_start_location}

連續性提醒（已由編劇 POV 過濾，僅含可安全交給主筆的句子；若無則表示本輪不額外提示）：
{_format_author_safe_continuity(payload.author_safe_continuity_notes)}

近期重要實體：
{payload.recent_entity_names}

## 本章劇情發展方向
表層劇本：
{payload.narrative_script}

## 本章必做內容
必出節點：
{payload.must_include_beats}

章末狀態變化：
{payload.ending_state_shift}

章末有效位置：
{payload.chapter_end_location_hint}

## 本章硬邊界
本章最遠只能寫到：
{payload.ending_boundary_rule}

本章禁止提前發生：
{payload.forbidden_next_scene_actions}

## 讀者資訊差
本章結束後讀者應知道：
{payload.reader_visible_facts}

本章結束後讀者仍不知道：
{payload.reader_unresolved_questions}

## 禁止提前揭露
{payload.forbidden_reveals}

## 上一版草稿（供修稿參考）
{previous_attempt_draft}

## 修稿優先順序
1. 第一優先：嚴格完成本章主任務，包含 `author_goal`、`must_include_beats`、`ending_state_shift`、`chapter_end_location_hint`、`ending_boundary_rule`。
2. 第二優先：修正 `draft_feedback` 指出的硬問題，例如事件鏈缺失、位置不一致、結尾越界、POV 洩漏或違反硬邊界。
3. 第三優先：只有在前兩者都已滿足時，才參考 `reader_feedback` 做文句、節奏、重複詞、情緒張力等文學層微調。
4. 若 `reader_feedback` 與本章主任務或 `draft_feedback` 衝突，必須忽略 `reader_feedback`，保留既定事件鏈與章節目標。

## 歷史退稿回饋
編輯部邏輯建議：
{draft_feedback_text}

## 讀者回饋
讀者回饋：
{reader_feedback_text}

請注意：讀者回饋只代表文學優化建議，不得推翻既定事件鏈、必出節點、章末位置與本章硬邊界。

## 你的寫作要求
1. 若上方提供了「上一版草稿」，代表這次是修稿，不是從零重寫；優先保留已經成立且未被 feedback 指出的內容。
2. 你必須先完成本章主任務與所有「本章必做內容」，再考慮文學潤飾；不可為了回應讀者建議而刪除關鍵事件。
3. 本章必須出現新的行動、新的發現、新的衝突，至少推進一個明確事件。
4. 章末狀態必須與章初不同，並符合指定的章末狀態變化。
5. 若上一版草稿已經完成某些必出節點，且沒有被 `draft_feedback` 指出有問題，請沿用並局部修正，不要任意改成另一組事件。
6. `draft_feedback` 屬於硬修正指令；`reader_feedback` 只屬於軟性優化建議，不得凌駕於劇情任務與硬邊界之上。
7. 你可以利用讀者知道與不知道的資訊差製造懸念，但不得直接揭露禁止提前揭露的內容。
8. 若本章涉及移動，必須清楚寫出角色離開了哪裡、抵達了哪裡，或章末停留在哪裡，讓位置可被抽取。
9. 不得自行補完底層真相，也不得擅自新增與本章任務無關的新機關、新謎團或新世界規則。
10. 語言要自然白話，句子偏短，優先寫具體動作、對話與可觀察細節。
11. 少用比喻、排比、連續形容詞，不要每段都先鋪氣氛再進劇情。
12. 字數審核看的是正規化後字數，不計空白與大多數標點；若 `length_adjustment=EXPAND` 或內容偏短，請直接補足新的有效情節與對話，不要灌水重述。
13. `chapter_end_location_hint` 與「本章硬邊界」是硬限制，不是參考建議；正文最遠只能停在那裡。
14. 只要碰到「本章禁止提前發生」中的任一動作，就代表你已經寫到下一章，必須停下並改寫結尾。
15. 若 feedback 指的是局部問題，例如結尾越界、位置不一致、缺少某個 beat，請只修正相關段落，不要把整章前半全部推翻重寫。
16. 若 `length_adjustment=COMPRESS` 或內容偏長，優先刪除重複檢查、重複等待、連續空轉心理描寫與重複氛圍句，但不得刪掉 `must_include_beats`、`ending_state_shift` 與章末位置。
""".strip()


def _format_feedback_entries(entries: list[dict], source: str) -> str:
    if not entries:
        return "無"
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        attempt = entry.get("attempt", index)
        violation = entry.get("violation", [])
        suggestion = entry.get("suggestion", "")
        message = entry.get("message", "")
        if source == "draft":
            lines.append(
                f"- 第 {attempt} 次退稿 | violation={violation} | suggestion={suggestion} | message={message}"
            )
        else:
            lines.append(
                f"- 第 {attempt} 次讀者評審 | score={entry.get('score', '')} | suggestion={entry.get('suggestion', '')} | message={message}"
            )
    return "\n".join(lines)


def _truncate_previous_attempt_draft(text: str, max_chars: int = 7000) -> str:
    if not text:
        return "無"
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[上一版草稿過長，僅提供前 {max_chars} 字作為修稿參考]"


def _build_expansion_prompt(payload, chapter_content: str, missing_length: int) -> str:
    return f"""
你要續寫同一章正文，不能重寫開頭，也不能摘要前文。
目前正文的正規化字數仍不足，還差至少 {missing_length}。
請直接承接最後一段往下寫，用新的有效情節、對話、動作與反應補足，不要灌水，不要重複已經寫過的資訊。
語言維持自然白話、句子偏短、少用比喻。
你不能跨過本章硬邊界；若必出節點已完成，請只在同一場景內補足反應、餘韻或短對話，不可開啟下一場景。
章末有效位置：{payload.chapter_end_location_hint}
本章硬邊界：{payload.ending_boundary_rule}
禁止提前發生：{payload.forbidden_next_scene_actions}
若尚未完成以下節點，優先補上：
{payload.must_include_beats}

目前正文：
{chapter_content}
""".strip()


def _build_compression_prompt(payload, chapter_content: str, excess_length: int) -> str:
    return f"""
你要壓縮同一章正文，不能改成摘要，也不能刪掉核心事件。
目前正文的正規化字數超出上限，至少要再縮短 {excess_length}。
請保留既有事件順序、must_include_beats、章末狀態與章末位置，但刪去重複等待、重複巡視、重複心理獨白、重複環境描寫與無效句。
語言維持自然白話、句子偏短，直接重寫成更緊湊的同章正文。
章末有效位置：{payload.chapter_end_location_hint}
本章硬邊界：{payload.ending_boundary_rule}
禁止提前發生：{payload.forbidden_next_scene_actions}
必須保留的節點：
{payload.must_include_beats}

目前正文：
{chapter_content}
""".strip()


def _repair_boundary_if_needed(chapter_id: int, payload, chapter_content: str, context: WorkflowContext, profile) -> tuple[str, int, int]:
    violations = _detect_boundary_violations(chapter_content, payload)
    if not violations:
        return chapter_content, 0, 0

    repair_prompt = _build_boundary_repair_prompt(payload, chapter_content, violations)
    repair_result = context.llm_client.invoke_text(repair_prompt, profile)
    repaired_content = _ensure_chapter_heading(chapter_id, repair_result.content)
    return repaired_content, repair_result.token_usage, repair_result.latency_ms


def _detect_boundary_violations(chapter_content: str, payload) -> list[str]:
    violations: list[str] = []
    lowered_content = chapter_content.casefold()
    for action in payload.forbidden_next_scene_actions:
        for cue in _extract_boundary_cues(action):
            if cue.casefold() in lowered_content:
                violations.append(action)
                break

    boundary_feedback = _format_feedback_entries(payload.draft_feedback, "draft")
    boundary_keywords = ("超出", "結尾", "章末", "安全屋", "下一章", "停留在", "截斷", "巷弄", "外圍")
    if any(keyword in boundary_feedback for keyword in boundary_keywords):
        violations.extend(message.get("message", "") for message in payload.draft_feedback if any(keyword in message.get("message", "") for keyword in boundary_keywords))

    deduped: list[str] = []
    for violation in violations:
        if violation and violation not in deduped:
            deduped.append(violation)
    return deduped


def _build_boundary_repair_prompt(payload, chapter_content: str, violations: list[str]) -> str:
    return f"""
你要修正同一章正文的結尾，原因是它已超出本章邊界。
請保留前面已經成立且不違規的內容，但重寫最後一段到最後數段，讓本章停在正確終點。
你必須滿足以下硬限制：
- 章末有效位置：{payload.chapter_end_location_hint}
- 本章硬邊界：{payload.ending_boundary_rule}
- 禁止提前發生：{payload.forbidden_next_scene_actions}

這次偵測到的越界內容：
{violations}

請特別注意：
1. 不可進入下一個完整場景、房間、據點或任務節點。
2. 不可解除原本要保留到下一章的懸念。
3. 可以保留撤離後的餘韻，但角色最遠只能停在本章指定的外圍或章末位置。
4. 直接輸出修正版正文，不要加說明。

目前正文：
{chapter_content}
""".strip()


def _extract_boundary_cues(action: str) -> list[str]:
    raw_parts = [part.strip() for part in action.replace("，", " ").replace("、", " ").replace("。", " ").split() if part.strip()]
    cues: list[str] = []
    for part in raw_parts:
        normalized = part
        for prefix in ("不要", "不可", "不得", "避免", "本章", "提前"):
            normalized = normalized.removeprefix(prefix)
        normalized = normalized.strip()
        if len(normalized) >= 3:
            cues.append(normalized)
    return cues


def _ensure_chapter_heading(chapter_id: int, content: str) -> str:
    stripped = content.strip()
    if stripped.startswith(f"第{chapter_id}章"):
        return stripped
    return f"第{chapter_id}章\n\n{stripped}"


def _strip_chapter_heading(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("第"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    if len(lines[0]) <= 12 and "章" in lines[0]:
        return "\n".join(lines[1:]).strip()
    return stripped
