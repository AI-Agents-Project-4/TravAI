"""How the planner calls Claude. One interface, two ways to reach the model.

- `ClaudeCLI` runs `claude -p` (Claude Code in headless mode), like the research
  agent, so it uses the team's Claude plan and needs no API key.
- `AnthropicAPI` uses the Anthropic SDK with an API key held only in the backend
  (for the eval in GitHub Actions, where `claude -p` can't log in).

Both return structured JSON checked against a schema, plus token use and cost.
Tests use a fake that returns canned JSON; nothing here runs in CI.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from decimal import Decimal
from typing import Any, Protocol

from app.agents.planner.types import ModelCallLog

# $ per million tokens: input, output, cache read, cache write (5-minute TTL).
# From the Anthropic pricing table (2026-11). Used only for the SDK path; the CLI
# reports its own cost.
PRICES: dict[str, tuple[str, str, str, str]] = {
    "claude-opus-5-5": ("4.00", "20.00", "0.20", "5.00"),
    "claude-sonnet-5-5": ("2.00", "10.00", "0.10", "2.50"),
    "claude-haiku-5-5": ("0.10", "0.50", "0.01", "0.125"),
}


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


class LLM(Protocol):
    model: str

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, Any], *, agent: str
    ) -> tuple[dict[str, Any], ModelCallLog]: ...


def api_cost(model: str, inp: int, out: int, cache_read: int, cache_write: int) -> Decimal:
    rates = PRICES.get(model)
    if rates is None:
        return Decimal(0)
    p_in, p_out, p_read, p_write = (Decimal(r) for r in rates)
    total = inp * p_in + out * p_out + cache_read * p_read + cache_write * p_write
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class ClaudeCLI:
    """`claude -p` with tools off, no session saved, and a per-call spend cap."""

    def __init__(self, model: str, timeout: int = 300, max_budget_usd: float = 1.0):
        self.model = model
        self.timeout = timeout
        self.max_budget_usd = max_budget_usd

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, Any], *, agent: str
    ) -> tuple[dict[str, Any], ModelCallLog]:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--no-session-persistence",
            "--max-budget-usd",
            str(self.max_budget_usd),
            "--tools",
            "",
            "--model",
            self.model,
        ]
        # The prompt goes on stdin: a long option list doesn't fit on a Windows command line.
        text = f"{system}\n\n{prompt}"
        try:
            # Neutral working directory, so the CLI doesn't load this repo's CLAUDE.md.
            with tempfile.TemporaryDirectory() as cwd:
                proc = subprocess.run(
                    cmd,
                    input=text,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    cwd=cwd,
                )
        except FileNotFoundError as exc:
            raise LLMError("The `claude` CLI isn't installed on this machine.") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"`claude -p` took longer than {self.timeout}s.") from exc
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"`claude -p` gave non-JSON output (exit {proc.returncode}): "
                f"{proc.stdout[:200]} {proc.stderr[:200]}"
            ) from exc
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        cost = data.get("total_cost_usd")
        log = ModelCallLog(
            agent=agent,
            model=self.model,
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_write_tokens=_int(usage.get("cache_creation_input_tokens")),
            cost_usd=Decimal(str(cost)) if isinstance(cost, (int, float)) else Decimal(0),
        )
        if data.get("is_error"):
            raise LLMError(f"`claude -p` error: {str(data.get('result'))[:300]}")
        out = data.get("structured_output")
        if out is None:
            try:
                out = json.loads(data.get("result") or "")
            except (json.JSONDecodeError, TypeError) as exc:
                raise LLMError("`claude -p` returned no structured output.") from exc
        if not isinstance(out, dict):
            raise LLMError("`claude -p` returned JSON that isn't an object.")
        return out, log


class AnthropicAPI:
    """The Anthropic SDK, with structured output and server-side refusal fallbacks."""

    def __init__(self, model: str, effort: str = "medium", timeout: int = 300):
        import anthropic  # only needed for this path

        self.model = model
        self.effort = effort
        self._client = anthropic.Anthropic(timeout=float(timeout))

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, Any], *, agent: str
    ) -> tuple[dict[str, Any], ModelCallLog]:
        import anthropic

        # Typed loosely: the SDK's TypedDicts don't infer well from a plain dict literal.
        output_config: Any = {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        messages: Any = [{"role": "user", "content": prompt}]
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # route a refusal to a fallback model, server side
                system=system,
                messages=messages,
                output_config=output_config,
            )
        except anthropic.APIConnectionError as exc:
            raise LLMError("Can't reach the Anthropic API.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        u = response.usage
        served_by = str(response.model)
        log = ModelCallLog(
            agent=agent,
            model=served_by,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            cost_usd=api_cost(
                served_by,
                u.input_tokens,
                u.output_tokens,
                u.cache_read_input_tokens or 0,
                u.cache_creation_input_tokens or 0,
            ),
        )
        if response.stop_reason == "refusal":
            raise LLMError("The model declined the planning request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model ran out of output tokens before finishing the plans.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise LLMError("The model returned no text.")
        try:
            out = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("The model returned invalid JSON.") from exc
        if not isinstance(out, dict):
            raise LLMError("The model returned JSON that isn't an object.")
        return out, log


def make_llm(kind: str, model: str, effort: str, timeout: int) -> LLM:
    if kind == "api":
        return AnthropicAPI(model, effort=effort, timeout=timeout)
    return ClaudeCLI(model, timeout=timeout)
