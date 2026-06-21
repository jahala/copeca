"""Codex ``exec --json`` parser.

Parses the JSONL event stream from ``codex exec --json`` (OpenAI Codex CLI).
Verified against codex-cli 0.133.0 — the fixtures in tests/fixtures/sample_codex_*.jsonl
were captured verbatim from real runs.

Architecture: domain-adapter. Imports runners/parsers/base.py (domain types) and
produces RunResult objects consumed by the orchestrator and validator.

Cost note: codex emits NO ``total_cost_usd``, so RunResult.total_cost_usd is 0.0
and the cost is computed downstream from token counts (cost_source="modeled" — see
orchestration/run.py and docs/metrics.md). Token semantics follow the OpenAI
convention: ``turn.completed.usage.input_tokens`` is the TOTAL prompt size and
INCLUDES ``cached_input_tokens``, so the fresh (input-rate) portion is
``input_tokens - cached_input_tokens`` and the cached portion is billed at the
cache-read rate. The old tilth parser charged the full ``input_tokens`` at the
input rate AND the cached tokens again at the cached rate — copeca avoids that
double-count.
"""

import json

from copeca.runners.parsers.base import RunResult, ToolCall, Turn


class ParseError(Exception):
    """Raised when the parser cannot process the agent's output stream."""


def parse_codex_json(raw: str) -> RunResult:
    """Parse codex ``exec --json`` JSONL output into a RunResult.

    Events (codex 0.133.0): ``thread.started`` / ``turn.started`` (ignored),
    ``item.started`` (ignored — an item is counted once, on completion),
    ``item.completed`` (``agent_message`` -> result text; ``command_execution`` /
    ``mcp_tool_call`` / ``file_edit`` / ``file_write`` -> tool calls),
    ``turn.completed`` (token usage), and ``error`` / ``turn.failed``
    (-> RunResult.error).

    ``agent_message`` and ``command_execution`` are verified against real 0.133.0
    output; ``mcp_tool_call`` / ``file_edit`` / ``file_write`` follow codex's
    documented item schema (also used by the tilth benchmark).

    Args:
        raw: Complete stdout from a ``codex exec --json`` run.

    Returns:
        RunResult with turns, tool_calls, result_text, and error populated.
        ``total_cost_usd`` is 0.0 — codex emits no vendor cost (computed downstream).
    """
    if not raw.strip():
        return RunResult()

    turns: list[Turn] = []
    tool_calls: list[ToolCall] = []
    result_text = ""
    error: str | None = None

    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON in stream: {e}") from e

        etype = event.get("type")

        if etype == "turn.completed":
            usage = event.get("usage", {}) or {}
            total_input = usage.get("input_tokens", 0)
            cached = usage.get("cached_input_tokens", 0)
            # input_tokens includes cached (OpenAI convention) — split so the fresh
            # portion is billed at the input rate, the cached portion at cache-read.
            fresh_input = max(total_input - cached, 0)
            turns.append(Turn(
                input_tokens=fresh_input,
                output_tokens=usage.get("output_tokens", 0),
                cache_creation_tokens=0,  # codex exposes no cache-write count
                cache_read_tokens=cached,
            ))

        elif etype == "item.completed":
            item = event.get("item", {})
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            if itype == "agent_message":
                text = item.get("text", "")
                if text:
                    if result_text:
                        result_text += "\n"
                    result_text += text
            elif itype == "command_execution":
                tool_calls.append(ToolCall(
                    name="Bash",
                    input={"command": item.get("command", "")},
                    turn=len(turns),
                ))
            elif itype == "mcp_tool_call":
                tool_calls.append(ToolCall(
                    name=item.get("tool", "unknown"),
                    input=item.get("arguments", {}) or {},
                    turn=len(turns),
                ))
            elif itype == "file_edit":
                tool_calls.append(ToolCall(
                    name="Edit",
                    input={"file_path": item.get("file_path", "")},
                    turn=len(turns),
                ))
            elif itype == "file_write":
                tool_calls.append(ToolCall(
                    name="Write",
                    input={"file_path": item.get("file_path", "")},
                    turn=len(turns),
                ))

        elif etype in ("error", "turn.failed"):
            # error event: top-level "message"; turn.failed: nested error.message.
            msg = event.get("message")
            if not msg:
                err_obj = event.get("error")
                if isinstance(err_obj, dict):
                    msg = err_obj.get("message", "")
            if msg:
                error = f"codex run failed: {msg}"

    return RunResult(
        turns=turns,
        result_text=result_text,
        total_cost_usd=0.0,
        duration_ms=0,
        tool_calls=tool_calls,
        error=error,
    )


class CodexJsonParser:
    """Parser adapter — wraps parse_codex_json for SubprocessRunner's parser protocol."""

    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        return parse_codex_json(stdout)
