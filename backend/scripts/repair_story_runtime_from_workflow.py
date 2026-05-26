"""Restore stories.story_runtime_json from a completed workflow run snapshot.

Usage (from backend/):
  python scripts/repair_story_runtime_from_workflow.py story_b3d3994568 548c9a14-e2ab-4903-8812-7799004cffda
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import get_settings
from app.domain.story_runtime import hydrate_anchor_nodes, parse_story_runtime
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository


def _resolve_db_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    for candidate in (
        _BACKEND.parent / "data" / "novelbuilder.sqlite3",
        _BACKEND / "data" / "novelbuilder.sqlite3",
        Path(get_settings().sqlite_path),
    ):
        if candidate.is_file():
            return candidate.resolve()
    return Path(get_settings().sqlite_path).resolve()


def repair(
    story_id: str,
    source_run_id: str,
    *,
    db_path: str | None = None,
    dry_run: bool = False,
) -> None:
    db = SQLiteDatabase(str(_resolve_db_path(db_path)))
    story_repo = StoryRepository(db)
    wf_repo = WorkflowRepository(db)

    story = story_repo.get_story(story_id)
    if not story:
        raise SystemExit(f"Story not found: {story_id}")

    state = wf_repo.get_run_state(source_run_id)
    if not state or str(state.get("story_id") or "") != story_id:
        raise SystemExit(f"Run not found or wrong story: {source_run_id}")

    resolved = sorted(
        dict.fromkeys(str(x).strip() for x in (state.get("resolved_anchors") or []) if str(x).strip())
    )
    candidates = list(state.get("anchor_candidates") or [])
    rt = parse_story_runtime(story.get("story_runtime_json"))
    prev_resolved = list(rt.get("resolved_anchors") or [])

    print(f"story_id={story_id}")
    print(f"source_run_id={source_run_id} chapter_id={state.get('chapter_id')}")
    print(f"prev resolved_anchors ({len(prev_resolved)}): {prev_resolved}")
    print(f"restore resolved_anchors ({len(resolved)}): {resolved}")
    print(f"restore anchor_candidates: {candidates}")

    if dry_run:
        print("dry-run: no write")
        return

    rt["resolved_anchors"] = resolved
    if candidates:
        rt["anchor_candidates"] = candidates
    story_repo.update_story_runtime_json(story_id, rt)

    hydrated = hydrate_anchor_nodes(
        list(story.get("anchor_nodes_json") or []),
        resolved_anchors=resolved,
        anchor_properties=dict(rt.get("anchor_properties") or {}),
    )
    resolved_n = sum(1 for n in hydrated if str(n.get("status")).upper() == "RESOLVED")
    unlocked = [n.get("id") for n in hydrated if str(n.get("status")).upper() == "UNLOCKED"]
    print(f"after hydrate: RESOLVED={resolved_n} UNLOCKED={unlocked}")
    print("repair complete")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__.strip())
        raise SystemExit(2)
    story_id = sys.argv[1]
    run_id = sys.argv[2]
    dry = "--dry-run" in sys.argv
    db_path = None
    for i, arg in enumerate(sys.argv):
        if arg == "--db" and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 1]
    repair(story_id, run_id, db_path=db_path, dry_run=dry)


if __name__ == "__main__":
    main()
