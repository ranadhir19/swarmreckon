"""Bundled sample tasks with deterministic checks, used by the bench.

Each sample is a small, self-contained development task whose output
can be graded by a machine check rather than by taste:

- ``utils-trio``: three independent Python utility modules, each with
  its own unit tests. The check runs the produced tests and counts
  passes — code that doesn't work scores badly, whoever wrote it.
- ``docs-trio``: three documentation files for a fictional CLI, from
  a spec embedded in the task. The check counts how many of the
  spec's required facts and sections actually appear.

The check score is a labelled proxy for quality (0.0-1.0), reported
alongside reviewer scores, never instead of them.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SampleTask:
    id: str
    title: str
    task: str

    def check(self, out_dir: Path) -> tuple[float, str]:
        if self.id == "utils-trio":
            return _check_utils(out_dir)
        if self.id == "docs-trio":
            return _check_docs(out_dir)
        return 0.0, "no check defined"  # pragma: no cover


UTILS_TASK = """Create three independent Python utility modules, each in
its own file, each with its own unittest test file:

1. textslug.py — a function slugify(text) that lowercases text,
   replaces runs of non-alphanumeric characters with single hyphens,
   and strips leading/trailing hyphens. Test file: test_textslug.py
   with at least 3 test cases.
2. chunker.py — a function chunk_list(items, size) that splits a list
   into consecutive chunks of at most size, raising ValueError if
   size < 1. Test file: test_chunker.py with at least 3 test cases.
3. backoff.py — a function delay_for(attempt, base=0.5, cap=8.0) that
   returns min(cap, base * 2 ** attempt). Test file: test_backoff.py
   with at least 3 test cases.

Tests must use the unittest framework and import the module they test.
Each module must be independent of the other two."""

DOCS_SPEC = """The fictional CLI "notejar" saves short notes from the
terminal. Commands: `notejar add "text"` (save a note), `notejar list`
(list notes, newest first), `notejar search KEYWORD` (full-text
search), `notejar delete ID` (delete by numeric id). Notes are stored
in ~/.notejar/notes.json. Version 1.0.0 (2026-09-01) added search;
version 0.9.0 (2026-06-15) was the first public release with add and
list only."""

DOCS_TASK = f"""Write three documentation files for the notejar CLI,
based only on this spec:

{DOCS_SPEC}

1. api.md — a command reference covering all four commands, with a
   section per command.
2. faq.md — a FAQ with at least four questions and answers, including
   where notes are stored and how search works.
3. changelog.md — a changelog with an entry for version 1.0.0 and an
   entry for version 0.9.0, using the dates and changes from the spec.

Each file must stand on its own; do not invent commands or versions
that are not in the spec."""


def _check_utils(out_dir: Path) -> tuple[float, str]:
    if not out_dir.exists() or not any(out_dir.rglob("test_*.py")):
        return 0.0, "no test files produced"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header",
             "-p", "no:cacheprovider", "."],
            cwd=out_dir, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return 0.0, "pytest timed out"
    out = proc.stdout + proc.stderr
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", out)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", out)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", out)) else 0
    total = passed + failed + errors
    if total == 0:
        return 0.0, f"no tests collected; pytest tail: {out.strip()[-160:]}"
    return passed / total, f"{passed}/{total} produced tests passed"


_DOCS_REQUIRED = {
    "api.md": ["notejar add", "notejar list", "notejar search",
               "notejar delete"],
    "faq.md": ["~/.notejar/notes.json", "search"],
    "changelog.md": ["1.0.0", "0.9.0", "2026-09-01", "2026-06-15"],
}


def _check_docs(out_dir: Path) -> tuple[float, str]:
    found = total = 0
    details = []
    for fname, needles in _DOCS_REQUIRED.items():
        total += len(needles)
        # The file counts wherever the run placed it (round 1 of the
        # bench scored 0.00 across the board because the planner put
        # the files under docs/ and this check only looked at the
        # root — an instrument bug, fixed here and regression-tested).
        matches = sorted(out_dir.rglob(fname)) if out_dir.exists() else []
        path = matches[0] if matches else None
        if path is None:
            details.append(f"{fname} missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [n for n in needles if n.lower() in text.lower()]
        found += len(hits)
        details.append(f"{fname}: {len(hits)}/{len(needles)} required items")
    return found / total, "; ".join(details)


SAMPLES: list[SampleTask] = [
    SampleTask(id="utils-trio", title="Three utility modules with tests",
               task=UTILS_TASK),
    SampleTask(id="docs-trio", title="Three documentation files from a spec",
               task=DOCS_TASK),
]
