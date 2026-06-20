"""Parser dataclasses — Turn, ToolCall, RunResult.

ADAPTED from tilth benchmark/parse.py. Pure domain types:
parsers produce these, validators consume them.

Architecture invariant: this file must never import from runners/ (its own layer
excluded), repos/, results/, or orchestration/.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class Parser(Protocol):
    """Parser protocol — parse(stdout) -> RunResult."""
    def parse(self, stdout: str, supported_events: list[str] | None = None) -> "RunResult": ...


@dataclass
class Turn:
    """One agent turn — token usage for a single request/response cycle."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def context_tokens(self) -> int:
        """Total context processed this turn = input + cache_creation."""
        return self.input_tokens + self.cache_creation_tokens


@dataclass
class ToolCall:
    """One tool invocation by the agent — name, args, and which turn."""

    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    turn: int = 0


@dataclass
class RunResult:
    """Parsed result of a single copeca run — the data model parsers fill."""

    turns: list[Turn] = field(default_factory=list)
    result_text: str = ""
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None

    @property
    def num_turns(self) -> int:
        return len(self.turns)

    @property
    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(t.cache_creation_tokens for t in self.turns)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(t.cache_read_tokens for t in self.turns)

    @property
    def num_tool_calls(self) -> int:
        return len(self.tool_calls)
