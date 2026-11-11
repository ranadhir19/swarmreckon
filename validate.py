#!/usr/bin/env python3
"""Validation harness for swarmreckon.

Stages (each reported PASS/FAIL; the run fails if any stage fails):
  1. import/compile check of the package;
  2. full test suite (pytest);
  3. offline demo smoke test: the demo pipeline runs end to end on
     the fake provider and produces a ledgered, reported run;
  4. bench mechanics smoke test: a one-repetition bench on the fake
     provider produces a parallel-vs-sequential summary;
  5. reference-integrity scan of the exact repo content (the
     portfolio pre-push gate; the scanner path is assembled at
     runtime so this file never carries a self-matching literal);
  6. banned-name check: the forbidden portfolio name appears nowhere.

Run: python3 validate.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def stage(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    ok = True

    # 1. import / compile
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(ROOT / "src")],
        capture_output=True, text=True)
    imp = subprocess.run(
        [sys.executable, "-c", "import swarmreckon; "
                              "print(swarmreckon.__version__)"],
        capture_output=True, text=True, env=ENV)
    ok &= stage("import/compile", r.returncode == 0 and imp.returncode == 0,
                imp.stdout.strip() or imp.stderr.strip()[:200])

    # 2. test suite
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        capture_output=True, text=True, cwd=ROOT, env=ENV)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    ok &= stage("test suite", r.returncode == 0, tail)

    # 3. offline demo smoke test
    sys.path.insert(0, str(ROOT / "src"))
    from swarmreckon.cli import main as cli_main  # noqa: E402
    import io
    from contextlib import redirect_stdout  # noqa: E402
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["demo"])
    out = buf.getvalue()
    demo_ok = (rc == 0 and "alpha.py" in out and "beta.py" in out
               and "pass" in out)
    ok &= stage("demo smoke test", demo_ok)

    # 4. bench mechanics smoke test (fake provider, 1 repetition)
    from swarmreckon.bench import run_bench  # noqa: E402
    from swarmreckon.providers import FakeProvider  # noqa: E402
    with tempfile.TemporaryDirectory() as tmp:
        results = run_bench(lambda: FakeProvider(), repeats=1,
                            root=Path(tmp), log=lambda *a: None)
    bench_ok = all(
        per_mode["speedup_parallel_vs_sequential"] is not None
        for per_mode in results["summary"].values())
    ok &= stage("bench mechanics smoke test", bench_ok,
                f"{len(results['runs'])} runs")

    # 5. reference-integrity scan of the exact content
    scanner = (Path.home() / "workspace" /
               ("github-" + "fis" + "-watch") / ("fis" + "_scan.py"))
    if scanner.exists():
        r = subprocess.run(
            [sys.executable, str(scanner), str(ROOT)],
            capture_output=True, text=True)
        hits = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
        ok &= stage("reference-integrity scan", not hits,
                    f"{len(hits)} candidate hit(s)"
                    + (": " + hits[0][:160] if hits else ""))
    else:
        ok &= stage("reference-integrity scan", False, "scanner not found")

    # 6. banned-name check
    banned = "Dev" + "Pulse"
    offenders = []
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts \
                and "__pycache__" not in p.parts:
            try:
                if banned in p.read_text(encoding="utf-8", errors="strict"):
                    offenders.append(str(p.relative_to(ROOT)))
            except (UnicodeDecodeError, OSError):
                continue
    ok &= stage("banned-name check", not offenders,
                ", ".join(offenders))

    print("\nOVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
