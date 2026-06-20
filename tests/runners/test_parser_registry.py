"""Test the parser registry — name -> Parser lookup with loud failure.

A CLI's output parser is named in its runner YAML. get_parser(name) resolves
that name to a Parser instance. An unknown/unimplemented parser must fail
loudly + honestly, not silently — so a CLI whose parser isn't built yet errors
instead of producing a parserless (zero-token) RunResult.
"""

import pytest

from copeca.runners.parsers import ParserNotFoundError, get_parser
from copeca.runners.parsers.base import Parser
from copeca.runners.parsers.stream_json import StreamJsonParser


class TestGetParser:
    def test_stream_json_resolves_to_stream_json_parser(self):
        parser = get_parser("stream_json")
        assert isinstance(parser, StreamJsonParser)

    def test_returned_object_satisfies_parser_protocol(self):
        parser = get_parser("stream_json")
        assert isinstance(parser, Parser)  # runtime_checkable Protocol

    def test_unknown_parser_raises_clear_error(self):
        with pytest.raises(ParserNotFoundError) as exc_info:
            get_parser("nope")
        # The error must name the unknown parser AND the known ones (honest).
        msg = str(exc_info.value)
        assert "nope" in msg
        assert "stream_json" in msg
