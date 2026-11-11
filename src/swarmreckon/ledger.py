"""The evidence ledger: one JSONL record per agent call, per run.

Every call the orchestrator makes — planner, coder, reviewer,
success or failure — is appended with the role, the provider, the
model requested and the model actually served, token usage, latency,
retry count, and a list-price cost estimate. Actual spend for the
free-tier providers used by default is $0; the estimate exists so
runs can be compared against what the same tokens would cost at
published list prices (see prices.json for the dated price table).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_PRICES_FILE = Path(__file__).with_name("prices.json")


def load_prices() -> dict:
    try:
        return json.loads(_PRICES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"models": {}}


def estimate_cost_usd(model: str, prompt_tokens: int | None,
                      completion_tokens: int | None,
                      prices: dict | None = None) -> float | None:
    """List-price estimate in USD, or None if the model is unpriced."""
    table = (prices or load_prices()).get("models", {})
    rate = table.get(model)
    if rate is None or prompt_tokens is None or completion_tokens is None:
        return None
    return (prompt_tokens * rate["input_per_1m"]
            + completion_tokens * rate["output_per_1m"]) / 1_000_000.0


class Ledger:
    """Append-only per-run ledger of agent calls."""

    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "ledger.jsonl"
        self.path.touch(exist_ok=True)
        self.records: list[dict] = []
        self._prices = load_prices()

    def record(self, *, run_id: str, role: str, provider: str,
               model_requested: str, model_served: str | None,
               prompt_tokens: int | None, completion_tokens: int | None,
               latency_s: float, status: str, retries: int = 0,
               detail: str = "") -> dict:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_id,
            "role": role,
            "provider": provider,
            "model_requested": model_requested,
            "model_served": model_served,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_s": round(latency_s, 3),
            "retries": retries,
            "status": status,
            "cost_estimate_usd": estimate_cost_usd(
                model_served or model_requested, prompt_tokens,
                completion_tokens, self._prices),
            "detail": detail,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        self.records.append(rec)
        return rec

    def totals(self) -> dict:
        ok = [r for r in self.records if r["status"] == "ok"]
        return {
            "calls": len(self.records),
            "calls_ok": len(ok),
            "calls_failed": len(self.records) - len(ok),
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in ok),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in ok),
            "retries": sum(r["retries"] for r in self.records),
            "cost_estimate_usd": round(
                sum(r["cost_estimate_usd"] or 0.0 for r in ok), 6),
        }


def read_ledger(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "ledger.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
