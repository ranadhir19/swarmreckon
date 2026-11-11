from swarmreckon.ledger import Ledger, read_ledger
from swarmreckon.memory import Blackboard, append_lessons, load_lessons


def test_blackboard_snapshot_contains_entries(tmp_path):
    board = Blackboard(tmp_path)
    board.publish("planner", "plan", "two subtasks")
    board.publish("s1", "output", "produced: a.py")
    snap = board.snapshot()
    assert "two subtasks" in snap and "a.py" in snap
    assert (tmp_path / "memory.jsonl").exists()


def test_blackboard_snapshot_is_bounded(tmp_path):
    board = Blackboard(tmp_path)
    board.publish("a", "k", "x" * 5000)
    board.publish("b", "k", "y" * 5000)
    assert len(board.snapshot(max_chars=1000)) <= 1000


def test_lessons_roundtrip_and_limit(tmp_path):
    ws = tmp_path / "ws"
    append_lessons(ws, [f"lesson {i}" for i in range(12)], "run-1")
    lessons = load_lessons(ws, limit=8)
    assert len(lessons) == 8
    assert lessons[-1] == "lesson 11"


def test_ledger_records_and_totals(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.record(run_id="r1", role="planner", provider="fake",
                  model_requested="fake-1", model_served="fake-1",
                  prompt_tokens=100, completion_tokens=50,
                  latency_s=0.5, status="ok")
    ledger.record(run_id="r1", role="coder", provider="fake",
                  model_requested="fake-1", model_served=None,
                  prompt_tokens=None, completion_tokens=None,
                  latency_s=0.0, status="error", detail="boom")
    totals = ledger.totals()
    assert totals["calls"] == 2
    assert totals["calls_ok"] == 1
    assert totals["calls_failed"] == 1
    assert totals["prompt_tokens"] == 100
    records = read_ledger(tmp_path)
    assert len(records) == 2
    assert records[1]["detail"] == "boom"
