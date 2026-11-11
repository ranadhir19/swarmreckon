import json

from swarmreckon.ledger import read_ledger
from swarmreckon.memory import load_lessons
from swarmreckon.orchestrator import Orchestrator
from swarmreckon.providers import FakeProvider


def _run(tmp_path, mode):
    orch = Orchestrator(FakeProvider(), tmp_path / "ws", use_lessons=True)
    return orch.run("Write alpha and beta modules.", mode=mode)


def test_parallel_run_end_to_end(tmp_path):
    result = _run(tmp_path, "parallel")
    assert sorted(result.files) == ["alpha.py", "beta.py"]
    for rel in result.files:
        assert (result.run_dir / "out" / rel).exists()
    records = read_ledger(result.run_dir)
    roles = [r["role"] for r in records]
    assert roles.count("planner") == 1
    assert roles.count("coder") == 2
    assert roles.count("reviewer") == 1
    assert all(r["status"] == "ok" for r in records)
    assert result.review["verdict"] == "pass"
    assert (result.run_dir / "report.md").exists()
    assert (result.run_dir / "audit.jsonl").exists()
    assert (result.run_dir / "memory.jsonl").exists()


def test_sequential_run_end_to_end(tmp_path):
    result = _run(tmp_path, "sequential")
    assert sorted(result.files) == ["alpha.py", "beta.py"]
    assert result.totals["calls"] == 4
    assert result.totals["calls_ok"] == 4


def test_lessons_are_recorded_and_reloaded(tmp_path):
    ws = tmp_path / "ws"
    orch = Orchestrator(FakeProvider(), ws, use_lessons=True)
    orch.run("Write alpha and beta modules.", mode="parallel")
    lessons = load_lessons(ws)
    assert lessons and "independent" in lessons[-1]


def test_run_json_is_complete(tmp_path):
    result = _run(tmp_path, "parallel")
    data = json.loads((result.run_dir / "run.json").read_text())
    assert data["mode"] == "parallel"
    assert data["files"] == ["alpha.py", "beta.py"]
    assert data["totals"]["calls"] == 4
