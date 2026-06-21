"""Test Claude Code stream-json parser — parsing verbose Claude Code output."""

from pathlib import Path

import pytest

from copeca.runners.parsers.stream_json import (
    ParseError,
    StreamJsonParser,
    parse_stream_json,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_stream_json.txt"


class TestStreamJsonParser:
    def test_parses_turns(self):
        text = FIXTURE.read_text()
        result = parse_stream_json(text)
        # 3 assistant messages with token usage = 3 turns
        assert result.num_turns == 3, f"expected 3 turns, got {result.num_turns}"

    def test_parses_total_tokens(self):
        result = parse_stream_json(FIXTURE.read_text())
        assert result.total_input_tokens == 15800
        assert result.total_output_tokens == 450

    def test_parses_result_text(self):
        result = parse_stream_json(FIXTURE.read_text())
        assert "Matcher" in result.result_text
        assert "RegexMatcher" in result.result_text

    def test_parses_tool_calls(self):
        result = parse_stream_json(FIXTURE.read_text())
        assert result.num_tool_calls == 2
        names = [tc.name for tc in result.tool_calls]
        assert "Grep" in names

    def test_empty_output(self):
        result = parse_stream_json("")
        assert result.num_turns == 0
        assert result.result_text == ""

    def test_malformed_json(self):
        with pytest.raises(ParseError):
            parse_stream_json("not json")


class TestStreamJsonParserAdapter:
    def test_parse_delegates_to_parse_stream_json(self):
        """StreamJsonParser.parse() calls parse_stream_json correctly."""
        text = FIXTURE.read_text()
        parser = StreamJsonParser()
        result = parser.parse(text)
        assert result.num_turns == 3
        assert result.total_input_tokens == 15800
        assert result.total_output_tokens == 450
        assert result.num_tool_calls == 2

    def test_parse_empty_input(self):
        parser = StreamJsonParser()
        result = parser.parse("")
        assert result.num_turns == 0
        assert result.result_text == ""

    def test_parse_malformed_json_raises(self):
        parser = StreamJsonParser()
        with pytest.raises(ParseError):
            parser.parse("not json")


class TestStreamJsonDedup:
    """Claude streams one assistant message as several events (one per content
    block: thinking / text / tool_use), each repeating the message's full usage.
    The parser must count usage ONCE per message.id (else tokens and computed
    cost inflate ~2-3x) while STILL collecting tool_use + text from every
    block-event (shakedown SD-D).
    """

    def test_dedupes_repeated_message_usage_by_id(self):
        import json as _json

        usage_a = {
            "input_tokens": 2,
            "output_tokens": 8,
            "cache_creation_input_tokens": 13996,
            "cache_read_input_tokens": 16945,
        }

        def _ev(content):
            return _json.dumps({
                "type": "assistant",
                "message": {
                    "id": "msg_AAA",
                    "role": "assistant",
                    "usage": usage_a,
                    "content": content,
                },
            })

        thinking_ev = _ev([{"type": "thinking", "thinking": "..."}])
        text_ev = _ev([{"type": "text", "text": "Running the command."}])
        tool_ev = _ev([{"type": "tool_use", "name": "Bash", "input": {"command": "echo one"}}])
        b_ev = _json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_BBB",
                "role": "assistant",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 71,
                    "cache_creation_input_tokens": 174,
                    "cache_read_input_tokens": 30941,
                },
                "content": [{"type": "text", "text": "Done."}],
            },
        })

        result = parse_stream_json("\n".join([thinking_ev, text_ev, tool_ev, b_ev]))

        # usage counted ONCE per message id -> 2 turns, not 4
        assert result.num_turns == 2
        assert result.total_cache_creation_tokens == 13996 + 174
        assert result.total_cache_read_tokens == 16945 + 30941
        assert result.total_output_tokens == 8 + 71
        # content is still fully collected from every block-event
        assert result.num_tool_calls == 1
        assert "Running the command." in result.result_text
        assert "Done." in result.result_text

    def test_no_id_messages_are_not_deduped(self):
        """When messages carry no id (older/foreign streams), every usage block
        is counted (cannot dedupe) — preserves prior behavior."""
        import json as _json

        ev = _json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "content": [{"type": "text", "text": "x"}],
            },
        })
        result = parse_stream_json("\n".join([ev, ev, ev]))
        assert result.num_turns == 3
