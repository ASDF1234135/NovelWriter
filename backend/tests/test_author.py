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
        self.output_language = "zh-Hant"


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
        self.output_language = "zh-Hant"


class HintRetryLLMClient:
    def __init__(self, chapter: str, hint_payloads: list[dict]) -> None:
        self.chapter = chapter
        self.hint_payloads = list(hint_payloads)
        self.json_calls = 0

    def invoke(self, prompt: str) -> LLMResult:
        raise NotImplementedError

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        return LLMResult(content=self.chapter, token_usage=10, latency_ms=10)

    def invoke_json(self, prompt, response_model, profile):
        idx = min(self.json_calls, len(self.hint_payloads) - 1)
        self.json_calls += 1
        data = self.hint_payloads[idx] if self.hint_payloads else {"entries": []}
        return response_model.model_validate(data), LLMResult(content="{}", token_usage=5, latency_ms=5)


class HintRetryContext:
    def __init__(self, chapter: str, hint_payloads: list[dict]) -> None:
        self.llm_client = HintRetryLLMClient(chapter, hint_payloads)
        self.output_language = "zh-Hant"


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


def test_author_formats_feedback_as_independent_entries() -> None:
    rendered = _format_feedback_entries(
        [
            {"attempt": 1, "violation": ["INCONSISTENCY"], "suggestion": "MODIFY", "message": "第一版問題"},
            {"attempt": 2, "violation": ["WORD_COUNT_UNMATCH"], "suggestion": "REWRITE", "message": "第二版問題"},
        ],
        "draft",
    )

    assert "rejection attempt 1" in rendered
    assert "第一版問題" in rendered
    assert "rejection attempt 2" in rendered
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

    assert "## Prior draft (for revision passes)" in prompt
    assert "主角原本停在石橋北端，卻又直接走進霧區深處。" in prompt
    assert "If a prior draft exists, revise" in prompt
    assert "patch the affected spans only" in prompt
    assert "## Revision priority" in prompt
    assert "## Length adjustment mode" in prompt
    assert "COMPRESS" in prompt
    assert "1) Satisfy author_goal" in prompt
    assert "draft_feedback is hard; reader_feedback is soft" in prompt
    assert "cannot override the locked event chain" in prompt


def test_author_prompt_includes_previous_chapter_tail_excerpt() -> None:
    prompt = _build_author_prompt(
        SafeAuthorPayload(
            narrative_script="主角在雨夜尋找線索，仍不確定是否安全。",
            chapter_start_location="城南巷口。",
            author_goal="讓主角找到下一步行動的落點。",
            must_include_beats=["確認巷口是否有人監視"],
            reader_visible_facts=["巷口有行人路過"],
            reader_unresolved_questions=["監視者是否在附近"],
            chapter_end_location_hint="城南巷尾陰影處。",
            ending_state_shift="主角確認監視仍未撤離。",
            ending_boundary_rule="本章最遠只能停在城南巷尾陰影處，不可進入下一據點。",
            forbidden_next_scene_actions=["不可直接進入下一據點"],
            forbidden_reveals=["不要揭露監視者的真名"],
            tone_direction="懸疑",
            target_word_count=1800,
            normalized_length_min=1170,
            normalized_length_max=2430,
            previous_chapter_summary="上一章主角被迫躲進暗巷。",
            previous_chapter_tail_excerpt="上一章結尾：他屏住呼吸，手指還停在門縫邊。",
            previous_attempt_draft="第1章\n\n上一版草稿內容。",
            last_known_location="暗巷內側。",
            author_safe_continuity_notes=["他還不知道誰在追查他。"],
            recent_entity_names=["灰鴉"],
            draft_feedback=[],
            reader_feedback=[],
            length_adjustment="NONE",
        )
    )
    assert "Previous chapter tail excerpt" in prompt
    assert "do not paste verbatim" in prompt
    assert "Hard bridge from prior chapter prose" in prompt
    assert "屏住呼吸，手指還停在門縫邊" in prompt


def test_author_prompt_includes_writing_note_block() -> None:
    prompt = _build_author_prompt(
        SafeAuthorPayload(
            narrative_script="主角在雨夜中保持移動，避免停留。",
            chapter_start_location="城南巷口。",
            author_goal="讓主角維持壓力下的行動節奏。",
            must_include_beats=["持續移動"],
            reader_visible_facts=["主角仍在逃離中"],
            reader_unresolved_questions=["追兵是否已包抄"],
            chapter_end_location_hint="轉運站外側。",
            ending_state_shift="主角把被動防守改為主動突圍。",
            ending_boundary_rule="本章最遠停在轉運站外側，不可進入站內。",
            forbidden_next_scene_actions=["不可進入站內"],
            forbidden_reveals=["不要揭露最終追兵身份"],
            tone_direction="懸疑",
            target_word_count=1800,
            normalized_length_min=1170,
            normalized_length_max=2430,
            previous_chapter_summary="上一章主角甩開了第一波追兵。",
            previous_attempt_draft="第1章\n\n上一版草稿內容。",
            last_known_location="城南巷口。",
            author_safe_continuity_notes=[],
            recent_entity_names=[],
            draft_feedback=[],
            reader_feedback=[],
            writing_note=["短句優先", "避免過度抒情"],
            safe_chapter_rules="遊戲規則：每回合只能行動一次；不可瞬間破局。",
            length_adjustment="NONE",
        )
    )
    assert "## Author writing_note (hard)" in prompt
    assert "## Absolute chapter laws" in prompt
    assert "每回合只能行動一次" in prompt
    assert "短句優先" in prompt
    assert "避免過度抒情" in prompt
    assert "## Naming discipline" in prompt
    assert "Name only when needed" in prompt
    assert "Describe before you label" in prompt


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


def test_author_retries_hints_for_missing_mandatory_entities() -> None:
    state = {
        "chapter_id": 1,
        "narrative_script": "主角啟用 memory dampener 並撤離。",
        "chapter_start_location": "觀測站",
        "author_goal": "提及必要道具",
        "must_include_beats": ["提到 memory dampener"],
        "reader_visible_facts": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "觀測站外",
        "ending_state_shift": "主角掌握新道具",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": [],
        "tone_direction": "緊張",
        "target_word_count": 80,
        "previous_chapter_summary": "",
        "current_draft": "",
        "last_known_location": "觀測站",
        "draft_feedback": [],
        "reader_feedback": [],
        "planned_graph_nodes": [
            {
                "node_id": "item_memory_dampener",
                "node_type": "ITEM",
                "mandatory": True,
                "role": "ITEM",
                "canonical_name": "memory dampener",
                "writing_brief": "記憶阻尼器",
            }
        ],
    }
    chapter = "第1章\n\n他握緊 memory dampener，確認干擾場已經展開。"
    context = HintRetryContext(
        chapter=chapter,
        hint_payloads=[
            {"entries": [{"node_id": "item_memory_dampener", "surface_forms": []}]},
            {"entries": [{"node_id": "item_memory_dampener", "surface_forms": ["memory dampener"]}]},
        ],
    )

    output, _, _, _ = run_author(state, context)

    assert context.llm_client.json_calls == 2
    hints = output.get("author_extraction_surface_hints") or []
    assert hints and hints[0]["surface_forms"] == ["memory dampener"]


def test_author_emits_hint_diagnostics_when_mandatory_hints_still_missing() -> None:
    state = {
        "chapter_id": 1,
        "narrative_script": "主角離開觀測站。",
        "chapter_start_location": "觀測站",
        "author_goal": "完成撤離",
        "must_include_beats": [],
        "reader_visible_facts": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "觀測站外",
        "ending_state_shift": "主角離開",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": [],
        "tone_direction": "緊張",
        "target_word_count": 80,
        "previous_chapter_summary": "",
        "current_draft": "",
        "last_known_location": "觀測站",
        "draft_feedback": [],
        "reader_feedback": [],
        "planned_graph_nodes": [
            {
                "node_id": "item_memory_dampener",
                "node_type": "ITEM",
                "mandatory": True,
                "role": "ITEM",
                "canonical_name": "memory dampener",
                "writing_brief": "記憶阻尼器",
            }
        ],
    }
    chapter = "第1章\n\n他檢查了工具包，沒有細說內容。"
    context = HintRetryContext(chapter=chapter, hint_payloads=[{"entries": []}, {"entries": []}])

    output, _, _, _ = run_author(state, context)

    assert context.llm_client.json_calls == 2
    diag = output.get("author_extraction_hints_diagnostics") or {}
    assert "item_memory_dampener" in (diag.get("missing_mandatory_hint_node_ids") or [])
