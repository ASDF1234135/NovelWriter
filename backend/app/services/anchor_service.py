from __future__ import annotations

import json

from app.domain.schema import (
    MacroCastMember,
    MacroNestedAnchorDraft,
    MacroPlanOutput,
    MacroVolumePlanDraft,
    StateAnchor,
    StoryCastMemberStored,
    StoryInput,
    VolumePlan,
)
from app.services.llm import LLMClient, MockLLMClient
from app.services.workflow.constants import MAX_ANCHORS_PER_VOLUME, MIN_ANCHORS_PER_VOLUME
from app.services.workflow.profiles import get_profile


class AnchorService:
    def compile_macro_plan(
        self, story_id: str, story_input: StoryInput, llm_client: LLMClient | None = None
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, str]]]:
        fixed_total_chapters = max(12, story_input.target_total_words // 2500)
        if llm_client is not None and not isinstance(llm_client, MockLLMClient):
            profile = get_profile("macro_planner")
            prompt = self._build_macro_prompt(story_input, fixed_total_chapters)
            structured_output, _ = llm_client.invoke_json(prompt, MacroPlanOutput, profile)
            return self._normalize_macro_plan(
                story_id, structured_output, fixed_total_chapters, story_input.target_total_words, story_input
            )
        return self._build_mock_macro_plan(story_id, story_input)

    def _build_mock_macro_plan(
        self, story_id: str, story_input: StoryInput
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, str]]]:
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

        plan = MacroPlanOutput(
            cast=[],  # filled by _normalize_cast_output defaults
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

    def _build_macro_prompt(self, story_input: StoryInput, fixed_total_chapters: int) -> str:
        return json.dumps(
            {
                "title": story_input.title,
                "premise": story_input.premise,
                "bible": story_input.bible,
                "target_total_words": story_input.target_total_words,
                "fixed_total_chapters": fixed_total_chapters,
                "output_shape": {
                    "cast": [
                        {
                            "canonical_name": "string",
                            "role": "protagonist | supporting",
                            "short_bio": "string optional",
                            "aliases": "string[] optional",
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
                                }
                            ],
                        }
                    ],
                },
                "requirements": [
                    f"總章數固定為 {fixed_total_chapters} 章，必須嚴格依此規劃。",
                    "請規劃 3-5 個 volumes。",
                    "每個 volume 需有連續不重疊的 chapter_start / chapter_end，且涵蓋 1 到總章數。",
                    f"每個 volume 都必須提供 target_volume_words，且所有 volume 的字數總和應接近 {story_input.target_total_words}。",
                    f"**每個 volume 的 anchors 陣列必須含 {MIN_ANCHORS_PER_VOLUME}-{MAX_ANCHORS_PER_VOLUME} 個元素**；"
                    "每個 anchor 的 chapter_target 必須落在該 volume 的 chapter_start 與 chapter_end 之間（含）。",
                    "每個 anchor 都要呼應 premise 與 bible；target_state 必須具體可追蹤。",
                    "若 bible 含 story_genre、writing_style、narrative_pov 或 tone，卷／anchors／cast 的規劃與命名必須與這些設定一致。",
                    "不要把 anchors 放在 volumes 外層；只能嵌套在對應 volume 內。",
                    "cast 陣列：至少 1 位 role=protagonist，可選多位 supporting；"
                    "錨點標題與描述應優先使用 cast 中的 canonical_name，避免泛稱「主角」。",
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
            ),
            MacroCastMember(
                canonical_name="重要配角",
                role="supporting",
                short_bio="與主線密切相關的核心人物。",
            ),
        ]

    def _normalize_cast_output(
        self, story_id: str, raw: list[MacroCastMember], story_input: StoryInput
    ) -> list[StoryCastMemberStored]:
        members = list(raw) if raw else []
        members = [m for m in members if (m.canonical_name or "").strip()]
        if not members:
            members = self._default_cast_drafts(story_input)

        if not any(m.role == "protagonist" for m in members):
            members[0] = members[0].model_copy(update={"role": "protagonist"})

        members.sort(key=lambda m: (0 if m.role == "protagonist" else 1, m.canonical_name))
        protagonist_seen = False
        coerced: list[MacroCastMember] = []
        for m in members:
            if m.role == "protagonist":
                if protagonist_seen:
                    m = m.model_copy(update={"role": "supporting"})
                else:
                    protagonist_seen = True
            coerced.append(m)
        members = coerced
        members.sort(key=lambda m: (0 if m.role == "protagonist" else 1, m.canonical_name))

        stored: list[StoryCastMemberStored] = []
        for idx, m in enumerate(members, start=1):
            node_id = f"{story_id}_mc_{idx:02d}"
            name = m.canonical_name.strip()
            stored.append(
                StoryCastMemberStored(
                    node_id=node_id,
                    canonical_name=name,
                    role=m.role,
                    short_bio=(m.short_bio or "")[:500],
                    aliases=[a.strip() for a in m.aliases if str(a).strip()][:8],
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
    ) -> tuple[list[VolumePlan], list[StateAnchor], list[StoryCastMemberStored], list[dict[str, str]]]:
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
        b_seed: list[dict[str, str]] = []
        for raw in output.initial_b_stories or []:
            if not isinstance(raw, dict):
                continue
            bid = str(raw.get("id") or "").strip()
            if not bid:
                continue
            b_seed.append({"id": bid, "desc": str(raw.get("desc") or "")[:800]})
        return volumes, anchors, cast_stored, b_seed

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
