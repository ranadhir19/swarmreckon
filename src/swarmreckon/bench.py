"""The bench: parallel mode vs sequential mode, same everything else.

For each sample task, the bench runs the orchestrator in both modes,
repeatedly, in a fresh workspace per repetition (lessons from earlier
runs are disabled, so neither mode gets a head start). It records
wall-clock time with spread, token totals, retry counts, the
deterministic check score, and the reviewer's score — then writes
the comparison as JSON and Markdown.

The honest caveats are part of the output: free-tier rate limits are
shared across parallel workers, so a parallel run can be throttled
in ways a sequential run is not; the numbers show whatever actually
happened, including that.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from .orchestrator import Orchestrator
from .samples import SAMPLES, SampleTask


def _agg(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "min": None, "max": None, "stdev": None}
    return {
        "mean": round(statistics.mean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
    }


def run_bench(provider_factory, *, tasks: list[SampleTask] | None = None,
              repeats: int = 2, modes: tuple[str, ...] = ("sequential", "parallel"),
              root: Path, log=print) -> dict:
    tasks = tasks or SAMPLES
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    raw_runs: list[dict] = []

    for task in tasks:
        for mode in modes:
            for rep in range(repeats):
                ws = root / f"ws-{task.id}-{mode}-{rep}"
                orch = Orchestrator(provider_factory(), ws, use_lessons=False)
                log(f"[bench] {task.id} / {mode} / rep {rep + 1} ...")
                t0 = time.time()
                try:
                    result = orch.run(task.task, mode=mode)
                    error = ""
                except Exception as exc:  # keep the bench honest, not dead
                    raw_runs.append({
                        "task": task.id, "mode": mode, "rep": rep,
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "wall_s": round(time.time() - t0, 3)})
                    log(f"[bench]   FAILED: {exc}")
                    continue
                score, detail = task.check(result.run_dir / "out")
                raw_runs.append({
                    "task": task.id, "mode": mode, "rep": rep,
                    "run_id": result.run_id, "wall_s": round(result.wall_s, 3),
                    "files": sorted(result.files),
                    "check_score": score, "check_detail": detail,
                    "review_score": result.review.get("score"),
                    "review_verdict": result.review.get("verdict"),
                    "prompt_tokens": result.totals.get("prompt_tokens"),
                    "completion_tokens": result.totals.get("completion_tokens"),
                    "retries": result.totals.get("retries"),
                    "cost_estimate_usd": result.totals.get("cost_estimate_usd"),
                    "error": error,
                })
                log(f"[bench]   wall {result.wall_s:.1f}s, "
                    f"check {score:.2f} ({detail})")

    summary: dict = {}
    for task in tasks:
        summary[task.id] = {}
        for mode in modes:
            runs = [r for r in raw_runs
                    if r["task"] == task.id and r["mode"] == mode
                    and not r.get("error")]
            summary[task.id][mode] = {
                "runs_ok": len(runs),
                "wall_s": _agg([r["wall_s"] for r in runs]),
                "check_score": _agg([r["check_score"] for r in runs]),
                "prompt_tokens_mean": _agg(
                    [r["prompt_tokens"] or 0 for r in runs])["mean"],
                "completion_tokens_mean": _agg(
                    [r["completion_tokens"] or 0 for r in runs])["mean"],
                "retries_total": sum(r["retries"] or 0 for r in runs),
            }
        seq = summary[task.id]["sequential"]["wall_s"]["mean"]
        par = summary[task.id]["parallel"]["wall_s"]["mean"]
        summary[task.id]["speedup_parallel_vs_sequential"] = (
            round(seq / par, 3) if seq and par else None)

    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "repeats": repeats, "runs": raw_runs, "summary": summary}


def write_bench_outputs(results: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [
        "# Bench results — parallel vs sequential",
        "",
        f"Generated {results['generated_at']}; "
        f"{results['repeats']} repetition(s) per cell, fresh workspace "
        "per run, cross-run lessons disabled for fairness.",
        "",
        "| Task | Mode | Runs ok | Wall mean s | Wall min–max s | Wall stdev | Check score mean | Prompt tok (mean) | Completion tok (mean) | Retries |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for task_id, per_mode in results["summary"].items():
        for mode in ("sequential", "parallel"):
            s = per_mode[mode]
            w = s["wall_s"]
            lines.append(
                f"| {task_id} | {mode} | {s['runs_ok']} | {w['mean']} | "
                f"{w['min']}–{w['max']} | {w['stdev']} | "
                f"{s['check_score']['mean']} | {s['prompt_tokens_mean']} | "
                f"{s['completion_tokens_mean']} | {s['retries_total']} |")
        lines.append(
            f"| **{task_id}** | **speedup (parallel vs sequential)** | "
            f"**{per_mode['speedup_parallel_vs_sequential']}×** | | | | | | | |")
    lines += [
        "",
        "Check score is the deterministic sample check (produced tests "
        "passing / required spec items present) — a proxy for quality, "
        "reported with the reviewer scores in results.json, not instead "
        "of them.",
        "",
        "Caveats: both modes share one free-tier account, so parallel "
        "workers contend for the same per-minute token quota and can be "
        "rate-limited in ways sequential workers are not; retries are "
        "counted in the ledger and above. Actual spend: $0 (free tier). "
        "Cost figures in results.json are list-price estimates.",
        "",
    ]
    md_path = out_dir / "RESULTS.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
