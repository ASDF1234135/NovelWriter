from app.domain.state import SafeAuthorPayload
from app.services.llm import LLMResult
from app.services.workflow.nodes.author import _build_author_prompt, _format_feedback_entries, run_author
from app.services.workflow.profiles import AgentPromptProfile


class FakeTextLLMClient:
    def invoke(self, prompt: str) -> LLMResult:
        raise NotImplementedError

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        return LLMResult(
            content="夜色沉下，主角在王都石街盡頭收下召喚令，終於明白自己必須離開。",
            token_usage=123,
            latency_ms=456,
        )

    def invoke_json(self, prompt, response_model, profile):
        raise NotImplementedError


class DummyContext:
    def __init__(self) -> None:
        self.llm_client = FakeTextLLMClient()


class SequenceTextLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    def invoke(self, prompt: str) -> LLMResult:
        raise NotImplementedError

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return LLMResult(content=response, token_usage=50, latency_ms=60)

    def invoke_json(self, prompt, response_model, profile):
        raise NotImplementedError


class SequenceContext:
    def __init__(self, responses: list[str]) -> None:
        self.llm_client = SequenceTextLLMClient(responses)


def test_author_uses_text_generation_for_real_llm() -> None:
    state = {
        "chapter_id": 1,
        "narrative_script": "主角在日常穩定表象中發現異常，章末被迫離城。",
        "chapter_start_location": "王都石街。",
        "author_goal": "讓主角在本章完成離城前的關鍵決定。",
        "must_include_beats": ["發現異常", "做出離城決定"],
        "reader_visible_facts": ["主角已無法留在原地"],
        "reader_unresolved_questions": ["誰在幕後施壓"],
        "chapter_end_location_hint": "王都西門外驛道。",
        "ending_state_shift": "主角從被動觀察轉為主動出發。",
        "ending_boundary_rule": "本章最遠只能停在王都西門外驛道，不能進入下一個據點。",
        "forbidden_next_scene_actions": ["不可進入驛站內部", "不可直接前往下一個據點"],
        "forbidden_reveals": ["不要直接揭露幕後黑手"],
        "tone_direction": "懸疑",
        "target_word_count": 1800,
        "previous_chapter_summary": "上一章主角在石街察覺異常。",
        "current_draft": "第1章\n\n主角先在石街盡頭停下，還沒做出最後決定。",
        "last_known_location": "王都石街。",
        "draft_feedback": [],
        "reader_feedback": [],
    }

    output, masked, tokens, latency = run_author(state, DummyContext())

    assert output["chapter_content"].startswith("第1章")
    assert output["word_count"] > 0
    assert masked == SafeAuthorPayload(
        narrative_script=state["narrative_script"],
        chapter_start_location=state["chapter_start_location"],
        author_goal=state["author_goal"],
        must_include_beats=state["must_include_beats"],
        reader_visible_facts=state["reader_visible_facts"],
        reader_unresolved_questions=state["reader_unresolved_questions"],
        chapter_end_location_hint=state["chapter_end_location_hint"],
        ending_state_shift=state["ending_state_shift"],
        ending_boundary_rule=state["ending_boundary_rule"],
        forbidden_next_scene_actions=state["forbidden_next_scene_actions"],
        forbidden_reveals=state["forbidden_reveals"],
        tone_direction=state["tone_direction"],
        target_word_count=state["target_word_count"],
        normalized_length_min=1170,
        normalized_length_max=2430,
        previous_chapter_summary=state["previous_chapter_summary"],
        previous_attempt_draft=state["current_draft"],
        last_known_location=state["last_known_location"],
        draft_feedback=[],
        reader_feedback=[],
        length_adjustment="NONE",
    ).model_dump(mode="json")
    assert tokens >= 123
    assert latency >= 456


def test_author_repairs_boundary_violation_before_returning() -> None:
    state = {
        "chapter_id": 1,
        "narrative_script": "主角撤離後停在安全屋外圍，不可進屋。",
        "chapter_start_location": "舊御花園後巷。",
        "author_goal": "讓主角完成撤離，並把懸念留到下一章。",
        "must_include_beats": ["撤離到安全屋外圍"],
        "reader_visible_facts": ["主角暫時脫離追兵"],
        "reader_unresolved_questions": ["安全屋內是誰在等他"],
        "chapter_end_location_hint": "安全屋外圍巷口陰影處。",
        "ending_state_shift": "主角成功撤離，但尚未真正安全。",
        "ending_boundary_rule": "本章最遠只能停在安全屋外圍巷口陰影處，不可進入安全屋內部。",
        "forbidden_next_scene_actions": ["不可進入安全屋內部"],
        "forbidden_reveals": ["不要揭露安全屋內部安排"],
        "tone_direction": "懸疑",
        "target_word_count": 200,
        "previous_chapter_summary": "主角在後巷甩開追兵。",
        "current_draft": "",
        "last_known_location": "舊御花園後巷。",
        "draft_feedback": [],
        "reader_feedback": [],
    }
    context = SequenceContext(
        [
            "第1章\n\n他終於抵達安全屋外圍，接著推門進入安全屋內部，準備和屋內的人會面。",
            "第1章\n\n他終於抵達安全屋外圍，停在巷口陰影處，沒有再往裡走，只聽見門後傳來極輕的腳步聲。",
        ]
    )

    output, _, _, _ = run_author(state, context)

    assert "安全屋內部" not in output["chapter_content"]
    assert "巷口陰影處" in output["chapter_content"]


def test_author_formats_feedback_as_independent_entries() -> None:
    rendered = _format_feedback_entries(
        [
            {"attempt": 1, "violation": ["INCONSISTENCY"], "suggestion": "MODIFY", "message": "第一版問題"},
            {"attempt": 2, "violation": ["WORD_COUNT_UNMATCH"], "suggestion": "REWRITE", "message": "第二版問題"},
        ],
        "draft",
    )

    assert "第 1 次退稿" in rendered
    assert "第一版問題" in rendered
    assert "第 2 次退稿" in rendered
    assert "第二版問題" in rendered


def test_author_prompt_includes_previous_attempt_draft_for_revision() -> None:
    prompt = _build_author_prompt(
        SafeAuthorPayload(
            narrative_script="主角在石橋邊確認追兵是否逼近。",
            chapter_start_location="石橋南端。",
            author_goal="讓主角確認風險並決定撤離。",
            must_include_beats=["確認追兵位置", "做出撤離決定"],
            reader_visible_facts=["追兵尚未放棄"],
            reader_unresolved_questions=["橋對岸是誰在等他"],
            chapter_end_location_hint="石橋北端霧區外圍。",
            ending_state_shift="主角從觀望轉為撤離。",
            ending_boundary_rule="本章最遠只能停在石橋北端霧區外圍，不可進入霧區深處。",
            forbidden_next_scene_actions=["不可進入霧區深處"],
            forbidden_reveals=["不要揭露霧區中的真相"],
            tone_direction="懸疑",
            target_word_count=1800,
            normalized_length_min=1170,
            normalized_length_max=2430,
            previous_chapter_summary="上一章主角被迫離開城門。",
            previous_attempt_draft="第1章\n\n主角原本停在石橋北端，卻又直接走進霧區深處。",
            last_known_location="石橋南端。",
            author_safe_continuity_notes=["霧區內仍有未知接應者。"],
            recent_entity_names=["Kaelen"],
            draft_feedback=[{"attempt": 1, "violation": ["INCONSISTENCY"], "suggestion": "REWRITE", "message": "結尾越界"}],
            reader_feedback=[],
            length_adjustment="COMPRESS",
        )
    )

    assert "## 上一版草稿（供修稿參考）" in prompt
    assert "主角原本停在石橋北端，卻又直接走進霧區深處。" in prompt
    assert "這次是修稿，不是從零重寫" in prompt
    assert "請只修正相關段落，不要把整章前半全部推翻重寫" in prompt
    assert "## 修稿優先順序" in prompt
    assert "## 字數修訂模式" in prompt
    assert "COMPRESS" in prompt
    assert "第一優先：嚴格完成本章主任務" in prompt
    assert "`reader_feedback` 只屬於軟性優化建議" in prompt
    assert "不得推翻既定事件鏈" in prompt


def test_author_compresses_when_draft_is_too_long() -> None:
    state = {
        "chapter_id": 1,
        "narrative_script": "主角完成接頭，帶著證據撤離到碼頭暗影。",
        "chapter_start_location": "舊碼頭外圍。",
        "author_goal": "讓主角完成接頭並帶走證據。",
        "must_include_beats": ["完成接頭", "帶走證據", "撤離到碼頭暗影"],
        "reader_visible_facts": ["證據已到手"],
        "reader_unresolved_questions": ["接頭人是否可信"],
        "chapter_end_location_hint": "碼頭暗影處。",
        "ending_state_shift": "主角拿到證據並成功撤離。",
        "ending_boundary_rule": "本章最遠只能停在碼頭暗影處。",
        "forbidden_next_scene_actions": ["不可登船離港"],
        "forbidden_reveals": [],
        "tone_direction": "緊張",
        "target_word_count": 100,
        "previous_chapter_summary": "上一章主角抵達舊碼頭。",
        "current_draft": "第1章\n\n舊版草稿",
        "last_known_location": "舊碼頭外圍。",
        "draft_feedback": [{"attempt": 1, "violation": ["WORD_COUNT_UNMATCH"], "suggestion": "MODIFY", "length_adjustment": "COMPRESS", "message": "太長"}],
        "reader_feedback": [],
        "length_adjustment": "COMPRESS",
    }
    repeated = "他先等了一會兒，又再等了一會兒，反覆確認四周沒有動靜。"
    long_body = "\n\n".join([repeated for _ in range(8)])
    context = SequenceContext(
        [
            f"第1章\n\n{long_body}",
            "第1章\n\n他完成接頭，拿到證據，隨即退到碼頭暗影處，沒有再往前走。",
        ]
    )

    output, _, _, _ = run_author(state, context)

    assert output["word_count"] <= 135
    assert "碼頭暗影處" in output["chapter_content"]
