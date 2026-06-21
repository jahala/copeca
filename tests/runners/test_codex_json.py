"""Test the codex `exec --json` parser — against REAL codex-cli 0.133.0 output.

Fixtures are VERBATIM real `codex exec --json` output (no hand-editing, no mocks):
- sample_codex_json.jsonl : a successful run that ran one shell command then answered.
- sample_codex_error.jsonl: a failed run (model rejected) — error + turn.failed events.
"""

from pathlib import Path

import pytest

from copeca.runners.parsers.codex_json import (
    CodexJsonParser,
    ParseError,
    parse_codex_json,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample_codex_json.jsonl"
ERROR_SAMPLE = FIXTURES / "sample_codex_error.jsonl"


class TestCodexJsonParser:
    def test_parses_single_turn(self):
        # one turn.completed event = one turn
        assert parse_codex_json(SAMPLE.read_text()).num_turns == 1

    def test_input_tokens_exclude_cached(self):
        # codex's input_tokens (27333) INCLUDES cached_input_tokens (18688) per the
        # OpenAI convention. copeca bills the fresh portion at the input rate and the
        # cached portion at the cache-read rate — the old tilth parser double-counted
        # by charging the full input_tokens AND the cached tokens again.
        result = parse_codex_json(SAMPLE.read_text())
        assert result.total_input_tokens == 27333 - 18688  # 8645 fresh
        assert result.total_cache_read_tokens == 18688
        assert result.total_cache_creation_tokens == 0  # codex exposes no cache-write count
        assert result.total_output_tokens == 60

    def test_no_vendor_cost(self):
        # codex emits no total_cost_usd — cost is computed downstream (modeled).
        assert parse_codex_json(SAMPLE.read_text()).total_cost_usd == 0.0

    def test_parses_result_text(self):
        assert "hello-from-codex" in parse_codex_json(SAMPLE.read_text()).result_text

    def test_parses_command_execution_as_bash_once(self):
        # codex emits item.started AND item.completed for the same command; only
        # item.completed is counted, so exactly ONE tool call (not two).
        result = parse_codex_json(SAMPLE.read_text())
        assert result.num_tool_calls == 1
        tc = result.tool_calls[0]
        assert tc.name == "Bash"
        assert "echo hello-from-codex" in tc.input.get("command", "")

    def test_error_sample_sets_error(self):
        result = parse_codex_json(ERROR_SAMPLE.read_text())
        assert result.error is not None
        assert "not supported" in result.error  # the model-rejection message
        assert result.num_turns == 0  # no turn.completed in a failed run

    def test_empty_output(self):
        result = parse_codex_json("")
        assert result.num_turns == 0
        assert result.result_text == ""
        assert result.error is None

    def test_malformed_json_raises(self):
        with pytest.raises(ParseError):
            parse_codex_json("not json")


class TestCodexJsonParserAdapter:
    def test_parse_delegates(self):
        result = CodexJsonParser().parse(SAMPLE.read_text())
        assert result.num_turns == 1
        assert result.num_tool_calls == 1

    def test_parse_empty(self):
        assert CodexJsonParser().parse("").num_turns == 0
