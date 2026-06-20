"""Test copeca parser dataclasses — Turn, ToolCall, RunResult."""

from copeca.runners.parsers.base import RunResult, ToolCall, Turn


class TestTurn:
    def test_context_tokens_computed(self):
        """context_tokens = input_tokens + cache_creation_tokens (per-turn)."""
        t = Turn(input_tokens=5000, cache_creation_tokens=3500)
        assert t.context_tokens == 8500

    def test_context_tokens_zero_when_both_zero(self):
        t = Turn()
        assert t.context_tokens == 0

    def test_context_tokens_input_only(self):
        t = Turn(input_tokens=5000, output_tokens=200)
        assert t.context_tokens == 5000  # cache_creation defaults to 0


class TestToolCall:
    def test_fields_assigned_correctly(self):
        """ToolCall carries name, input dict, and turn index."""
        tc = ToolCall(name="tilth_search", input={"query": "Matcher"}, turn=3)
        assert tc.name == "tilth_search"
        assert tc.input == {"query": "Matcher"}
        assert tc.turn == 3


class TestRunResult:
    def test_properties_from_turns(self):
        """Aggregate properties sum correctly across turns."""
        turns = [
            Turn(input_tokens=5000, output_tokens=200, cache_creation_tokens=100, cache_read_tokens=3000),
            Turn(input_tokens=8000, output_tokens=150, cache_creation_tokens=200, cache_read_tokens=5000),
        ]
        result = RunResult(
            turns=turns,
            total_cost_usd=0.0734,
            duration_ms=45230,
            result_text="The Matcher trait is defined in...",
            tool_calls=[ToolCall(name="grep"), ToolCall(name="read")],
        )
        assert result.num_turns == 2
        assert result.total_input_tokens == 13000
        assert result.total_output_tokens == 350
        assert result.total_cache_creation_tokens == 300
        assert result.total_cache_read_tokens == 8000
        assert result.num_tool_calls == 2
        assert result.result_text == "The Matcher trait is defined in..."
        assert result.total_cost_usd == 0.0734

    def test_empty_result(self):
        result = RunResult()
        assert result.num_turns == 0
        assert result.total_input_tokens == 0
        assert result.total_output_tokens == 0
        assert result.total_cache_creation_tokens == 0
        assert result.total_cache_read_tokens == 0
        assert result.num_tool_calls == 0
        assert result.result_text == ""
        assert result.error is None
