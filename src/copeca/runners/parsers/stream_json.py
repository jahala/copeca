"""Claude Code stream-json parser.

ADAPTED from tilth benchmark/parse.py parse_stream_json(). Parses the verbose
stream-json output format (`--output-format stream-json --verbose`).

Architecture: domain-adapter. Imports from runners/parsers/base.py (domain types)
and produces RunResult objects consumed by the orchestrator and validator.
"""

import json

from copeca.runners.parsers.base import RunResult, ToolCall, Turn


class ParseError(Exception):
    """Raised when the parser cannot process the agent's output stream."""


def parse_stream_json(raw: str) -> RunResult:
    """Parse Claude Code stream-json verbose output into a RunResult.

    Extracts turn-by-turn token usage from assistant messages that carry
    `usage` blocks, tool calls from user messages with `tool_use` content,
    and the final result text from the last assistant text message.

    When the result event carries ``is_error: true`` (e.g. "Not logged in ·
    Please run /login", budget exhaustion), the run is recorded as an error
    rather than a valid answer: ``RunResult.error`` is set to the result text
    and ``result_text`` is left empty.  This prevents auth/budget failures from
    silently grading as wrong answers and skewing metrics (AUTH-3).

    Args:
        raw: Complete stdout from a Claude Code stream-json verbose run.

    Returns:
        RunResult with turns, tool_calls, result_text, total_cost_usd,
        and duration_ms populated from the parsed stream.  When the CLI
        reports is_error=true, only error is set (result_text stays empty).
    """
    if not raw.strip():
        return RunResult()

    turns: list[Turn] = []
    seen_message_ids: set[str] = set()
    tool_calls: list[ToolCall] = []
    result_text = ""
    vendor_cost = 0.0
    duration = 0
    error: str | None = None

    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON in stream: {e}") from e

        msg = event.get("message", {})
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage", {})

        # Extract turn data from assistant messages with usage
        if usage:
            # Claude streams one assistant message as several events (one per
            # content block: thinking / text / tool_use), each repeating the
            # message's full usage. Count usage ONCE per message id, else tokens
            # and computed cost inflate ~2-3x (shakedown SD-D). Tool calls and
            # text are still collected from every event below.
            msg_id = msg.get("id")
            if msg_id is None or msg_id not in seen_message_ids:
                if msg_id is not None:
                    seen_message_ids.add(msg_id)
                turns.append(
                    Turn(
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    )
                )

        # Extract tool calls from user messages
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tc = ToolCall(
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                        turn=len(turns),
                    )
                    tool_calls.append(tc)

                # Extract text from assistant messages
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        if result_text:
                            result_text += "\n"
                        result_text += text

        # Extract result event — surface is_error so auth/budget failures are
        # recorded as errors, never graded as wrong answers (AUTH-3).
        if event.get("type") == "result":
            vendor_cost = event.get("total_cost_usd", 0.0)
            duration = event.get("duration_ms", 0)
            if event.get("is_error"):
                error = str(event.get("result", "claude run reported is_error=true"))
                # Do not treat the error text as a valid answer
                result_text = ""

    return RunResult(
        turns=turns,
        result_text=result_text,
        total_cost_usd=vendor_cost,
        duration_ms=duration,
        tool_calls=tool_calls,
        error=error,
    )


class StreamJsonParser:
    """Parser adapter — wraps parse_stream_json for SubprocessRunner's parser protocol."""

    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        return parse_stream_json(stdout)
