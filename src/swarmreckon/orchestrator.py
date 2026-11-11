"""The orchestrator: planner → parallel (or sequential) workers → reviewer.

One task goes in. A planner decomposes it into role-specialised
subtasks. Coder workers execute them — concurrently in ``parallel``
mode, one at a time in ``sequential`` mode, with identical prompts
and models so the two modes differ only in concurrency (that is what
makes the bench comparison mean something). A reviewer reads the
produced files, scores them, and extracts lessons for future runs.

Everything the agents produce is a proposal staged in the run's
``out/`` directory; the approval gate (gate.py) decides whether any
of it reaches a real target directory.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .gate import AuditLog, apply_proposals, sanitise_relpath
from .ledger import Ledger
from .memory import Blackboard, append_lessons, load_lessons
from .providers import ChatResult, ProviderError

PLANNER_SYSTEM = """ROLE: PLANNER
You decompose a small software development task into 2-4 independent
subtasks that different workers can execute without waiting on each
other. Reply with JSON only, no prose, in exactly this shape:
{"subtasks": [{"id": "s1", "title": "...", "role": "coder",
"complexity": "simple", "target": "relative/file/path",
"instructions": "precise instructions for the worker"}], "notes": "..."}
Complexity is one of: simple, standard, complex.
Each subtask produces exactly one primary file (its target). Use the
file paths named in the task exactly as given; do not add directories
the task did not ask for. Prefer subtasks whose outputs do not import
or depend on each other's unwritten contents; where a test file is
wanted, make it part of the same subtask as the module it tests."""

CODER_SYSTEM = """ROLE: CODER
You write exactly the files your subtask asks for, completely and
correctly, with no placeholders. Reply with one block per file in
exactly this format and nothing else:
<<<FILE path="relative/path.py">>>
<full file content>
<<<END FILE>>>
Do not explain, do not use markdown fences inside the blocks."""

REVIEWER_SYSTEM = """ROLE: REVIEWER
You review files produced by other agents for a task: correctness,
completeness against the task, and obvious risks. Reply with JSON
only, no prose, in exactly this shape:
{"verdict": "pass|revise", "score": 0, "issues": ["..."],
"lessons": ["one transferable lesson for future runs"]}
Score is an integer 0-10. Lessons must be general, not task-specific
trivia; at most 3."""

# Complexity routing: simple work goes to the small free model;
# standard and complex work goes to the large one. Planner and
# reviewer always use the large model (few calls, high leverage).
_ROUTES = {
    "groq": {"planner": "openai/gpt-oss-120b",
             "reviewer": "openai/gpt-oss-120b",
             "simple": "openai/gpt-oss-20b",
             "standard": "openai/gpt-oss-120b",
             "complex": "openai/gpt-oss-120b"},
    "gemini": {"planner": "gemini-3.5-flash",
               "reviewer": "gemini-3.5-flash",
               "simple": "gemini-3.5-flash",
               "standard": "gemini-3.5-flash",
               "complex": "gemini-3.5-flash"},
    "fake": {"planner": "fake-1", "reviewer": "fake-1",
             "simple": "fake-1", "standard": "fake-1", "complex": "fake-1"},
}


def route_model(provider_name: str, role: str, complexity: str = "standard") -> str:
    table = _ROUTES.get(provider_name, _ROUTES["fake"])
    if role in ("planner", "reviewer"):
        return table[role]
    return table.get(complexity, table["standard"])


@dataclass
class Subtask:
    id: str
    title: str
    role: str = "coder"
    complexity: str = "standard"
    target: str = ""
    instructions: str = ""


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    mode: str
    wall_s: float
    files: dict[str, str] = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    totals: dict = field(default_factory=dict)
    gate_decisions: dict[str, str] = field(default_factory=dict)
    plan_notes: str = ""


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON object extraction from a model reply."""
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_plan(text: str, task: str) -> tuple[list[Subtask], str]:
    """Parse the planner's reply; degrade to one subtask if unparseable."""
    obj = _extract_json(text)
    subtasks: list[Subtask] = []
    notes = ""
    if obj:
        notes = str(obj.get("notes", ""))
        for i, raw in enumerate(obj.get("subtasks") or []):
            if not isinstance(raw, dict):
                continue
            complexity = str(raw.get("complexity", "standard")).lower()
            if complexity not in ("simple", "standard", "complex"):
                complexity = "standard"
            subtasks.append(Subtask(
                id=str(raw.get("id") or f"s{i + 1}"),
                title=str(raw.get("title") or f"Subtask {i + 1}"),
                role=str(raw.get("role") or "coder"),
                complexity=complexity,
                target=str(raw.get("target") or ""),
                instructions=str(raw.get("instructions") or "")))
    if not subtasks:
        subtasks = [Subtask(id="s1", title="Whole task", role="coder",
                            complexity="standard", target="",
                            instructions=task)]
        notes = (notes + " [planner output unparseable; "
                 "fell back to a single subtask]").strip()
    return subtasks, notes


_FILE_BLOCK = re.compile(
    r'<<<FILE\s+path="([^"]+)">>>\s*\n(.*?)\n<<<END FILE>>>', re.DOTALL)


def parse_files(text: str, default_target: str = "") -> dict[str, str]:
    """Extract proposed files from a coder reply."""
    files: dict[str, str] = {}
    for path, content in _FILE_BLOCK.findall(text):
        safe = sanitise_relpath(path)
        if safe:
            files[safe] = content
    if not files and default_target:
        body = text.strip()
        body = re.sub(r"^```[a-zA-Z]*\n", "", body)
        body = re.sub(r"\n```$", "", body)
        safe = sanitise_relpath(default_target)
        if safe and body:
            files[safe] = body
    return files


def parse_review(text: str) -> dict:
    obj = _extract_json(text)
    if not obj:
        return {"verdict": "unparsed", "score": None, "issues":
                ["reviewer output was not valid JSON"], "lessons": []}
    try:
        score = int(obj.get("score"))
    except (TypeError, ValueError):
        score = None
    return {
        "verdict": str(obj.get("verdict", "unparsed")),
        "score": score,
        "issues": [str(i) for i in (obj.get("issues") or [])],
        "lessons": [str(x) for x in (obj.get("lessons") or [])][:3],
    }


class Orchestrator:
    def __init__(self, provider, workspace: Path, *,
                 review_provider=None, use_lessons: bool = True):
        self.provider = provider
        self.review_provider = review_provider or provider
        self.workspace = Path(workspace)
        self.use_lessons = use_lessons

    # -- one agent call, ledgered either way -------------------------
    def _call(self, ledger: Ledger, run_id: str, role: str, provider,
              system: str, user: str, model: str,
              max_tokens: int, temperature: float = 0.0) -> ChatResult:
        try:
            result = provider.chat(system, user, model,
                                   max_tokens=max_tokens,
                                   temperature=temperature)
        except ProviderError as exc:
            ledger.record(run_id=run_id, role=role, provider=provider.name,
                          model_requested=model, model_served=None,
                          prompt_tokens=None, completion_tokens=None,
                          latency_s=0.0, status="error", detail=str(exc)[:300])
            raise
        ledger.record(run_id=run_id, role=role, provider=provider.name,
                      model_requested=model,
                      model_served=result.model_served,
                      prompt_tokens=result.prompt_tokens,
                      completion_tokens=result.completion_tokens,
                      latency_s=result.latency_s, status="ok",
                      retries=result.retries)
        return result

    # -- the run ------------------------------------------------------
    def run(self, task: str, *, mode: str = "parallel",
            target: Path | None = None, approve_all: bool = False,
            interactive: bool = False) -> RunResult:
        if mode not in ("parallel", "sequential"):
            raise ValueError(f"unknown mode: {mode}")
        t_start = time.time()
        run_id = (time.strftime("%Y%m%d-%H%M%S") + f"-{mode}-"
                  + uuid.uuid4().hex[:6])
        run_dir = self.workspace / "runs" / run_id
        (run_dir / "out").mkdir(parents=True, exist_ok=True)
        ledger = Ledger(run_dir)
        audit = AuditLog(run_dir)
        board = Blackboard(run_dir)
        audit.log("run_started", mode=mode, task=task[:200])

        lessons = load_lessons(self.workspace) if self.use_lessons else []
        lesson_block = ""
        if lessons:
            lesson_block = ("\nLessons from earlier runs:\n"
                            + "\n".join(f"- {x}" for x in lessons))

        # 1. plan
        plan_model = route_model(self.provider.name, "planner")
        plan_res = self._call(
            ledger, run_id, "planner", self.provider, PLANNER_SYSTEM,
            f"Task:\n{task}{lesson_block}", plan_model, max_tokens=1500)
        subtasks, plan_notes = parse_plan(plan_res.text, task)
        board.publish("planner", "plan",
                      json.dumps([s.__dict__ for s in subtasks]))

        # 2. workers
        def do_worker(sub: Subtask) -> dict[str, str]:
            model = route_model(self.provider.name, sub.role, sub.complexity)
            board_view = board.snapshot()
            user = (f"Overall task:\n{task}\n\nYour subtask: {sub.title}\n"
                    f"Target file: {sub.target}\n"
                    f"Instructions: {sub.instructions}\n\n"
                    f"Shared blackboard so far:\n{board_view}")
            res = self._call(ledger, run_id, sub.role, self.provider,
                             CODER_SYSTEM, user, model,
                             max_tokens=3000, temperature=0.2)
            files = parse_files(res.text, sub.target)
            board.publish(sub.id, "output",
                          f"produced: {', '.join(files) or '(no files)'}")
            return files

        files: dict[str, str] = {}
        if mode == "parallel":
            with ThreadPoolExecutor(max_workers=max(1, len(subtasks))) as pool:
                for produced in pool.map(do_worker, subtasks):
                    files.update(produced)
        else:
            for sub in subtasks:
                files.update(do_worker(sub))

        # stage proposals in the sandbox
        for rel, content in files.items():
            dest = run_dir / "out" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        audit.log("proposals_staged", files=sorted(files))

        # 3. review
        review_model = route_model(self.review_provider.name, "reviewer")
        review_input = [f"Task:\n{task}", "\nProduced files:"]
        for rel, content in sorted(files.items()):
            review_input.append(f"\n--- {rel} ---\n{content[:4000]}")
        review_res = self._call(
            ledger, run_id, "reviewer", self.review_provider,
            REVIEWER_SYSTEM, "\n".join(review_input)[:24000],
            review_model, max_tokens=1500)
        review = parse_review(review_res.text)
        if review["lessons"]:
            append_lessons(self.workspace, review["lessons"], run_id)
            audit.log("lessons_recorded", lessons=review["lessons"])

        # 4. gate
        decisions: dict[str, str] = {}
        if target is not None:
            decisions = apply_proposals(
                files, Path(target), approve_all=approve_all,
                interactive=interactive, audit=audit)

        wall_s = time.time() - t_start
        totals = ledger.totals()
        result = RunResult(run_id=run_id, run_dir=run_dir, mode=mode,
                           wall_s=wall_s, files=files, review=review,
                           totals=totals, gate_decisions=decisions,
                           plan_notes=plan_notes)
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": run_id, "mode": mode, "task": task,
            "wall_s": round(wall_s, 3), "files": sorted(files),
            "review": review, "totals": totals,
            "gate_decisions": decisions, "plan_notes": plan_notes,
        }, indent=2), encoding="utf-8")
        audit.log("run_finished", wall_s=round(wall_s, 3))
        from .report import render_report
        (run_dir / "report.md").write_text(
            render_report(run_dir), encoding="utf-8")
        return result
