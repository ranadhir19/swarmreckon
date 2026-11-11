# Bench results — parallel vs sequential

Generated 2026-11-11T01:24:04+0000; 2 repetition(s) per cell, fresh workspace per run, cross-run lessons disabled for fairness.

| Task | Mode | Runs ok | Wall mean s | Wall min–max s | Wall stdev | Check score mean | Prompt tok (mean) | Completion tok (mean) | Retries |
|---|---|---|---|---|---|---|---|---|---|
| utils-trio | sequential | 1 | 46.375 | 46.375–46.375 | 0.0 | 1.0 | 4052 | 1383 | 3 |
| utils-trio | parallel | 0 | None | None–None | None | None | None | None | 0 |
| **utils-trio** | **speedup (parallel vs sequential)** | **None×** | | | | | | | |
| docs-trio | sequential | 0 | None | None–None | None | None | None | None | 0 |
| docs-trio | parallel | 0 | None | None–None | None | None | None | None | 0 |
| **docs-trio** | **speedup (parallel vs sequential)** | **None×** | | | | | | | |

Check score is the deterministic sample check (produced tests passing / required spec items present) — a proxy for quality, reported with the reviewer scores in results.json, not instead of them.

Caveats: both modes share one free-tier account, so parallel workers contend for the same per-minute token quota and can be rate-limited in ways sequential workers are not; retries are counted in the ledger and above. Actual spend: $0 (free tier). Cost figures in results.json are list-price estimates.
