"""Gemini CLI ``--output-format json`` parser.

Parses the single-JSON-object output from ``gemini -p --output-format json --yolo``.

Verified output shape (gemini CLI, 2026):

.. code-block:: json

    {
        "response": "<final answer text>",
        "stats": {
            "models": {
                "<model-id>": {
                    "tokens": {
                        "prompt": N,
                        "candidates": N,
                        "cached": N,
                        "thoughts": N,
                        "tool": N,
                        "total": N
                    }
                }
            },
            "tools": {
                "totalCalls": N,
                "byName": {"<tool-name>": <count>, ...}
            }
        },
        "error": {}
    }

Cost note: gemini JSON emits NO ``total_cost_usd``, so RunResult.total_cost_usd is
0.0 and cost is computed downstream from token counts (cost_source="modeled" — see
orchestration/run.py and docs/metrics.md).

Token mapping:
  input_tokens        ← tokens.prompt
  output_tokens       ← tokens.candidates + tokens.thoughts (both billed at output rate)
  cache_read_tokens   ← tokens.cached
  cache_creation_tokens ← 0  (gemini JSON reports no cache-write count)

Architecture: domain-adapter. Imports runners/parsers/base.py (domain types) and
produces RunResult objects consumed by the orchestrator and validator.
"""

import json

from copeca.runners.parsers.base import RunResult, ToolCall, Turn


class ParseError(Exception):
    """Raised when the parser cannot process the agent's output."""


def parse_gemini_json(raw: str) -> RunResult:
    """Parse ``gemini --output-format json`` output into a RunResult.

    Args:
        raw: Complete stdout from a ``gemini -p --output-format json`` run.

    Returns:
        RunResult with one Turn of token counts, result_text, tool_calls, and
        error populated.  ``total_cost_usd`` is 0.0 — gemini emits no vendor
        cost (computed downstream).
    """
    if not raw.strip():
        return RunResult()

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return RunResult(error=f"gemini run produced malformed JSON: {exc}")

    if not isinstance(obj, dict):
        return RunResult(error="gemini JSON output is not an object")

    # ── Result text ───────────────────────────────────────────────────────────
    result_text: str = obj.get("response", "") or ""

    # ── Token counts ──────────────────────────────────────────────────────────
    # stats.models is a dict keyed by model id; we sum across all model keys in
    # case a future multi-model run emits more than one entry.
    stats: object = obj.get("stats")
    turns: list[Turn] = []

    if isinstance(stats, dict):
        models: object = stats.get("models")
        if isinstance(models, dict):
            total_prompt = 0
            total_candidates = 0
            total_cached = 0
            total_thoughts = 0
            for model_data in models.values():
                if not isinstance(model_data, dict):
                    continue
                tokens: object = model_data.get("tokens")
                if not isinstance(tokens, dict):
                    continue
                total_prompt += int(tokens.get("prompt", 0) or 0)
                total_candidates += int(tokens.get("candidates", 0) or 0)
                total_cached += int(tokens.get("cached", 0) or 0)
                total_thoughts += int(tokens.get("thoughts", 0) or 0)

            if total_prompt or total_candidates or total_cached or total_thoughts:
                turns.append(
                    Turn(
                        input_tokens=total_prompt,
                        # thoughts are billed at the output rate alongside candidates
                        output_tokens=total_candidates + total_thoughts,
                        cache_creation_tokens=0,
                        cache_read_tokens=total_cached,
                    )
                )

    # ── Tool calls ────────────────────────────────────────────────────────────
    # stats.tools.byName maps tool-name -> call-count; we expand each into N
    # ToolCall entries so num_tool_calls matches the actual invocation count.
    tool_calls: list[ToolCall] = []
    if isinstance(stats, dict):
        tools_section: object = stats.get("tools")
        if isinstance(tools_section, dict):
            by_name: object = tools_section.get("byName")
            if isinstance(by_name, dict):
                for tool_name, count in by_name.items():
                    call_count = int(count or 0)
                    for _ in range(call_count):
                        tool_calls.append(ToolCall(name=str(tool_name), input={}, turn=0))

    # ── Error ─────────────────────────────────────────────────────────────────
    error: str | None = None
    err_obj: object = obj.get("error")
    if isinstance(err_obj, dict) and err_obj:
        # non-empty error dict — surface as a string
        error = f"gemini run failed: {json.dumps(err_obj)}"
    elif isinstance(err_obj, str) and err_obj:
        error = f"gemini run failed: {err_obj}"

    return RunResult(
        turns=turns,
        result_text=result_text,
        total_cost_usd=0.0,
        duration_ms=0,
        tool_calls=tool_calls,
        error=error,
    )


class GeminiJsonParser:
    """Parser adapter — wraps parse_gemini_json for SubprocessRunner's parser protocol."""

    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        return parse_gemini_json(stdout)
