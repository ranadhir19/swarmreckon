"""Render a human-readable report for a run from its own records.

The report is derived only from run.json + ledger.jsonl + audit.jsonl
in the run directory, so it can be regenerated at any time with
``swarmreckon report <run_dir>`` and will always match the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from .ledger import read_ledger


def render_report(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    summary = {}
    run_json = run_dir / "run.json"
    if run_json.exists():
        summary = json.loads(run_json.read_text(encoding="utf-8"))
    records = read_ledger(run_dir)
    totals = summary.get("totals", {})
    review = summary.get("review", {})

    lines = [
        f"# Run {summary.get('run_id', run_dir.name)}",
        "",
        f"- Mode: **{summary.get('mode', '?')}**",
        f"- Wall time: **{summary.get('wall_s', '?')}s**",
        f"- Task: {summary.get('task', '')}",
        "",
        "## Agent calls (from the ledger)",
        "",
        "| Role | Provider | Model served | Prompt tok | Completion tok | Latency s | Retries | Status | Est. cost $ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r['role']} | {r['provider']} | {r['model_served']} | "
            f"{r['prompt_tokens']} | {r['completion_tokens']} | "
            f"{r['latency_s']} | {r['retries']} | {r['status']} | "
            f"{r['cost_estimate_usd']} |")
    lines += [
        "",
        f"Totals: {totals.get('calls_ok', 0)}/{totals.get('calls', 0)} calls ok, "
        f"{totals.get('prompt_tokens', 0)} prompt + "
        f"{totals.get('completion_tokens', 0)} completion tokens, "
        f"{totals.get('retries', 0)} retries, list-price estimate "
        f"${totals.get('cost_estimate_usd', 0)} (actual spend on free tiers: $0).",
        "",
        "## Files proposed",
        "",
    ]
    files = summary.get("files", [])
    lines += [f"- `{f}`" for f in files] or ["- (none)"]
    lines += [
        "",
        "## Review",
        "",
        f"- Verdict: **{review.get('verdict', '?')}**, "
        f"score: {review.get('score')}",
    ]
    for issue in review.get("issues", []):
        lines.append(f"- Issue: {issue}")
    for lesson in review.get("lessons", []):
        lines.append(f"- Lesson: {lesson}")
    decisions = summary.get("gate_decisions", {})
    if decisions:
        lines += ["", "## Approval gate", ""]
        for path, decision in sorted(decisions.items()):
            lines.append(f"- `{path}`: {decision}")
    if summary.get("plan_notes"):
        lines += ["", f"Planner notes: {summary['plan_notes']}"]
    lines.append("")
    return "\n".join(lines)
