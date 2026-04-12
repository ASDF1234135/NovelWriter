from __future__ import annotations

import re

from app.core.config import get_settings
from app.services.llm import MockLLMClient
from app.services.workflow.continuity import chapter_content_tail_snippet
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.author import _ensure_chapter_heading
from app.services.workflow.profiles import get_profile


def _completed_chapter_tail(
    story_repository,
    story_id: str,
    chapter_id: int,
    max_chars: int,
) -> str:
    row = story_repository.get_chapter(story_id, chapter_id)
    if not row:
        return ""
    if (str(row.get("status") or "").strip().lower()) != "completed":
        return ""
    raw = str(row.get("content") or "")
    return chapter_content_tail_snippet(raw, max_chars=max_chars) if raw else ""


def _load_read_only_prev_tails(
    state: dict,
    context: WorkflowContext,
    *,
    n1_max: int,
    n2_max: int,
) -> tuple[str, str]:
    story_id = state["story_id"]
    cid = int(state["chapter_id"])
    repo = context.story_repository
    tail_m2 = _completed_chapter_tail(repo, story_id, cid - 2, n2_max) if cid > 2 else ""
    tail_m1 = _completed_chapter_tail(repo, story_id, cid - 1, n1_max) if cid > 1 else ""
    return tail_m2, tail_m1


def _strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _collapse_leading_noise(text: str) -> str:
    """Drop common LLM preamble lines before the chapter heading."""
    t = text.strip()
    for _ in range(4):
        lowered = t[:80].lower()
        if lowered.startswith("好的") or lowered.startswith("以下是") or lowered.startswith("這是"):
            lines = t.splitlines()
            t = "\n".join(lines[1:]).strip() if len(lines) > 1 else t
            continue
        break
    return t


def _strip_stray_markdown(text: str) -> str:
    # Light cleanup: paired ** and stray list markers at line starts are reduced in prose pass.
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    out = re.sub(r"(?m)^[\*\-]\s+", "", out)
    return out


def _identity_tokens_to_block(state: dict) -> list[str]:
    allowed = {
        str(x).strip().casefold()
        for x in (state.get("allowed_identity_reveals_this_chapter") or [])
        if str(x).strip()
    }
    blocked: set[str] = set()
    for row in (state.get("forbidden_reveals") or []):
        if not isinstance(row, str) or not row.strip():
            continue
        if not any(k in row for k in ("身分", "身份", "真名", "真相", "其實是", "真正是")):
            continue
        for token in re.findall(r"「([^」]{1,30})」", row):
            t = token.strip()
            if t and t.casefold() not in allowed:
                blocked.add(t)
    return sorted(blocked, key=len, reverse=True)


def _redact_identity_terms(text: str, blocked_terms: list[str]) -> str:
    out = text
    for term in blocked_terms:
        out = re.sub(re.escape(term), "[REDACTED_IDENTITY]", out, flags=re.IGNORECASE)
    return out


def _build_copyeditor_prompt(
    state: dict,
    *,
    tail_n2: str,
    tail_n1: str,
    chapter_draft: str,
) -> str:
    cid = int(state["chapter_id"])
    read_only_blocks: list[str] = []
    if cid > 2:
        read_only_blocks.append(
            f"## 唯讀：第 {cid - 2} 章結尾節錄（禁止改寫、禁止複製進輸出）\n"
            f"{tail_n2 if tail_n2 else '（無）'}"
        )
    if cid > 1:
        read_only_blocks.append(
            f"## 唯讀：第 {cid - 1} 章結尾節錄（禁止改寫、禁止複製進輸出）\n"
            f"{tail_n1 if tail_n1 else '（無）'}"
        )
    read_only_section = (
        "\n\n".join(read_only_blocks)
        if read_only_blocks
        else "## 唯讀參考\n（本章為第 1 章，尚無已完成之前章。）"
    )
    return f"""你是校閱編輯。只允許修飾語句、刪除冗餘與 Markdown、整理標點與轉折，不得改寫事實與劇情資訊。

{read_only_section}

## 可編輯：第 {cid} 章全文草稿（你只能產出此章潤飾後的全文）
{chapter_draft}

## 鐵律
1. 資訊守恆（最高）：不得刪除道具、關鍵對白、地點或事件；不得新增情節；不得把具體指稱改成晦澀隱喻以致與必出實體表面脫鉤。
2. 去重：若本章開頭與上章結尾在動作／感嘆上重複，刪本章冗餘句並無縫接續（不刪事件）。
3. 版面：移除多餘 Markdown（粗體星號、裝飾符）；避免套話式總結尾聲。
4. 除草任務（Jargon Pruning）：若草稿出現過於生硬、遊戲化、或做作引號式專有名詞（如「獵犬協同邏輯」「策略性緩衝節點」），請改寫成自然敘述。
5. 除草原則：不改變劇情事實與因果，只把名詞包裝拆成角色可觀察的動作、感官、空間變化或系統反應。
6. 必要命名可保留：若名稱屬核心辨識點且後文需要，可保留名稱；但請刪除裝飾性副標、過度引號與術語堆砌。
7. 參考改寫示例：
   - 原文：他看見了「虛空節點：坍塌區」。
   - 修改：他看見了這片空間最脆弱的縫隙，光束在那裡發生了不穩定的扭曲。
8. 輸出：只輸出第 {cid} 章潤飾後正文，禁止前言、禁止 JSON、禁止解釋。
"""


def run_copyeditor(state: dict, context: WorkflowContext) -> dict[str, object]:
    settings = get_settings()
    cid = int(state["chapter_id"])
    draft = (state.get("best_draft_content") or state.get("current_draft") or "").strip()
    if not draft:
        return {"current_draft": "", "best_draft_content": ""}

    tail_m2, tail_m1 = _load_read_only_prev_tails(
        state,
        context,
        n1_max=int(settings.copyeditor_prev_tail_n1_max_chars),
        n2_max=int(settings.copyeditor_prev_tail_n2_max_chars),
    )

    if isinstance(context.llm_client, MockLLMClient):
        polished = _ensure_chapter_heading(cid, draft)
        polished = _redact_identity_terms(polished, _identity_tokens_to_block(state))
        return {"current_draft": polished, "best_draft_content": polished}

    profile = get_profile("copyeditor")
    prompt = _build_copyeditor_prompt(state, tail_n2=tail_m2, tail_n1=tail_m1, chapter_draft=draft)
    result = context.llm_client.invoke_text(prompt, profile)
    body = _strip_markdown_fences(result.content)
    body = _collapse_leading_noise(body)
    body = _strip_stray_markdown(body)
    polished = _ensure_chapter_heading(cid, body)
    polished = _redact_identity_terms(polished, _identity_tokens_to_block(state))
    if not polished.strip():
        polished = _ensure_chapter_heading(cid, draft)
    return {"current_draft": polished, "best_draft_content": polished}
