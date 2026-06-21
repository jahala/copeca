"""Test C — mcp_config command wiring via runner arg_map.

build_command includes the mcp_config flag+path when:
  - the runner's arg_map has an "mcp_config" key (e.g. "--mcp-config"), AND
  - mcp_config is a non-empty string

We assert the mechanism — the flag name comes from arg_map, NOT hardcoded.
This means operators can declare any flag they like.
"""

from __future__ import annotations

from pathlib import Path

from copeca.runners.base import BaseRunner
from copeca.runners.parsers.base import RunResult


class StubRunner(BaseRunner):
    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout)

    def run(self, command: list[str], cwd: str | None = None) -> RunResult:
        return self.parse("")


def _make_runner_with_mcp(flag: str = "--mcp-config") -> StubRunner:
    """Runner whose arg_map declares an mcp_config flag."""
    return StubRunner(
        name="mcp-runner",
        cli="agent-cli",
        default_args=[],
        arg_map={
            "model": "--model",
            "mcp_config": flag,  # operator-declared flag name, NOT hardcoded
            "prompt_separator": "--",
        },
    )


def _make_runner_without_mcp() -> StubRunner:
    """Runner whose arg_map has NO mcp_config key — mcp wiring must be a no-op."""
    return StubRunner(
        name="no-mcp-runner",
        cli="agent-cli",
        default_args=[],
        arg_map={
            "model": "--model",
            "prompt_separator": "--",
        },
    )


class TestMcpCommandWiring:
    """build_command includes mcp_config flag only when arg_map declares it."""

    def test_mcp_config_in_command_when_arg_map_declares_flag(self) -> None:
        """With arg_map mcp_config key present and a non-None path, flag+path appear.

        Key: we test the MECHANISM (arg_map-driven) — the flag is '--mcp-config'
        only because we put it in arg_map, not because it's hardcoded.
        """
        runner = _make_runner_with_mcp("--mcp-config")

        cmd = runner.build_command(
            model="test-model",
            prompt="do something",
            mcp_config="/tmp/x.json",
        )

        assert "--mcp-config" in cmd, (
            "'--mcp-config' must appear when arg_map declares it and mcp_config is provided"
        )
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == "/tmp/x.json", "Path must immediately follow the flag"

    def test_mcp_config_absent_when_mcp_config_is_none(self) -> None:
        """mcp_config=None → flag is NOT emitted (build_command no-ops it)."""
        runner = _make_runner_with_mcp("--mcp-config")

        cmd = runner.build_command(
            model="test-model",
            prompt="do something",
            mcp_config=None,
        )

        assert "--mcp-config" not in cmd

    def test_mcp_config_absent_when_runner_has_no_arg_map_entry(self) -> None:
        """Even when mcp_config is provided, if the runner's arg_map has no
        'mcp_config' key, the flag is silently dropped — NOT an error.

        This tests that the mechanism is truly runner-config-driven.
        """
        runner = _make_runner_without_mcp()

        cmd = runner.build_command(
            model="test-model",
            prompt="do something",
            mcp_config="/tmp/x.json",
        )

        # No mcp flag at all (runner didn't declare one)
        mcp_tokens = [t for t in cmd if "mcp" in t.lower() or ".json" in t]
        assert mcp_tokens == [], (
            f"No mcp-related tokens expected when arg_map has no mcp_config key; got: {mcp_tokens}"
        )

    def test_custom_flag_name_is_used(self) -> None:
        """The flag name is whatever is in arg_map — operators can choose any name."""
        runner = _make_runner_with_mcp("--servers-file")

        cmd = runner.build_command(
            model="test-model",
            prompt="task",
            mcp_config="/etc/servers.json",
        )

        assert "--servers-file" in cmd, (
            "Custom flag name from arg_map must be used — NOT '--mcp-config'"
        )
        idx = cmd.index("--servers-file")
        assert cmd[idx + 1] == "/etc/servers.json"
        assert "--mcp-config" not in cmd

    def test_prompt_still_last_after_mcp_flag(self) -> None:
        """The prompt (positional) must still be the last token."""
        runner = _make_runner_with_mcp("--mcp-config")

        cmd = runner.build_command(
            model="m",
            prompt="my task",
            mcp_config="/tmp/cfg.json",
        )

        assert cmd[-1] == "my task"

    def test_mcp_wiring_end_to_end_from_run_single(self, tmp_path: Path) -> None:
        """run_single passes harness.mcp_config_path to build_command.

        This wires test B (mcp materialization) to test C (command wiring):
        the file written by provision_arm ends up in the built command.
        """
        import json

        from copeca.config.models import (
            Category,
            ComprehensionGroundTruth,
            Difficulty,
            Language,
            Mode,
            Task,
            TaskType,
        )
        from copeca.orchestration.run import run_single
        from copeca.runners.parsers.base import RunResult

        # Spy that records the command it receives
        class CommandSpyRunner:
            name = "cmd-spy"

            def __init__(self) -> None:
                self.captured_command: list[str] = []

            def build_command(
                self,
                model: str,
                prompt: str,
                mcp_config: str | None = None,
                **kwargs: object,
            ) -> list[str]:
                cmd = ["agent-cli", "--model", model]
                if mcp_config:
                    cmd.extend(["--mcp-config", mcp_config])
                cmd.extend(["--", prompt])
                self.captured_command = cmd
                return cmd

            def run(
                self,
                command: list[str],
                cwd: str | None = None,
                env: dict[str, str] | None = None,
            ) -> RunResult:
                return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)

        mcp_dict = {"mcpServers": {"s": {"command": "npx", "args": ["-y", "srv"]}}}
        mode = Mode(name="mcprun", mcp_config=mcp_dict)

        class StubMgr:
            def __init__(self, wt: Path) -> None:
                self._wt = wt

            def verify_toolchain(self, k: str) -> None:
                pass

            def create_worktree(self, *a: object, **kw: object) -> Path:
                self._wt.mkdir(parents=True, exist_ok=True)
                return self._wt

            def setup(self, wt: Path) -> None:
                pass

            def reset(self, wt: Path) -> None:
                pass

        task = Task(
            name="t",
            source="test",
            repo="r",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="ok",
            ground_truth=ComprehensionGroundTruth(required_strings=[]),
        )

        runner = CommandSpyRunner()
        mgr = StubMgr(tmp_path / "wt")

        run_single(
            task=task,
            mode_name="mcprun",
            model="m",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        # The mcp.json path written by provision_arm must appear in the command
        mcp_tokens = [t for t in runner.captured_command if t.endswith("mcp.json")]
        assert len(mcp_tokens) == 1, (
            f"Exactly one mcp.json path must appear in the command; "
            f"got command={runner.captured_command}"
        )
        # Verify the file actually exists
        assert Path(mcp_tokens[0]).exists(), (
            "The mcp.json path in the command must point at the written file"
        )
        written = json.loads(Path(mcp_tokens[0]).read_text())
        assert written == mcp_dict
