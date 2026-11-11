"""Command line interface.

  swarmreckon demo                     offline end-to-end demo (fake provider)
  swarmreckon run --task "..."         one task, parallel by default
  swarmreckon run --task "..." --mode sequential --target DIR
  swarmreckon bench                    parallel-vs-sequential comparison
  swarmreckon report <run_dir>         re-render a run's report.md

Runs write into a workspace (default ``./.swarmreckon``): one folder
per run with the ledger, audit log, blackboard, proposed files, and
report.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import __version__
from .bench import run_bench, write_bench_outputs
from .orchestrator import Orchestrator
from .providers import FakeProvider, GeminiProvider, GroqProvider
from .report import render_report

DEMO_TASK = ("Write two tiny Python modules: alpha.py defining "
             "VALUE = 1 and beta.py defining VALUE = 2.")


def _provider(name: str):
    if name == "groq":
        return GroqProvider()
    if name == "gemini":
        return GeminiProvider()
    if name == "fake":
        return FakeProvider()
    raise SystemExit(f"unknown provider: {name}")


def _orchestrator(args, workspace: Path) -> Orchestrator:
    review_provider = None
    if getattr(args, "cross_provider_review", False):
        review_provider = GeminiProvider()
    return Orchestrator(_provider(args.provider), workspace,
                        review_provider=review_provider)


def cmd_demo(args) -> int:
    workspace = Path(tempfile.mkdtemp(prefix="swarmreckon-demo-"))
    orch = Orchestrator(FakeProvider(), workspace, use_lessons=False)
    result = orch.run(DEMO_TASK, mode="parallel")
    print(f"demo run {result.run_id} (fake provider, offline)")
    print(f"workspace: {workspace}")
    print(f"wall: {result.wall_s:.2f}s, files: {sorted(result.files)}")
    print(f"review: {result.review.get('verdict')} "
          f"(score {result.review.get('score')})")
    print(f"totals: {result.totals}")
    return 0


def cmd_run(args) -> int:
    task = args.task
    if args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8")
    if not task:
        print("error: --task or --task-file is required", file=sys.stderr)
        return 2
    workspace = Path(args.workspace)
    orch = _orchestrator(args, workspace)
    interactive = (args.target is not None and not args.approve_all
                   and sys.stdin.isatty())
    result = orch.run(task, mode=args.mode,
                      target=Path(args.target) if args.target else None,
                      approve_all=args.approve_all,
                      interactive=interactive)
    print(f"run {result.run_id} ({result.mode}) in {result.wall_s:.1f}s")
    print(f"report: {result.run_dir / 'report.md'}")
    print(f"files proposed: {sorted(result.files)}")
    print(f"review: {result.review.get('verdict')} "
          f"(score {result.review.get('score')})")
    if result.gate_decisions:
        print(f"gate decisions: {result.gate_decisions}")
    print(f"tokens: {result.totals.get('prompt_tokens')} prompt + "
          f"{result.totals.get('completion_tokens')} completion; "
          f"retries {result.totals.get('retries')}; "
          f"list-price estimate ${result.totals.get('cost_estimate_usd')} "
          "(actual spend on free tiers: $0)")
    return 0


def cmd_bench(args) -> int:
    out_dir = Path(args.out)
    results = run_bench(lambda: _provider(args.provider),
                        repeats=args.repeats, root=out_dir / "workspaces")
    json_path, md_path = write_bench_outputs(results, out_dir)
    print(f"bench results: {md_path} and {json_path}")
    for task_id, per_mode in results["summary"].items():
        print(f"{task_id}: speedup "
              f"{per_mode['speedup_parallel_vs_sequential']}× "
              f"(sequential mean {per_mode['sequential']['wall_s']['mean']}s, "
              f"parallel mean {per_mode['parallel']['wall_s']['mean']}s)")
    return 0


def cmd_report(args) -> int:
    print(render_report(Path(args.run_dir)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="swarmreckon",
        description="A parallel multi-agent runner that grades itself: "
                    "every run is ledgered, gated, and benchmarked "
                    "against sequential execution.")
    parser.add_argument("--version", action="version",
                        version=f"swarmreckon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="offline end-to-end demo (fake provider)")

    p_run = sub.add_parser("run", help="run one task")
    p_run.add_argument("--task", default="")
    p_run.add_argument("--task-file", default="")
    p_run.add_argument("--mode", choices=["parallel", "sequential"],
                       default="parallel")
    p_run.add_argument("--provider", choices=["groq", "gemini", "fake"],
                       default="groq",
                       help="gemini is the AI Studio free tier: content "
                            "may be used by Google, so public material only")
    p_run.add_argument("--cross-provider-review", action="store_true",
                       help="review with Gemini instead (free tier: "
                            "content may be used by Google; public "
                            "material only)")
    p_run.add_argument("--workspace", default=".swarmreckon")
    p_run.add_argument("--target", default=None,
                       help="directory to apply proposed files to, "
                            "through the approval gate")
    p_run.add_argument("--approve-all", action="store_true",
                       help="approve every proposed file for --target "
                            "without prompting (still audited)")

    p_bench = sub.add_parser("bench", help="parallel vs sequential bench")
    p_bench.add_argument("--provider", choices=["groq", "gemini", "fake"],
                         default="groq",
                         help="gemini is the AI Studio free tier: content "
                              "may be used by Google, so public material only")
    p_bench.add_argument("--repeats", type=int, default=2)
    p_bench.add_argument("--out", default=".swarmreckon/bench")

    p_report = sub.add_parser("report", help="re-render a run report")
    p_report.add_argument("run_dir")

    args = parser.parse_args(argv)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "bench":
        return cmd_bench(args)
    if args.command == "report":
        return cmd_report(args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
