"""Test BaseRunner abstract class — invoke resolution (arg_map, invoke_template)."""

import pytest

from copeca.runners.base import BaseRunner, InvokeError


class StubRunner(BaseRunner):
    """Concrete runner for testing — implements parse()."""
    def parse(self, stdout, supported_events=None):
        from copeca.runners.parsers.base import RunResult
        return RunResult(result_text=stdout)

    def run(self, command, cwd=None):
        return self.parse("")


@pytest.fixture
def runner():
    return StubRunner(
        name="test-runner",
        cli="test-cli",
        default_args=["-p", "--output-format", "json"],
        arg_map={
            "model": "--model",
            "budget": "--max-budget-usd",
            "system_prompt": "--system-prompt",
            "prompt_separator": "--",
        },
    )


class TestArgMap:
    def test_builds_command_from_arg_map(self, runner):
        cmd = runner.build_command(
            model="test-model",
            prompt="hello world",
        )
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "--model" in cmd
        assert "test-model" in cmd
        assert cmd[-1] == "hello world"
        assert cmd[-2] == "--"

    def test_invoke_template_takes_precedence(self):
        runner = StubRunner(
            name="codex",
            cli="codex",
            default_args=["exec"],
            arg_map={"model": "--model"},
            invoke_template="{cli} exec --json -m {model} -- {prompt}",
        )
        cmd = runner.build_command(model="gpt-5", prompt="fix the bug")
        assert "codex" in cmd
        assert "--json" in cmd
        assert "-m" in cmd
        assert "gpt-5" in cmd

    def test_missing_both_raises(self):
        bare_runner = StubRunner(name="bare", cli="bare")
        with pytest.raises(InvokeError, match="arg_map"):
            bare_runner.build_command(model="m", prompt="p")


# ── Task 51: BaseRunner full args ─────────────────────────────────────────

class TestFullArgs:
    """Discriminate tests for build_command with all optional parameters."""

    def test_builds_command_with_all_optional_args(self):
        """All optional flags appear in the built command."""
        runner = StubRunner(
            name="full-runner",
            cli="full-cli",
            default_args=["-q"],
            arg_map={
                "model": "--model",
                "budget": "--max-budget-usd",
                "system_prompt": "--system-prompt",
                "tools": "--allowedTools",
                "mcp_config": "--mcp-config",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(
            model="test",
            prompt="hello",
            budget=2.50,
            system_prompt="be helpful",
            tools=["Read", "Write"],
            mcp_config="mcp.json",
        )

        assert cmd[0] == "full-cli"
        assert "-q" in cmd
        assert "--model" in cmd
        assert "test" in cmd
        assert "--max-budget-usd" in cmd
        assert "2.5" in cmd
        assert "--system-prompt" in cmd
        assert "be helpful" in cmd
        assert "--allowedTools" in cmd
        assert "Read,Write" in cmd
        assert "--mcp-config" in cmd
        assert "mcp.json" in cmd
        assert "--" in cmd
        assert cmd[-1] == "hello"
        # Ensure ordering: separator before prompt
        sep_idx = cmd.index("--")
        assert cmd[sep_idx + 1] == "hello"

    def test_invoke_template_with_all_placeholders(self):
        """invoke_template resolves all placeholders correctly."""
        runner = StubRunner(
            name="tpl",
            cli="cli",
            default_args=[],
            arg_map={"model": "--model"},
            invoke_template=(
                "{cli} exec --model {model} --budget {budget} "
                "--sys {system_prompt} --tools {tools} "
                "--mcp {mcp_config} -- {prompt}"
            ),
        )

        # Multi-word values get split by str.split() in invoke_template resolution.
        # Use single-word values for reliable assertions.
        cmd = runner.build_command(
            model="gpt-5",
            prompt="fix-it",
            budget=1.23,
            system_prompt="professional",
            tools=["Bash", "Read"],
            mcp_config="servers.json",
        )

        assert cmd[0] == "cli"
        assert "exec" in cmd
        assert "--model" in cmd
        assert "gpt-5" in cmd
        assert "--budget" in cmd
        assert "1.23" in cmd
        assert "--sys" in cmd
        assert "professional" in cmd
        assert "--tools" in cmd
        assert "Bash,Read" in cmd
        assert "--mcp" in cmd
        assert "servers.json" in cmd
        assert "--" in cmd
        assert cmd[-1] == "fix-it"

    def test_budget_zero_is_passed(self):
        """budget=0: 0 is not None, so the flag IS passed — discriminates truthiness bug."""
        runner = StubRunner(
            name="zero-budget",
            cli="cli",
            arg_map={
                "model": "--model",
                "budget": "--max-budget-usd",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(model="m", prompt="p", budget=0)

        # budget=0 is NOT None, so the flag + value are present
        assert "--max-budget-usd" in cmd
        # The value "0" must appear after --max-budget-usd
        budget_idx = cmd.index("--max-budget-usd")
        assert cmd[budget_idx + 1] == "0"

    def test_empty_tools_not_passed(self):
        """tools=[] is falsy, so --allowedTools is NOT in command."""
        runner = StubRunner(
            name="no-tools",
            cli="cli",
            arg_map={
                "model": "--model",
                "tools": "--allowedTools",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(model="m", prompt="p", tools=[])

        assert "--allowedTools" not in cmd
        # The rest of the command is still intact
        assert "--" in cmd
        assert cmd[-1] == "p"

    def test_budget_none_not_passed(self):
        """budget=None (default) does NOT produce the flag."""
        runner = StubRunner(
            name="no-budget",
            cli="cli",
            arg_map={
                "model": "--model",
                "budget": "--max-budget-usd",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(model="m", prompt="p")

        assert "--max-budget-usd" not in cmd
        assert cmd[-1] == "p"

    def test_system_prompt_empty_not_passed(self):
        """system_prompt="" is falsy, so --system-prompt is NOT in command."""
        runner = StubRunner(
            name="no-sys",
            cli="cli",
            arg_map={
                "model": "--model",
                "system_prompt": "--system-prompt",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(model="m", prompt="p", system_prompt="")

        assert "--system-prompt" not in cmd

    def test_mcp_config_empty_not_passed(self):
        """mcp_config="" is falsy, so --mcp-config is NOT in command."""
        runner = StubRunner(
            name="no-mcp",
            cli="cli",
            arg_map={
                "model": "--model",
                "mcp_config": "--mcp-config",
                "prompt_separator": "--",
            },
        )

        cmd = runner.build_command(model="m", prompt="p", mcp_config="")

        assert "--mcp-config" not in cmd


class TestPrependSystemPrompt:
    """codex `exec` has no --system-prompt flag, so a runner with
    prepend_system_prompt=True must fold the system prompt INTO the positional
    prompt rather than drop it. A silent drop would be a measurement bug (the
    experimental arm would lose its instructions without anyone noticing).
    """

    def _codex_like(self):
        return StubRunner(
            name="codex-like",
            cli="codex",
            default_args=["exec"],
            arg_map={"model": "-m", "prompt_separator": "--"},
            prepend_system_prompt=True,
        )

    def test_prepends_system_prompt_to_positional(self):
        cmd = self._codex_like().build_command(
            model="m", prompt="USER", system_prompt="SYS"
        )
        assert "--system-prompt" not in cmd  # no flag — codex has none
        assert cmd[-1] == "SYS\n\nUSER"  # folded into the positional prompt
        sep_idx = cmd.index("--")
        assert cmd[sep_idx + 1] == "SYS\n\nUSER"

    def test_no_system_prompt_leaves_prompt_unchanged(self):
        cmd = self._codex_like().build_command(model="m", prompt="USER")
        assert cmd[-1] == "USER"

    def test_default_runner_does_not_prepend(self):
        """prepend_system_prompt defaults False — a flag-style runner is unaffected."""
        runner = StubRunner(
            name="claude-like",
            cli="claude",
            arg_map={
                "model": "--model",
                "system_prompt": "--system-prompt",
                "prompt_separator": "--",
            },
        )
        cmd = runner.build_command(model="m", prompt="USER", system_prompt="SYS")
        assert "--system-prompt" in cmd
        assert cmd[-1] == "USER"  # positional prompt NOT modified
