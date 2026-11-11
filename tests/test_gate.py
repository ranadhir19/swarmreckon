from swarmreckon.gate import AuditLog, apply_proposals, sanitise_relpath


def test_sanitise_relpath():
    assert sanitise_relpath("a/b.py") == "a/b.py"
    assert sanitise_relpath("/etc/passwd") is None
    assert sanitise_relpath("../escape.py") is None
    assert sanitise_relpath("a/../b.py") is None
    assert sanitise_relpath("") is None


def test_default_is_pending_and_writes_nothing(tmp_path):
    target = tmp_path / "target"
    decisions = apply_proposals({"x.py": "X = 1\n"}, target)
    assert decisions == {"x.py": "pending"}
    assert not (target / "x.py").exists()


def test_approve_all_writes(tmp_path):
    target = tmp_path / "target"
    decisions = apply_proposals({"sub/x.py": "X = 1\n"}, target,
                                approve_all=True)
    assert decisions == {"sub/x.py": "applied"}
    assert (target / "sub" / "x.py").read_text() == "X = 1\n"


def test_interactive_rejection(tmp_path):
    target = tmp_path / "target"
    decisions = apply_proposals({"x.py": "X = 1\n"}, target,
                                interactive=True,
                                prompt_fn=lambda _: "n")
    assert decisions == {"x.py": "rejected"}
    assert not (target / "x.py").exists()


def test_interactive_acceptance(tmp_path):
    target = tmp_path / "target"
    decisions = apply_proposals({"x.py": "X = 1\n"}, target,
                                interactive=True,
                                prompt_fn=lambda _: "y")
    assert decisions == {"x.py": "applied"}
    assert (target / "x.py").exists()


def test_unsafe_path_refused_and_audited(tmp_path):
    audit = AuditLog(tmp_path)
    decisions = apply_proposals({"../evil.py": "X\n"}, tmp_path / "t",
                                approve_all=True, audit=audit)
    assert decisions["../evil.py"] == "refused-unsafe-path"
    assert not (tmp_path / "evil.py").exists()
    assert "gate_refused" in audit.path.read_text()
