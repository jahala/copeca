"""Tests for ISO-2: IsolationSpec flags in build_command (architecture §13.2).

strict_mcp_flags and disable_session_flags from IsolationSpec must be appended
to EVERY command — baseline included — so the clean-room contract holds across
CLIs without per-CLI branches.
"""

from __future__ import annotations

from copeca.config.models import IsolationSpec
from copeca.runners.base import BaseRunner
from copeca.runners.parsers.base import RunResult

# ── Stub runner ───────────────────────────────────────────────────────────────


class StubRunner(BaseRunner):
    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout)

    def run(self, command: list[str], cwd: str | None = None) -> RunResult:
        return self.parse("")


def _runner(**kwargs: object) -> StubRunner:
    defaults: dict[str, object] = {
        "name": "test-runner",
        "cli": "claude",
        "arg_map": {"model": "--model", "prompt_separator": "--"},
    }
    defaults.update(kwargs)
    return StubRunner(**defaults)  # type: ignore[arg-type]


def _isolation(**kwargs: object) -> IsolationSpec:
    return IsolationSpec(**kwargs)  # type: ignore[arg-type]


# ── strict_mcp_flags ──────────────────────────────────────────────────────────


class TestStrictMcpFlags:
    """strict_mcp_flags must be appended regardless of whether mcp_config is set."""

    def test_strict_mcp_flags_appended_without_mcp_config(self) -> None:
        """Baseline: no mcp_config, but strict flag still present (claude's
        --strict-mcp-config with no --mcp-config = zero MCP)."""
        runner = _runner()
        isolation = _isolation(strict_mcp_flags=["--strict-mcp-config"])

        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            isolation=isolation,
        )

        assert "--strict-mcp-config" in cmd

    def test_strict_mcp_flags_appended_with_mcp_config(self) -> None:
        """Experimental arm: both --mcp-config and --strict-mcp-config present."""
        runner = _runner(
            arg_map={"model": "--model", "mcp_config": "--mcp-config", "prompt_separator": "--"}
        )
        isolation = _isolation(strict_mcp_flags=["--strict-mcp-config"])

        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            mcp_config="/tmp/mcp.json",
            isolation=isolation,
        )

        assert "--strict-mcp-config" in cmd
        assert "--mcp-config" in cmd

    def test_no_strict_flags_when_isolation_empty(self) -> None:
        """When IsolationSpec has no strict_mcp_flags, nothing is appended."""
        runner = _runner()
        isolation = _isolation()  # strict_mcp_flags=[]

        cmd = runner.build_command(
            model="m",
            prompt="p",
            isolation=isolation,
        )

        assert "--strict-mcp-config" not in cmd

    def test_no_strict_flags_when_isolation_not_passed(self) -> None:
        """build_command with no isolation= kwarg must still work (backward compat)."""
        runner = _runner()

        cmd = runner.build_command(model="m", prompt="p")

        assert isinstance(cmd, list)
        assert "m" in cmd

    def test_strict_flags_come_before_prompt(self) -> None:
        """Isolation flags must NOT appear after the positional prompt."""
        runner = _runner()
        isolation = _isolation(strict_mcp_flags=["--strict-mcp-config"])

        cmd = runner.build_command(
            model="m",
            prompt="my-prompt",
            isolation=isolation,
        )

        prompt_idx = cmd.index("my-prompt")
        strict_idx = cmd.index("--strict-mcp-config")
        assert strict_idx < prompt_idx, (
            "--strict-mcp-config must appear before the positional prompt"
        )


# ── disable_session_flags ─────────────────────────────────────────────────────


class TestDisableSessionFlags:
    """disable_session_flags must also be appended before the positional prompt."""

    def test_disable_session_flags_appended(self) -> None:
        runner = _runner()
        isolation = _isolation(disable_session_flags=["--no-session-persistence"])

        cmd = runner.build_command(
            model="m",
            prompt="p",
            isolation=isolation,
        )

        assert "--no-session-persistence" in cmd

    def test_both_flag_sets_appended_together(self) -> None:
        runner = _runner()
        isolation = _isolation(
            strict_mcp_flags=["--strict-mcp-config"],
            disable_session_flags=["--no-session-persistence"],
        )

        cmd = runner.build_command(model="m", prompt="p", isolation=isolation)

        assert "--strict-mcp-config" in cmd
        assert "--no-session-persistence" in cmd

    def test_multiple_strict_flags_all_appended(self) -> None:
        """Multiple flags in the list are all appended (e.g. codex two-flag idiom)."""
        runner = _runner()
        isolation = _isolation(
            strict_mcp_flags=["--flag-a", "--flag-b"],
        )

        cmd = runner.build_command(model="m", prompt="p", isolation=isolation)

        assert "--flag-a" in cmd
        assert "--flag-b" in cmd
