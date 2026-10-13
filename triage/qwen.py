"""Client for Qwen's own chat completions endpoint. Standard library only, no model SDK.

POST <QWEN_BASE_URL>/chat/completions, for example base URL https://<host>/compatible-mode/v1.
Thinking is a per-request switch: enable_thinking true or false, plus an optional thinking_budget.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class QwenError(Exception):
    """The request failed (network, timeout, HTTP error, or an error body). Never contains the API key."""


@dataclass(frozen=True)
class Reply:
    text: str
    finish_reason: str | None
    prompt_tokens: int
    output_tokens: int  # includes reasoning tokens, which are billed as output
    reasoning_tokens: int
    seconds: float


def thinking_params(mode: str, budget: int = 256) -> dict:
    """on: provider thinking. off: no reasoning tokens. budget: thinking capped at `budget` tokens."""
    if mode == "off":
        return {"enable_thinking": False}
    if mode == "budget":
        return {"enable_thinking": True, "thinking_budget": budget}
    return {"enable_thinking": True}


class QwenClient:
    def __init__(self, api_key: str, base_url: str, timeout: float = 90.0):
        self.api_key, self.base_url, self.timeout = api_key, base_url.rstrip("/"), timeout

    def complete(self, model: str, system: str, user: str, max_tokens: int = 2000,
                 thinking: dict | None = None) -> Reply:
        if not self.base_url:
            raise QwenError("QWEN_BASE_URL is not set")
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **(thinking or {})}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise QwenError(f"HTTP {exc.code}: {exc.read(200).decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise QwenError(f"{type(exc).__name__}: {exc}"[:200]) from None
        if "error" in data or not data.get("choices"):
            raise QwenError(f"error response: {json.dumps(data.get('error', data))[:200]}")
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return Reply(
            text=(choice.get("message") or {}).get("content") or "",
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            reasoning_tokens=int(details.get("reasoning_tokens", 0)),
            seconds=time.monotonic() - started,
        )
