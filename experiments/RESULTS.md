# Bench results — parallel vs sequential

Generated 2026-11-11T01:14:50+0000; 2 repetition(s) per cell, fresh workspace per run, cross-run lessons disabled for fairness.

| Task | Mode | Runs ok | Wall mean s | Wall min–max s | Wall stdev | Check score mean | Prompt tok (mean) | Completion tok (mean) | Retries |
|---|---|---|---|---|---|---|---|---|---|
| utils-trio | sequential | 2 | 10.093 | 9.491–10.694 | 0.851 | 1.0 | 4948.5 | 3237 | 0 |
| utils-trio | parallel | 2 | 15.566 | 8.009–23.122 | 10.687 | 1.0 | 5451.5 | 3758.5 | 3 |
| **utils-trio** | **speedup (parallel vs sequential)** | **0.648×** | | | | | | | |
| docs-trio | sequential | 2 | 28.105 | 21.968–34.243 | 8.68 | 0.0 | 4216.5 | 2233 | 10 |
| docs-trio | parallel | 2 | 18.444 | 14.602–22.285 | 5.433 | 0.0 | 4214 | 2516.5 | 11 |
| **docs-trio** | **speedup (parallel vs sequential)** | **1.524×** | | | | | | | |

Check score is the deterministic sample check (produced tests passing / required spec items present) — a proxy for quality, reported with the reviewer scores in results.json, not instead of them.

Caveats: both modes share one free-tier account, so parallel workers contend for the same per-minute token quota and can be rate-limited in ways sequential workers are not; retries are counted in the ledger and above. Actual spend: $0 (free tier). Cost figures in results.json are list-price estimates.

## Measurement notes (appended by hand, 2026-11-10)

This table is **round 1** (Groq free tier, gpt-oss-120b/20b), the only
complete round. Three things a reader must know:

1. **The docs-trio check scores (0.0) are an instrument bug, not a
   result.** In all eight round-1 runs the planner placed the files
   under a subdirectory (`docs/`, `utils/`) and the docs check only
   looked at the output root. The files existed with the required
   names and content (verified by direct listing and grep before the
   workspaces were rotated). The check now searches recursively and
   is regression-tested (`tests/test_samples.py`); the planner prompt
   also now instructs exact target paths. The docs **wall times,
   tokens, and retries above are valid**; only that one column is
   void. Round 1's raw data is in `results.json`.
2. **Round 2 (Groq, fixed instrument) died on quota after 1 of 8
   runs** (`round2-groq-attempt-results.json`): the account's shared
   200,000 tokens/day free-tier cap was already exhausted by other
   work on the same key. The one completed run (utils-trio,
   sequential) scored check 1.00 (4/4 tests).
3. **Round 3 (Gemini free tier) died on quota after 1 of 8 runs**
   (`round3-gemini-attempt-results.json`): that tier allows 20
   requests/day for the served model, likewise already consumed. Its
   one completed run (utils-trio, sequential) scored check 1.00 with
   **11/11 produced tests passing** — the strongest spec compliance
   seen (the task asks for ≥3 tests per module; round-1 Groq runs
   produced 3–4 tests total).

**What round 1 supports saying:** on the code task, parallel mode was
*slower* on mean wall time (0.648×) — one of its two runs absorbed
rate-limit retries while sequential runs absorbed none. On the docs
task, parallel was faster (1.524×) despite *more* retries. With n=2
per cell and a shared, contended free-tier quota, both numbers are
"what happened today on this account", not laws — which is precisely
why the bench exists and why it reports spread and retries next to
every mean. Re-run `swarmreckon bench` after a quota reset for a
cleaner read.
