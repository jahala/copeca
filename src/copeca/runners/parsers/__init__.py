"""Copeca runner parsers — extract structured data from agent CLI output.

Parser registry: runner YAMLs name their output parser (``parser: <name>``);
``get_parser`` resolves that name to a Parser instance. A name with no built
parser fails loudly via ``ParserNotFoundError`` — so a CLI whose output format
isn't supported yet errors honestly instead of silently producing a parserless,
zero-token RunResult.
"""

from collections.abc import Callable

from copeca.runners.parsers.base import Parser
from copeca.runners.parsers.codex_json import CodexJsonParser
from copeca.runners.parsers.gemini_json import GeminiJsonParser
from copeca.runners.parsers.stream_json import StreamJsonParser


class ParserNotFoundError(Exception):
    """Raised when a runner YAML names a parser that isn't registered."""


# name -> zero-arg factory producing a Parser. Add an entry here when a new
# output format's parser ships.
_PARSERS: dict[str, Callable[[], Parser]] = {
    "stream_json": StreamJsonParser,
    "codex_json": CodexJsonParser,
    "gemini_json": GeminiJsonParser,
}


def get_parser(name: str) -> Parser:
    """Resolve a parser name to a Parser instance.

    Args:
        name: Parser name from a runner YAML (e.g. "stream_json").

    Returns:
        A new Parser instance for that name.

    Raises:
        ParserNotFoundError: If no parser is registered under ``name``.
    """
    factory = _PARSERS.get(name)
    if factory is None:
        known = ", ".join(sorted(_PARSERS)) or "(none registered)"
        raise ParserNotFoundError(
            f"Unknown parser '{name}'. No parser is built for it yet. Known parsers: {known}."
        )
    return factory()
