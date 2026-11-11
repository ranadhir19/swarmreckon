"""The approval gate: worker output is a proposal until a human says so.

Workers never write to a real target directory directly. Their files
are staged in the run sandbox (``out/``). Applying them to a target
requires a decision per file:

- interactive runs prompt per file;
- non-interactive runs apply nothing unless ``approve_all`` is set;
- every decision — applied, rejected, or left pending — is written
  to the run's audit log.

Paths are sanitised before any decision: absolute paths and ``..``
escapes are refused outright and audited as refusals.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def sanitise_relpath(path: str) -> str | None:
    """Return a safe relative path, or None if the path is unsafe."""
    p = Path(path)
    if p.is_absolute() or not path.strip():
        return None
    parts = [part for part in p.parts if part not in ("", ".")]
    if any(part == ".." for part in parts) or not parts:
        return None
    return "/".join(parts)


class AuditLog:
    """Append-only audit trail for gate and lifecycle decisions."""

    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "audit.jsonl"
        self.path.touch(exist_ok=True)

    def log(self, event: str, **fields) -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
        rec.update(fields)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def apply_proposals(files: dict[str, str], target_dir: Path, *,
                    approve_all: bool = False, interactive: bool = False,
                    audit: AuditLog | None = None,
                    prompt_fn=input) -> dict[str, str]:
    """Decide the fate of each proposed file against ``target_dir``.

    Returns {relative_path: decision} where decision is one of
    ``applied``, ``rejected``, ``pending``, ``refused-unsafe-path``.
    Only ``applied`` files are written.
    """
    target_dir = Path(target_dir)
    decisions: dict[str, str] = {}
    for rel, content in sorted(files.items()):
        safe = sanitise_relpath(rel)
        if safe is None:
            decisions[rel] = "refused-unsafe-path"
            if audit:
                audit.log("gate_refused", path=rel,
                          reason="absolute or escaping path")
            continue
        if approve_all:
            decision = "applied"
        elif interactive:
            answer = prompt_fn(
                f"Apply {safe} to {target_dir}? [y/N] ").strip().lower()
            decision = "applied" if answer in ("y", "yes") else "rejected"
        else:
            decision = "pending"
        if decision == "applied":
            dest = target_dir / safe
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        decisions[safe] = decision
        if audit:
            audit.log("gate_decision", path=safe, decision=decision,
                      target=str(target_dir))
    return decisions
