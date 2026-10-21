"""Bounded tool-calling loop. Tools are plain callables bound server-side to the requesting principal."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .numbers import unverified_numbers
from .providers import AgentProvider, ProviderError

SYSTEM_PROMPT = """You are the Nodal Accord assistant inside a supply-shortage resolution workbench (synthetic demo data).
Rules you must follow:
- Use the tools to read facts. Answer only from tool results. If something is not in a tool result, say you don't know.
- Never do arithmetic or estimate numbers yourself. Quote numbers exactly as the tools return them, with their units.
- Always cite the case_id and run_id you used, e.g. "(CASE-000004, RUN-...)".
- You cannot send, accept, approve or change offers or agreements. Humans do that in the Resolve tab. Say so if asked.
- request_scenario only queues a solver job; results appear later in the Simulate tab. Use it at most once.
- Solver statuses mean: OPTIMAL = proven best; FEASIBLE_WITH_GAP = valid plan, not proven best; INFEASIBLE = no plan
  meets the hard constraints; TIME_LIMIT = no plan found in time. Never call a FEASIBLE_WITH_GAP plan optimal.
- Shortage exposure is a scenario proxy, not a real loss. Data is synthetic; do not present results as customer savings.
- Be concise: short paragraphs or bullets, plain language for a planner."""

ToolFn = Callable[[dict[str, Any]], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class AgentOutcome:
    status: str  # COMPLETED | STOPPED | FAILED
    answer: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    finish_reason: str = ""
    rounds: int = 0
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


def run_agent(provider: AgentProvider, question: str, tools: list[Tool], *, context: str = "", max_rounds: int = 4,
              max_tokens: int = 900, max_tool_chars: int = 6000,
              redact: Callable[[Any], tuple[Any, list[str]]] | None = None) -> AgentOutcome:
    """Runs at most `max_rounds` model calls. `redact` is applied to every tool output before the model sees it."""
    by_name = {t.name: t for t in tools}
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": question})
    trace: list[dict[str, Any]] = []
    outputs: list[Any] = []
    usage: dict[str, int] = {}
    for rnd in range(1, max_rounds + 1):
        # On the last round, offer no tools so the model must answer.
        offered = [t.schema() for t in tools] if rnd < max_rounds else []
        try:
            res = provider.chat(messages, offered, max_tokens=max_tokens)
        except ProviderError as exc:
            return AgentOutcome("FAILED", "", trace, [], "error", rnd, str(exc), usage)
        for k, v in (res.usage or {}).items():
            if isinstance(v, int):
                usage[k] = usage.get(k, 0) + v
        msg = res.message
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = (msg.get("content") or "").strip()
            status = "COMPLETED"
            if res.finish_reason in ("length",):
                answer += "\n\n[Answer cut off at the length limit.]"
            if res.finish_reason in ("insufficient_system_resource", "content_filter", "aborted"):
                status = "FAILED"
            return AgentOutcome(status, answer, trace, unverified_numbers(answer, outputs), res.finish_reason, rnd, None, usage)
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn_name = (call.get("function") or {}).get("name", "")
            raw_args = (call.get("function") or {}).get("arguments") or "{}"
            started = time.perf_counter()
            entry: dict[str, Any] = {"tool": fn_name, "arguments": raw_args[:500]}
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
                tool = by_name.get(fn_name)
                if tool is None:
                    result: Any = {"error": f"unknown tool {fn_name}"}
                    entry["ok"] = False
                else:
                    result = tool.fn(args)
                    entry["ok"] = not (isinstance(result, dict) and "error" in result)
            except (json.JSONDecodeError, ValueError) as exc:
                result = {"error": f"invalid arguments: {exc}"}
                entry["ok"] = False
            except Exception as exc:  # a tool bug must not kill the request or leak internals
                result = {"error": f"tool failed: {type(exc).__name__}"}
                entry["ok"] = False
            if redact is not None:
                result, removed = redact(result)
                if removed:
                    entry["redacted_fields"] = removed
            text = json.dumps(result, default=str)
            if len(text) > max_tool_chars:
                text = text[:max_tool_chars] + '..."[truncated]"'
                entry["truncated"] = True
            outputs.append(result)
            entry["output_chars"] = len(text)
            entry["ms"] = round((time.perf_counter() - started) * 1000, 1)
            trace.append(entry)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text})
    return AgentOutcome("STOPPED", "The assistant reached its step limit before answering. Try a narrower question.",
                        trace, [], "max_rounds", max_rounds, None, usage)
