"""Shared memory: a run-scoped blackboard plus a cross-run lessons log.

Deliberately small. The blackboard is an append-only JSONL file inside
the run directory — every worker publishes what it produced, and every
worker can read the snapshot. The lessons log is a second JSONL file
that lives in the workspace across runs: the reviewer extracts lessons
from each run, and the planner reads the most recent ones next time.
Both are plain files a human can open, diff, and delete. (A persistent
cross-harness memory *product* is a different tool in the portfolio;
this one keeps only what a run needs.)
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Blackboard:
    """Append-only shared memory for one run."""

    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "memory.jsonl"
        self.path.touch(exist_ok=True)
        self._entries: list[dict] = []

    def publish(self, author: str, kind: str, body: str) -> None:
        entry = {"ts": _now(), "author": author, "kind": kind, "body": body}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        self._entries.append(entry)

    def snapshot(self, max_chars: int = 6000) -> str:
        """A bounded text view of everything published so far."""
        lines = [f"[{e['author']}/{e['kind']}] {e['body']}" for e in self._entries]
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[-max_chars:]
        return text


def lessons_path(workspace: Path) -> Path:
    return Path(workspace) / "memory" / "lessons.jsonl"


def load_lessons(workspace: Path, limit: int = 8) -> list[str]:
    """Most recent lessons from earlier runs, newest last."""
    path = lessons_path(workspace)
    if not path.exists():
        return []
    lessons: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("lesson"):
            lessons.append(str(rec["lesson"]))
    return lessons[-limit:]


def append_lessons(workspace: Path, lessons: list[str], run_id: str) -> None:
    path = lessons_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for lesson in lessons:
            fh.write(json.dumps(
                {"ts": _now(), "run_id": run_id, "lesson": lesson}) + "\n")
