"""Config-driven proof: build_runner constructs the runner from the runner YAML.

THE multi-CLI test. build_runner must read the CLI interface (cli, default_args,
arg_map, invoke_template, config_dir_env, parser) from <name>.yaml — NOT from
hardcoded Claude flags in cli.py. We prove this by pointing build_runner at a
fixture YAML for a *different* CLI and asserting the produced command is that
CLI's command, not Claude's.
"""

from pathlib import Path

import pytest

from copeca.cli import build_runner
from copeca.config.resources import data_path
from copeca.runners.subprocess import SubprocessRunner


@pytest.fixture
def fakecli_dir(tmp_path: Path) -> Path:
    """A runner dir with a YAML for a non-Claude CLI with a different interface."""
    d = tmp_path / "runners"
    d.mkdir()
    (d / "fakecli.yaml").write_text(
        "pricing:\n"
        "  fake-model-1:\n"
        "    input: 1.0\n"
        "    output: 2.0\n"
        "    cache_creation: 1.0\n"
        "    cache_read: 0.5\n"
        '    updated: "2026-06-20"\n'
        "runner:\n"
        "  cli: fakecli\n"
        "  default_args: [run, --json]\n"
        "  arg_map: {model: -m, prompt_separator: --}\n"
        "  parser: stream_json\n"
    )
    return d


class TestBuildRunnerConfigDriven:
    def test_builds_fake_cli_command_not_claude(self, fakecli_dir: Path) -> None:
        """The command produced uses the FAKE CLI's flags, proving config-driven."""
        runner = build_runner("fakecli", timeout=120, runner_dirs=[fakecli_dir])
        assert isinstance(runner, SubprocessRunner)

        cmd = runner.build_command(model="fake-model-1", prompt="do the thing")

        # Fake CLI's interface — NOT Claude's.
        assert cmd[0] == "fakecli"
        assert cmd[1] == "run"
        assert cmd[2] == "--json"
        assert "-m" in cmd
        idx = cmd.index("-m")
        assert cmd[idx + 1] == "fake-model-1"
        assert cmd[-1] == "do the thing"

        # None of Claude's hardcoded flags leaked in.
        for claude_flag in (
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            "--dangerously-skip-permissions",
        ):
            assert claude_flag not in cmd, (
                f"Claude flag {claude_flag!r} leaked into fakecli command"
            )

    def test_timeout_comes_from_argument(self, fakecli_dir: Path) -> None:
        runner = build_runner("fakecli", timeout=42, runner_dirs=[fakecli_dir])
        assert runner.timeout == 42

    def test_parser_is_instantiated_from_name(self, fakecli_dir: Path) -> None:
        from copeca.runners.parsers.stream_json import StreamJsonParser

        runner = build_runner("fakecli", timeout=120, runner_dirs=[fakecli_dir])
        assert isinstance(runner.parser, StreamJsonParser)

    def test_unknown_parser_in_yaml_fails_loudly(self, tmp_path: Path) -> None:
        """A runner YAML naming a parser that isn't built must raise, not silently
        produce a parserless runner."""
        from copeca.runners.parsers import ParserNotFoundError

        d = tmp_path / "runners"
        d.mkdir()
        (d / "weirdcli.yaml").write_text(
            "runner:\n"
            "  cli: weirdcli\n"
            "  default_args: [go]\n"
            "  arg_map: {model: -m}\n"
            "  parser: not_a_real_parser\n"
        )
        with pytest.raises(ParserNotFoundError):
            build_runner("weirdcli", timeout=120, runner_dirs=[d])


class TestBuildRunnerClaude:
    """Building the packaged claude runner yields Claude's verified interface."""

    def test_claude_command_uses_verified_flags(self) -> None:
        runner = build_runner("claude", timeout=300, runner_dirs=[data_path("defaults", "runners")])
        cmd = runner.build_command(model="claude-sonnet-4-6", prompt="hi")

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--model" in cmd
        # The bogus flag must be gone.
        assert "--no-session-persistence" not in cmd
        assert cmd[-1] == "hi"

    def test_config_dir_env_wired(self) -> None:
        runner = build_runner("claude", timeout=300, runner_dirs=[data_path("defaults", "runners")])
        assert runner.config_dir_env == "CLAUDE_CONFIG_DIR"
