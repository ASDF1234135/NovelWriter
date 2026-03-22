from app.domain.schema import CharacterNode, EdgeType, GraphEdge, GraphSnapshot, LocationNode, VectorDocument
from app.services.workflow.continuity import build_continuity_packet, resolve_pov_character_id


def test_resolve_pov_character_id_maps_to_existing_character_node() -> None:
    snapshot = GraphSnapshot(
        nodes=[
            CharacterNode(
                node_id="char_exiled_knight",
                canonical_name="主角",
                aliases=["調查者"],
                description="被流放的騎士。",
            ),
            LocationNode(node_id="loc_alley", canonical_name="後巷"),
        ],
        edges=[],
    )

    resolved = resolve_pov_character_id("knight_exile", snapshot)

    assert resolved == "char_exiled_knight"


def test_build_continuity_packet_prefers_recent_chapter_summary_metadata() -> None:
    chapters = [
        {"chapter_id": 1, "title": "第1章", "content": "第1章 開頭描述很多，但真正重點不是這裡。"},
        {"chapter_id": 2, "title": "第2章", "content": "第2章 這也是正文開頭，不該直接變成上一章摘要。"},
    ]
    vector_hits = [
        VectorDocument(
            text_chunk="第2章摘要：主角抵達斷刃酒館後巷，通過驗證後停留等待。",
            metadata={
                "chapter_id": 2,
                "epoch_id": "epoch_present",
                "memory_type": "chapter_summary",
                "chapter_summary": "主角抵達斷刃酒館後巷，通過驗證後停留等待。",
                "location_name": "斷刃酒館後巷",
            },
        ),
        VectorDocument(
            text_chunk="第1章摘要：主角進入鏽蝕區並取得接頭暗號。",
            metadata={
                "chapter_id": 1,
                "epoch_id": "epoch_present",
                "memory_type": "chapter_summary",
                "chapter_summary": "主角進入鏽蝕區並取得接頭暗號。",
                "location_name": "鏽蝕區",
            },
        ),
    ]

    packet = build_continuity_packet(
        chapters,
        GraphSnapshot(nodes=[], edges=[]),
        vector_hits,
        pov_character_id="char_exiled_knight",
        active_epoch_id="epoch_present",
    )

    assert packet["previous_chapter_summary"] == "主角抵達斷刃酒館後巷，通過驗證後停留等待。"
    assert "第2章：主角抵達斷刃酒館後巷，通過驗證後停留等待。" in packet["recent_chapter_context"]


def test_build_continuity_packet_filters_location_by_epoch_and_recency() -> None:
    snapshot = GraphSnapshot(
        nodes=[
            CharacterNode(
                node_id="char_exiled_knight",
                canonical_name="主角",
                aliases=["調查者"],
                description="被流放的騎士。",
            ),
            LocationNode(node_id="loc_alley", canonical_name="後巷"),
        ],
        edges=[
            GraphEdge(
                edge_id="edge_old_loc",
                source_id="char_exiled_knight",
                relation_type=EdgeType.LOCATED_IN,
                target_id="loc_alley",
                valid_epoch="epoch_past",
                start_event_id="evt_old",
                end_event_id=None,
                is_truth=True,
                is_public=False,
                known_by=["char_exiled_knight"],
            )
        ],
    )
    vector_hits = [
        VectorDocument(
            text_chunk="舊摘要",
            metadata={
                "chapter_id": 5,
                "epoch_id": "epoch_past",
                "memory_type": "chapter_summary",
                "location_name": "舊碼頭",
            },
        ),
        VectorDocument(
            text_chunk="新摘要",
            metadata={
                "chapter_id": 2,
                "epoch_id": "epoch_present",
                "memory_type": "chapter_summary",
                "location_name": "斷刃酒館後巷",
            },
        ),
    ]

    packet = build_continuity_packet(
        chapters=[{"chapter_id": 2, "title": "第2章", "content": "第2章 主角停留在後巷。"}],
        graph_snapshot=snapshot,
        vector_hits=vector_hits,
        pov_character_id="char_exiled_knight",
        active_epoch_id="epoch_present",
    )

    assert packet["last_known_location"] == "斷刃酒館後巷"
