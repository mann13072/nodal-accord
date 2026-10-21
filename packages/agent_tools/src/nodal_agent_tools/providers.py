"""Chat providers behind one small interface (OpenAI-style messages and tool calls).

DeepSeekProvider talks to DeepSeek's OpenAI-compatible endpoint. The API key is read from the environment at
construction and never placed in error messages, logs or results.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Sanitised provider failure (no headers, no key material)."""


@dataclass
class ChatResult:
    message: dict[str, Any]  # assistant message: {"role": "assistant", "content": str|None, "tool_calls": [...]?}
    finish_reason: str
    usage: dict[str, Any] = field(default_factory=dict)


class AgentProvider(Protocol):
    name: str
    model: str

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, max_tokens: int) -> ChatResult: ...


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, api_key: str, model: str = "deepseek-flash", base_url: str = "https://api.deepseek.com", timeout: float = 60.0):
        if not api_key:
            raise ValueError("missing API key")
        self._key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout

    def __repr__(self) -> str:  # never expose the key
        return f"DeepSeekProvider(model={self.model!r})"

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, max_tokens: int) -> ChatResult:
        import httpx  # lazy: a missing dependency disables AI instead of breaking the app

        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                "thinking": {"type": "disabled"}, "temperature": 0.2, "max_tokens": max_tokens, "stream": False}
        try:
            r = httpx.post(self._url, json=body, timeout=self._timeout,
                           headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error contacting {self.name}: {type(exc).__name__}") from None
        if r.status_code != 200:
            detail = ""
            try:
                detail = str(r.json().get("error", {}).get("message", ""))[:200]
            except Exception:
                detail = r.text[:200]
            raise ProviderError(f"{self.name} returned HTTP {r.status_code}: {detail}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        out = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        return ChatResult(out, choice.get("finish_reason") or "stop", data.get("usage") or {})


class ScriptedProvider:
    """Deterministic provider for tests: returns queued responses and records every payload it was sent."""

    name = "scripted"
    model = "scripted-test"

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []

    def chat(self, messages, tools, *, max_tokens):
        import copy
        self.sent.append({"messages": copy.deepcopy(messages), "tools": tools, "max_tokens": max_tokens})
        if not self.responses:
            return ChatResult({"role": "assistant", "content": "No further scripted response."}, "stop")
        r = self.responses.pop(0)
        return ChatResult(r["message"], r.get("finish_reason", "tool_calls" if r["message"].get("tool_calls") else "stop"))


def provider_from_env() -> AgentProvider | None:
    """Returns the configured provider, or None when AI is disabled (no key)."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key or os.environ.get("NODAL_AI_PROVIDER", "deepseek").lower() in ("none", "off", "disabled"):
        return None
    try:
        return DeepSeekProvider(key, model=os.environ.get("NODAL_AI_MODEL", "deepseek-flash"),
                                base_url=os.environ.get("NODAL_AI_BASE_URL", "https://api.deepseek.com"))
    except Exception:
        return None
