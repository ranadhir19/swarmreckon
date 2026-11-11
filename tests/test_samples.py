from swarmreckon.samples import SAMPLES

DOCS = next(t for t in SAMPLES if t.id == "docs-trio")
UTILS = next(t for t in SAMPLES if t.id == "utils-trio")


def _write_docs(root, subdir=""):
    base = root / subdir if subdir else root
    base.mkdir(parents=True, exist_ok=True)
    (base / "api.md").write_text(
        "# API\nnotejar add\nnotejar list\nnotejar search\nnotejar delete\n")
    (base / "faq.md").write_text(
        "# FAQ\nNotes live in ~/.notejar/notes.json. How does search work?\n")
    (base / "changelog.md").write_text(
        "# Changes\n## 1.0.0 — 2026-09-01\n## 0.9.0 — 2026-06-15\n")


def test_docs_check_at_root(tmp_path):
    _write_docs(tmp_path)
    score, _ = DOCS.check(tmp_path)
    assert score == 1.0


def test_docs_check_finds_nested_files(tmp_path):
    # Regression: bench round 1 scored 0.00 everywhere because the
    # planner nested the files under docs/ and the check did not look.
    _write_docs(tmp_path, "docs")
    score, detail = DOCS.check(tmp_path)
    assert score == 1.0
    assert "missing" not in detail


def test_docs_check_missing_files(tmp_path):
    score, detail = DOCS.check(tmp_path)
    assert score == 0.0
    assert "missing" in detail


def test_utils_check_without_tests(tmp_path):
    score, detail = UTILS.check(tmp_path)
    assert score == 0.0
    assert "no test files" in detail


def test_utils_check_runs_produced_tests(tmp_path):
    (tmp_path / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_mod.py").write_text(
        "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    score, detail = UTILS.check(tmp_path)
    assert score == 1.0
    assert "1/1" in detail
