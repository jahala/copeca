"""Base runner abstraction — ABC, invoke resolution, price loading.

Architecture: port. The BaseRunner ABC defines the contract that adapter
implementations (subprocess runner, future HTTP runner) must satisfy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from copeca.runners.parsers.base import RunResult

class InvokeError(Exception):
    """Raised when the runner cannot build a valid CLI invocation."""


@dataclass
class BaseRunner(ABC):
    """Abstract runner — defines the CLI agent contract.

    Concrete runners implement parse() for their output format and can
    optionally override build_command() for non-standard CLI conventions.
    """

    name: str
    cli: str = "claude"
    default_args: list[str] = field(default_factory=list)
    arg_map: dict[str, str] = field(default_factory=dict)
    invoke_template: str = ""

    def build_command(
        self,
        model: str,
        prompt: str,
        budget: float | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        mcp_config: str | None = None,
    ) -> list[str]:
        """Build the CLI command for this runner.

        Uses invoke_template if present (escape hatch for non-standard CLI
        argument conventions). Otherwise uses arg_map to construct flag-style
        arguments. If neither is present, raises InvokeError.

        Args:
            model: Full model ID from runner pricing keys.
            prompt: The task prompt (placed after prompt_separator).
            budget: Optional budget in USD.
            system_prompt: Optional system prompt override.
            tools: Optional list of allowed tool names.
            mcp_config: Optional path to MCP config JSON.

        Returns:
            List of CLI argument strings ready for subprocess.
        """
        cmd: list[str] = [self.cli]

        if self.invoke_template:
            # Escape hatch: template-driven invocation
            resolved = self.invoke_template.format(
                cli=self.cli,
                model=model,
                prompt=prompt,
                budget=str(budget) if budget else "",
                system_prompt=system_prompt or "",
                tools=",".join(tools) if tools else "",
                mcp_config=mcp_config or "",
            )
            return resolved.split()

        if not self.arg_map:
            raise InvokeError(
                f"Runner '{self.name}' has neither arg_map nor invoke_template — "
                f"cannot build command. Add at least one to the runner YAML."
            )

        # arg_map path: flag-style arguments
        cmd.extend(self.default_args)

        for key, flag in self.arg_map.items():
            if key == "prompt_separator":
                # The separator comes before the positional prompt
                continue
            elif key == "model":
                cmd.extend([flag, model])
            elif key == "budget" and budget is not None:
                cmd.extend([flag, str(budget)])
            elif key == "system_prompt" and system_prompt:
                cmd.extend([flag, system_prompt])
            elif key == "tools" and tools:
                cmd.extend([flag, ",".join(tools)])
            elif key == "mcp_config" and mcp_config:
                cmd.extend([flag, mcp_config])

        # prompt_separator + positional prompt always comes last
        separator = self.arg_map.get("prompt_separator", "")
        if separator:
            cmd.append(separator)
        cmd.append(prompt)

        return cmd

    @abstractmethod
    def parse(self, stdout: str, supported_events: list[str] | None = None) -> RunResult:
        """Parse agent stdout into a RunResult.

        Each runner type has its own output format. Concrete implementations
        must provide the parser for their format.

        Args:
            stdout: Raw agent stdout from the subprocess.
            supported_events: Which event types the runner can emit (used for
                sparse output handling — fields not supported are null).

        Returns:
            Parsed RunResult with turns, tool_calls, result_text, and cost.
        """
        ...

    @abstractmethod
    def run(self, command: list[str], cwd: str | None = None) -> RunResult:
        """Execute the command and return a parsed RunResult."""
        ...
