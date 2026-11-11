"""Model providers for swarmreckon.

Three providers ship in v1:

- ``GroqProvider`` — Groq's free tier. Authentication rides the
  registered ``custom.groq`` connector's credential-surrogate
  exchange: this code never reads, stores, or prints an API key; the
  surrogate attaches the credential to requests addressed to
  ``api.groq.com`` only. Outside that environment, construct any
  class with the same ``chat()`` signature and pass it to the
  orchestrator instead.
- ``GeminiProvider`` — Google AI Studio's free tier, same surrogate
  pattern via ``custom.google-ai-studio``. Opt-in only: the free
  tier's terms let Google use submitted content to improve its
  products, so never route private material through it.
- ``FakeProvider`` — a deterministic, offline provider used by the
  test suite and the ``demo`` command. It returns canned planner,
  coder, and reviewer responses keyed off the role named in the
  system prompt, so the full pipeline can be exercised with no
  network and no keys.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

_CRED_BIN = "/opt/muse/skills/custom-connector-setup/bin"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class ProviderError(RuntimeError):
    """A provider call failed in a way the caller should hear about."""


@dataclass
class ChatResult:
    text: str
    model_served: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float
    retries: int = 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):  # noqa: D102 - refusal is the point
        raise ProviderError("redirect refused; verify the endpoint")


def _surrogate_fns():
    if _CRED_BIN not in sys.path:
        sys.path.insert(0, _CRED_BIN)
    try:
        from dynamic_credentials import add_surrogate_to_request, read_json_response
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ProviderError(
            "credential surrogate not available in this environment; "
            "run inside the Muse connector environment or use "
            "--provider fake") from exc
    return add_surrogate_to_request, read_json_response


def _post_json(url: str, payload: dict, connector: str, host: str,
               timeout: int = 180) -> dict:
    add_surrogate, read_json = _surrogate_fns()
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _UA,
                 "Accept": "application/json"})
    add_surrogate(request, connector, allowed_hosts=[host])
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return read_json(response)


_RETRY_IN = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(\d+(?:\.\d+)?)s")


def stated_retry_delay(body: str, attempt: int) -> float:
    """How long to wait before retrying, honouring the provider's own
    stated delay when the error body gives one ("retry in 46s",
    "retry in 6h38m16s"), capped at 90s — a multi-hour daily-cap delay
    is a failure, not a wait. Falls back to exponential backoff."""
    match = _RETRY_IN.search(body or "")
    if match:
        hours = float(match.group(1) or 0)
        minutes = float(match.group(2) or 0)
        seconds = float(match.group(3))
        return min(90.0, hours * 3600 + minutes * 60 + seconds + 1.0)
    return min(30.0, 2.0 * (2 ** attempt))


def _with_retries(fn, attempts: int = 4):
    """Run fn(), retrying transient HTTP failures with backoff.

    Returns (result, retries_used). Rate limits (HTTP 429) are a fact
    of life on free tiers; they are retried, counted, and surfaced in
    the ledger rather than hidden.
    """
    retries = 0
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn(), retries
        except urllib.error.HTTPError as exc:
            last = exc
            body = ""
            try:
                body = exc.read()[:400].decode("utf-8", "replace")
            except Exception:
                pass
            if exc.code in (429, 500, 502, 503) and attempt < attempts - 1:
                retries += 1
                time.sleep(stated_retry_delay(body, attempt))
                continue
            raise ProviderError(f"HTTP {exc.code}: {body[:200]}") from exc
        except urllib.error.URLError as exc:
            last = exc
            if attempt < attempts - 1:
                retries += 1
                time.sleep(min(30.0, 2.0 * (2 ** attempt)))
                continue
            raise ProviderError(f"network error: {exc}") from exc
    raise ProviderError(f"provider call failed after retries: {last}")


class GroqProvider:
    """Groq free tier, OpenAI-compatible chat completions."""

    name = "groq"
    BASE = "https://api.groq.com/openai/v1"

    def chat(self, system: str, user: str, model: str,
             max_tokens: int = 2000, temperature: float = 0.0) -> ChatResult:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        t0 = time.time()

        def once():
            return _post_json(self.BASE + "/chat/completions", payload,
                              "custom.groq", "api.groq.com")

        result, retries = _with_retries(once)
        choice = (result.get("choices") or [{}])[0]
        usage = result.get("usage") or {}
        return ChatResult(
            text=(choice.get("message") or {}).get("content") or "",
            model_served=result.get("model") or model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_s=time.time() - t0,
            retries=retries)


class GeminiProvider:
    """Google AI Studio free tier via the Interactions API.

    The classic generateContent endpoint 404s for this account class
    ("no longer available to new users"); the Interactions API is the
    working route, and the response's own ``model`` field — not the
    requested alias — is what gets recorded as the served model.
    """

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def chat(self, system: str, user: str, model: str,
             max_tokens: int = 2000, temperature: float = 0.0) -> ChatResult:
        model_id = model if model.startswith("models/") else "models/" + model
        payload = {"model": model_id, "input": system + "\n\n" + user}
        t0 = time.time()

        def once():
            return _post_json(self.BASE + "/interactions", payload,
                              "custom.google-ai-studio",
                              "generativelanguage.googleapis.com")

        result, retries = _with_retries(once)
        text = ""
        for step in result.get("steps") or []:
            if step.get("type") == "model_output":
                for part in step.get("content") or []:
                    if part.get("type") == "text":
                        text += part.get("text", "")
        usage = result.get("usage") or {}
        return ChatResult(
            text=text,
            model_served=result.get("model") or model,
            prompt_tokens=usage.get("total_input_tokens"),
            completion_tokens=usage.get("total_output_tokens"),
            latency_s=time.time() - t0,
            retries=retries)


class FakeProvider:
    """Deterministic offline provider for tests and the demo.

    Responses are keyed off the role marker the orchestrator puts in
    each system prompt (PLANNER / CODER / REVIEWER), so the whole
    pipeline — decomposition, parallel workers, review, ledger,
    gates — runs end to end with no network.
    """

    name = "fake"

    def chat(self, system: str, user: str, model: str,
             max_tokens: int = 2000, temperature: float = 0.0) -> ChatResult:
        t0 = time.time()
        if "ROLE: PLANNER" in system:
            text = json.dumps({"subtasks": [
                {"id": "s1", "title": "Alpha module", "role": "coder",
                 "complexity": "simple", "target": "alpha.py",
                 "instructions": "Write alpha.py defining VALUE = 1."},
                {"id": "s2", "title": "Beta module", "role": "coder",
                 "complexity": "simple", "target": "beta.py",
                 "instructions": "Write beta.py defining VALUE = 2."},
            ], "notes": "fake plan"})
        elif "ROLE: CODER" in system:
            target = "out.py"
            for line in user.splitlines():
                if line.startswith("Target file:"):
                    target = line.split(":", 1)[1].strip()
                    break
            text = (f'<<<FILE path="{target}">>>\n'
                    f'"""Fake-generated module for {target}."""\n\n'
                    f"VALUE = 1\n<<<END FILE>>>\n")
        elif "ROLE: REVIEWER" in system:
            text = json.dumps({
                "verdict": "pass", "score": 8, "issues": [],
                "lessons": ["Keep subtasks independent so workers "
                            "never wait on each other."]})
        else:  # pragma: no cover - defensive
            text = ""
        return ChatResult(
            text=text, model_served=model,
            prompt_tokens=max(1, len(user) // 4),
            completion_tokens=max(1, len(text) // 4),
            latency_s=time.time() - t0, retries=0)
