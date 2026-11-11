import json

from swarmreckon.ledger import estimate_cost_usd
from swarmreckon.orchestrator import (
    CODER_SYSTEM, PLANNER_SYSTEM, REVIEWER_SYSTEM, parse_files,
    parse_plan, parse_review, route_model)
from swarmreckon.providers import FakeProvider, stated_retry_delay


def test_stated_retry_delay_parses_provider_bodies():
    assert stated_retry_delay("Please retry in 46s", 0) == 47.0
    assert stated_retry_delay("retry in 6h38m16s", 0) == 90.0  # capped
    assert stated_retry_delay("retry in 1m30s", 0) == 90.0  # 91s -> cap


def test_stated_retry_delay_falls_back_to_backoff():
    assert stated_retry_delay("", 0) == 2.0
    assert stated_retry_delay("no delay stated", 2) == 8.0


def test_fake_planner_returns_parseable_plan():
    provider = FakeProvider()
    res = provider.chat(PLANNER_SYSTEM, "Task: anything", "fake-1")
    subtasks, _ = parse_plan(res.text, "anything")
    assert len(subtasks) == 2
    assert all(s.role == "coder" for s in subtasks)


def test_fake_coder_honours_target_file():
    provider = FakeProvider()
    res = provider.chat(CODER_SYSTEM, "Target file: gamma.py\nDo it",
                        "fake-1")
    files = parse_files(res.text, "")
    assert list(files) == ["gamma.py"]
    assert "VALUE = 1" in files["gamma.py"]


def test_fake_reviewer_returns_parseable_review():
    provider = FakeProvider()
    res = provider.chat(REVIEWER_SYSTEM, "files...", "fake-1")
    review = parse_review(res.text)
    assert review["verdict"] == "pass"
    assert review["score"] == 8
    assert review["lessons"]


def test_parse_plan_falls_back_on_garbage():
    subtasks, notes = parse_plan("no json here", "the whole task")
    assert len(subtasks) == 1
    assert subtasks[0].instructions == "the whole task"
    assert "fell back" in notes


def test_parse_files_fallback_uses_default_target():
    files = parse_files("```python\nX = 3\n```", "mod.py")
    assert files == {"mod.py": "X = 3"}


def test_parse_review_unparsed():
    review = parse_review("not json")
    assert review["verdict"] == "unparsed"
    assert review["score"] is None


def test_routing():
    assert route_model("groq", "coder", "simple") == "openai/gpt-oss-20b"
    assert route_model("groq", "coder", "complex") == "openai/gpt-oss-120b"
    assert route_model("groq", "planner") == "openai/gpt-oss-120b"
    assert route_model("groq", "reviewer") == "openai/gpt-oss-120b"


def test_cost_estimate_uses_price_table():
    est = estimate_cost_usd("openai/gpt-oss-120b", 1_000_000, 1_000_000)
    assert est is not None and abs(est - 0.75) < 1e-9
    assert estimate_cost_usd("unknown-model", 10, 10) is None
    assert estimate_cost_usd("openai/gpt-oss-120b", None, 10) is None


def test_fake_provider_records_usage():
    provider = FakeProvider()
    res = provider.chat(PLANNER_SYSTEM, "x" * 40, "fake-1")
    assert res.prompt_tokens and res.prompt_tokens >= 1
    assert json.loads(res.text)  # planner output is valid JSON
