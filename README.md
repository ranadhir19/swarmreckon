# swarmreckon

**A parallel multi-agent runner that grades itself.**

Plenty of tools will run a swarm of agents at your task and quote you
an agent count. swarmreckon does the unfashionable other thing: it
runs the same task **in parallel and sequentially** — same planner,
same worker prompts, same models, only the concurrency differs — and
reports wall-clock time with spread, token totals, retries, and a
deterministic quality check for both. Then it shows you the ledger.

```bash
pip install -e .          # or just use PYTHONPATH=src
swarmreckon demo          # offline end-to-end demo, no keys, no network
swarmreckon run --task "Write a slugify module with tests"
swarmreckon bench         # the parallel-vs-sequential comparison
```

Pure Python standard library, Python ≥ 3.10, local-first. Default
provider is Groq's free tier; a Gemini free-tier provider and a
deterministic fake provider (tests/demo) are built in.

## Watch it built

Built by the presenter of **[The Architect's AI Workshop](https://www.youtube.com/@ArchitectsAIWorkshop)** — *first principles on the whiteboard, built live in the editor, measured honestly.*

## How a run works

1. **Planner** decomposes the task into 2–4 independent subtasks,
   each tagged with a complexity grade.
2. **Workers** (coder role in v1) execute the subtasks —
   concurrently in `parallel` mode, one at a time in `sequential`
   mode. A **router** sends simple subtasks to a small free model
   and standard/complex ones to a large free model.
3. **Shared memory**: a run-scoped blackboard (append-only JSONL)
   every worker reads and publishes to, plus a cross-run **lessons
   log** — the reviewer extracts transferable lessons from each run
   and the planner reads them next time.
4. **Reviewer** reads the produced files, scores them, and lists
   issues and lessons.
5. **Approval gate**: worker output is a *proposal*, staged in the
   run's `out/` directory. Applying it to a real directory
   (`--target`) requires a per-file human decision; every decision
   is written to the run's audit log, and unsafe paths (absolute,
   `..` escapes) are refused outright.

Every agent call lands in the run's **evidence ledger**
(`ledger.jsonl`): role, provider, model requested vs actually
served, prompt/completion tokens, latency, retries, status, and a
list-price cost estimate. Actual spend on the free tiers is $0; the
estimate (prices in `src/swarmreckon/prices.json`, dated) exists so
runs can be compared with what the same tokens would cost at list.

## Measured results — first bench, failures included

`swarmreckon bench`, 2 sample tasks × 2 modes × 2 repetitions, fresh
workspace per run, lessons disabled for fairness. Full data:
[experiments/RESULTS.md](experiments/RESULTS.md) and
`experiments/results.json`. Groq free tier (gpt-oss-120b planner/
coders/reviewer, gpt-oss-20b for simple subtasks), 2026-11-10.

| Task | Sequential wall (mean ± sd) | Parallel wall (mean ± sd) | Speedup | Check score |
|---|---|---|---|---|
| utils-trio (3 modules + tests) | 10.1s ± 0.9 | 15.6s ± 10.7 | **0.65× — parallel was slower** | 1.00 both modes |
| docs-trio (3 docs from a spec) | 28.1s ± 8.7 | 18.4s ± 5.4 | **1.52×** | see note |

What actually happened, unvarnished:

- **Parallel lost on the code task.** One of its two runs absorbed
  the free tier's per-minute rate limiting (retries are in the
  ledger); sequential runs absorbed none. On a shared free-tier
  quota, concurrency contends with itself — the swarm's worst enemy
  was the token budget, not coordination.
- **Parallel won on the docs task** despite *more* retries (11 vs
  10): three independent documents overlap cleanly.
- **The docs check column in the raw table reads 0.0 — that is an
  instrument bug, disclosed in the results file.** The planner
  nested the files under `docs/`; the check didn't look there. The
  files existed with the required content. The check now searches
  recursively, is regression-tested, and the planner is instructed
  to use task-named paths exactly.
- **Two follow-up bench rounds died on quota** (also in the results
  file): Groq's shared 200k tokens/day cap and Gemini's
  20 requests/day cap were both already consumed by other work on
  the same keys. The one Gemini run that completed produced the
  best spec compliance of the day (11/11 produced tests passing).
- Reviewer scores (a model's opinion, kept separate from the
  deterministic checks): utils runs 4–6/10 ("revise" — the produced
  test counts fell short of the ≥3-per-file spec even though the
  tests that existed all passed); docs runs 9–10/10.

n=2 per cell, one account, one evening: these are *what happened*
numbers, not laws. The tool's claim is not that parallel wins — it
is that you should never have to take a swarm's word for it.

## Providers and keys

- **Groq (default).** Authentication rides the registered
  `custom.groq` connector's credential-surrogate exchange: the code
  never reads or stores a key, and the credential is attached only
  to requests to `api.groq.com`. To use swarmreckon outside that
  environment, pass any object with the `chat()` signature of
  `providers.FakeProvider` to `Orchestrator` — the provider seam is
  the extension point.
- **Gemini (opt-in).** `--provider gemini` or
  `--cross-provider-review`. The AI Studio free tier may use
  submitted content to improve Google's products — route **public
  material only** through it. The served model is recorded from the
  response (the `gemini-3.5-flash` alias currently serves as
  `gemini-3.6-flash`), because aliases lie and ledgers shouldn't.
- **Fake.** Deterministic and offline; drives the tests and `demo`.

One provider gotcha the ledger will show you if you hit it: free
tiers rate-limit per minute *and* per day, and parallel workers
share both. swarmreckon honours provider-stated retry delays and
counts every retry instead of hiding them.

## Run layout

```
.swarmreckon/
  runs/<run-id>/
    ledger.jsonl    every agent call, with tokens and cost estimate
    audit.jsonl     gate decisions and lifecycle events
    memory.jsonl    the run's blackboard
    out/            proposed files (the sandbox)
    report.md       rendered from the records above
    run.json        machine-readable run summary
  memory/lessons.jsonl   cross-run lessons the planner reads
```

## Scope and non-goals

v1 is deliberately small: one worker role that writes files
(coder), a planner, a reviewer. It is not a persistent memory
product (that's a sibling tool's job), not a security scanner, and
not a routing-policy research platform. The bench executes
model-written tests locally as its quality check — run it on tasks
and machines where that is appropriate.

## Validation

`python3 validate.py` — import/compile, the full test suite (32
tests), an offline demo smoke test, a bench-mechanics smoke test, a
reference-integrity scan, and a banned-name check. All stages must
pass.

## License

MIT. Author: Ranadhir Ghosh.
