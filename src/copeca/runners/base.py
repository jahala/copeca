"""Base runner abstraction — ABC, invoke resolution, price loading.

Architecture: port. The BaseRunner ABC defines the contract that adapter
implementations (subprocess runner, future HTTP runner) must satisfy.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from copeca.config.models import IsolationSpec
from copeca.runners.parsers.base import RunResult


class InvokeError(Exception):
    """Raised when the runner cannot build a valid CLI invocation."""


def _mcp_config_overrides(mcp_config_path: str) -> list[str]:
    """Translate an MCP config JSON file into codex -c override tokens.

    Reads the JSON file and emits, for each server in mcpServers:
      -c mcp_servers.<name>.command=<cmd>
      -c mcp_servers.<name>.args=<json-array>

    This matches codex's config-override convention (TILTH_MCP_CODEX_ARGS shape).
    The command value is bare (no extra quoting — the shell layer adds quotes if
    needed when the list is joined; subprocess passes it verbatim).

    Args:
        mcp_config_path: Absolute path to the MCP config JSON file.

    Returns:
        Flat list of CLI tokens ready to splice into the command list.
    """
    data = json.loads(Path(mcp_config_path).read_text())
    tokens: list[str] = []
    for server_name, server_cfg in data.get("mcpServers", {}).items():
        command = server_cfg.get("command", "")
        args = server_cfg.get("args", [])
        tokens += ["-c", f"mcp_servers.{server_name}.command={command}"]
        tokens += ["-c", f"mcp_servers.{server_name}.args={json.dumps(args)}"]
    return tokens


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
    # When True, fold the system prompt into the positional prompt instead of
    # passing a flag — for CLIs (e.g. codex exec) that have no system-prompt flag.
    prepend_system_prompt: bool = False
    # When True, MCP is delivered as repeated -c mcp_servers.<name>.command/args
    # overrides instead of a --mcp-config flag. Codex has no --mcp-config; it
    # reads MCP config through its -c config-override mechanism.
    mcp_via_config_overrides: bool = False

    def build_command(
        self,
        model: str,
        prompt: str,
        budget: float | None = None,
        system_prompt: str | None = None,
        append_system_prompt: str | None = None,
        tools: list[str] | None = None,
        mcp_config: str | None = None,
        isolation: IsolationSpec | None = None,
    ) -> list[str]:
        """Build the CLI command for this runner.

        Uses invoke_template if present (escape hatch for non-standard CLI
        argument conventions). Otherwise uses arg_map to construct flag-style
        arguments. If neither is present, raises InvokeError.

        Appends isolation.strict_mcp_flags and isolation.disable_session_flags
        for EVERY run (baseline included) so the clean-room contract holds
        across CLIs without per-CLI branches (architecture §13.4).

        Args:
            model: Full model ID from runner pricing keys.
            prompt: The task prompt (placed after prompt_separator).
            budget: Optional budget in USD.
            system_prompt: Optional system prompt override.
            append_system_prompt: Optional per-mode instruction to append to the
                agent's base prompt.  For CLIs with an --append-system-prompt flag
                (claude), emitted as that flag.  For CLIs without a flag (codex,
                gemini, prepend_system_prompt=True), prepended to the positional
                prompt so the instruction is carried rather than silently dropped.
            tools: Optional list of allowed tool names.
            mcp_config: Optional path to MCP config JSON.
            isolation: Per-CLI clean-room descriptor (architecture §13.4).
                       When None, no isolation flags are appended.

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

        # MCP via -c overrides (codex) — mutually exclusive with arg_map mcp_config key.
        # Emitted BEFORE the arg_map loop so the override block is a coherent unit.
        if self.mcp_via_config_overrides and mcp_config:
            cmd.extend(_mcp_config_overrides(mcp_config))

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
            elif key == "append_system_prompt" and append_system_prompt:
                # CLIs that have a dedicated flag (e.g. claude --append-system-prompt).
                cmd.extend([flag, append_system_prompt])
            elif key == "tools" and tools:
                cmd.extend([flag, ",".join(tools)])
            elif key == "mcp_config" and mcp_config and not self.mcp_via_config_overrides:
                # When mcp_via_config_overrides is set, the file was already translated
                # into -c pairs above — skip the flag-path form here.
                cmd.extend([flag, mcp_config])

        # ── Isolation flags (architecture §13.2) ─────────────────────
        # Appended BEFORE the positional prompt for every run — baseline
        # included. Static flags from the descriptor are appended verbatim;
        # dynamic per-server flags (Gemini) are ISO-5's concern.
        if isolation is not None:
            cmd.extend(isolation.strict_mcp_flags)
            cmd.extend(isolation.disable_session_flags)

        # prompt_separator + positional prompt always comes last. A runner with
        # no system-prompt flag (codex / gemini, prepend_system_prompt=True) folds
        # the system prompt into the positional prompt here, so instructions are
        # carried rather than silently dropped.
        # append_system_prompt uses the same prepend path for these CLIs.
        effective_prompt = prompt
        if self.prepend_system_prompt and system_prompt:
            effective_prompt = f"{system_prompt}\n\n{effective_prompt}"
        if self.prepend_system_prompt and append_system_prompt:
            effective_prompt = f"{append_system_prompt}\n\n{effective_prompt}"
        separator = self.arg_map.get("prompt_separator", "")
        if separator:
            cmd.append(separator)
        cmd.append(effective_prompt)

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
    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        exclude: set[str] | None = None,
    ) -> RunResult:
        """Execute the command and return a parsed RunResult."""
        ...
