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
