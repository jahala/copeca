"""Tests for check_mode_runner_compat — mode<->runner compatibility warnings."""

from dataclasses import dataclass, field

from copeca.config.models import Mode
from copeca.orchestration.validation import check_mode_runner_compat


@dataclass
class FakeRunner:
    name: str = "claude"
    cli: str = "claude"
    arg_map: dict[str, str] = field(default_factory=dict)
    invoke_template: str = ""


def make_mode(**kwargs) -> Mode:
    """Build a Mode with default baseline (tools only) and overrides."""
    defaults = {
        "name": "test_mode",
        "tools": ["bash"],
    }
    defaults.update(kwargs)
    return Mode(**defaults)


class TestMcpConfigCompat:
    def test_mcp_config_without_runner_support_warns(self):
        """Mode with mcp_config, runner with no mcp_config support -> warning."""
        mode = make_mode(mcp_config={"server": "test"})
        runner = FakeRunner(name="codex", arg_map={})

        warnings = check_mode_runner_compat(mode, runner)

        assert len(warnings) >= 1
        mcp_warnings = [w for w in warnings if "mcp_config" in w]
        assert len(mcp_warnings) == 1
        assert "test_mode" in mcp_warnings[0]
        assert "codex" in mcp_warnings[0]

    def test_mcp_config_with_runner_support_no_warning(self):
        """Mode with mcp_config, runner with mcp_config in arg_map -> no warning."""
        mode = make_mode(mcp_config={"server": "test"})
        runner = FakeRunner(
            name="codex",
            arg_map={"mcp_config": "--mcp-config"},
        )

        warnings = check_mode_runner_compat(mode, runner)

        mcp_warnings = [w for w in warnings if "mcp_config" in w]
        assert mcp_warnings == []

    def test_mcp_config_in_invoke_template_no_warning(self):
        """Mode with mcp_config, runner with {mcp_config} in invoke_template -> no warning."""
        mode = make_mode(mcp_config={"server": "test"})
        runner = FakeRunner(
            name="codex",
            invoke_template="{cli} -p '{prompt}' --mcp {mcp_config}",
        )

        warnings = check_mode_runner_compat(mode, runner)

        mcp_warnings = [w for w in warnings if "mcp_config" in w]
        assert mcp_warnings == []


class TestAgentConfigCompat:
    def test_agent_config_warns(self):
        """Mode with agent_config -> warning about config dir."""
        mode = make_mode(agent_config="/path/to/config")
        runner = FakeRunner(name="claude")

        warnings = check_mode_runner_compat(mode, runner)

        agent_warnings = [w for w in warnings if "agent_config" in w]
        assert len(agent_warnings) == 1
        assert "test_mode" in agent_warnings[0]
        assert "--agent-config-dir" in agent_warnings[0]


class TestWrapperCompat:
    def test_wrapper_warns(self):
        """Mode with wrapper -> warning about command prefix."""
        mode = make_mode(wrapper=["sudo", "-E"])
        runner = FakeRunner(name="claude")

        warnings = check_mode_runner_compat(mode, runner)

        wrapper_warnings = [w for w in warnings if "wrapper" in w.lower()]
        assert len(wrapper_warnings) == 1
        assert "test_mode" in wrapper_warnings[0]
        assert "command prefix" in wrapper_warnings[0]


class TestEnvCompat:
    def test_env_with_claude_no_warning(self):
        """Mode with env, claude runner -> no warning (claude supports env)."""
        mode = make_mode(env={"FOO": "bar"})
        runner = FakeRunner(name="claude")

        warnings = check_mode_runner_compat(mode, runner)

        env_warnings = [w for w in warnings if "env" in w.lower()]
        assert env_warnings == []

    def test_env_with_unknown_runner_warns(self):
        """Mode with env, non-claude runner -> warning about env propagation."""
        mode = make_mode(env={"FOO": "bar"})
        runner = FakeRunner(name="codex")

        warnings = check_mode_runner_compat(mode, runner)

        env_warnings = [w for w in warnings if "env" in w.lower()]
        assert len(env_warnings) >= 1
        assert "test_mode" in env_warnings[0]
        assert "codex" in env_warnings[0]


class TestFullyCompatible:
    def test_fully_compatible_no_warnings(self):
        """Mode with tools only (baseline), runner with full arg_map -> no warnings."""
        mode = make_mode(tools=["bash", "read"])
        runner = FakeRunner(
            name="claude",
            arg_map={
                "model": "-m",
                "mcp_config": "--mcp-config",
                "system_prompt": "--system-prompt",
            },
        )

        warnings = check_mode_runner_compat(mode, runner)
        assert warnings == []


class TestAdvisoryWarnings:
    def test_warnings_are_advisory(self):
        """Warnings are returned as list; function never raises."""
        # Full test: all integration paths at once, no-support runner
        mode = make_mode(
            mcp_config={"server": "test"},
            agent_config="/tmp/config",
            wrapper=["timeout", "30"],
            env={"DEBUG": "1"},
        )
        runner = FakeRunner(
            name="codex",
            arg_map={},
            invoke_template="",
        )

        result = check_mode_runner_compat(mode, runner)
        assert isinstance(result, list)
        assert len(result) >= 3  # mcp_config, agent_config, wrapper, env

    def test_never_raises_with_minimal_runner(self):
        """Function never raises, even with objects missing expected attributes."""
        # Use actual Mode with just name + tools, and a bare object as runner
        mode = make_mode()

        @dataclass
        class BareRunner:
            name: str = "bare"

        runner = BareRunner()

        # Should not raise even though arg_map and invoke_template are missing
        result = check_mode_runner_compat(mode, runner)
        assert isinstance(result, list)


# ── Task 54: FakeMode dataclass tests ────────────────────────────────────
# Tests using plain dataclasses (not Pydantic Mode) to avoid
# validation overhead and test the function with minimal interface.


@dataclass
class FakeMode:
    """Plain dataclass matching the interface check_mode_runner_compat expects.

    No Pydantic validation — just the fields the function reads.
    """

    name: str = "test"
    mcp_config: dict | None = None
    env: dict | None = None
    agent_config: str | None = None
    wrapper: list | None = None
    tools: list = field(default_factory=list)


class TestCheckModeRunnerCompat:
    """check_mode_runner_compat with FakeMode dataclasses.

    These tests verify the function works with minimal objects matching
    the interface — no Pydantic validation, just duck-typing.
    """

    def test_mcp_config_with_arg_map_no_warning(self):
        mode = FakeMode(name="test", mcp_config={"command": "server"})
        runner = FakeRunner(arg_map={"mcp_config": "--mcp"})
        assert check_mode_runner_compat(mode, runner) == []

    def test_mcp_config_without_runner_support_warns(self):
        mode = FakeMode(name="test", mcp_config={"command": "server"})
        runner = FakeRunner(name="no-mcp-runner")
        warnings = check_mode_runner_compat(mode, runner)
        assert len(warnings) == 1
        assert "mcp_config" in warnings[0]
        assert "test" in warnings[0]
        assert "no-mcp-runner" in warnings[0]

    def test_mcp_config_in_invoke_template_no_warning(self):
        mode = FakeMode(name="test", mcp_config={"command": "server"})
        runner = FakeRunner(invoke_template="{cli} --mcp {mcp_config} -- {prompt}")
        assert check_mode_runner_compat(mode, runner) == []

    def test_agent_config_warns(self):
        mode = FakeMode(name="test", agent_config="settings.json")
        runner = FakeRunner()
        warnings = check_mode_runner_compat(mode, runner)
        assert len(warnings) == 1
        assert "agent_config" in warnings[0]

    def test_wrapper_warns(self):
        mode = FakeMode(name="test", wrapper=["prefix"])
        runner = FakeRunner()
        warnings = check_mode_runner_compat(mode, runner)
        assert len(warnings) == 1
        assert "wrapper" in warnings[0]

    def test_env_claude_no_warning(self):
        mode = FakeMode(name="test", env={"ANTHROPIC_BASE_URL": "http://x"})
        runner = FakeRunner(name="claude")
        assert check_mode_runner_compat(mode, runner) == []

    def test_env_non_claude_warns(self):
        mode = FakeMode(name="test", env={"ANTHROPIC_BASE_URL": "http://x"})
        runner = FakeRunner(name="codex")
        warnings = check_mode_runner_compat(mode, runner)
        assert len(warnings) == 1
        assert "env" in warnings[0]

    def test_fully_compatible_no_warnings(self):
        mode = FakeMode(name="baseline", tools=["Read"])
        runner = FakeRunner(arg_map={"mcp_config": "--mcp"})
        assert check_mode_runner_compat(mode, runner) == []

    def test_multiple_warnings_accumulate(self):
        """All four warning categories fire simultaneously on incompatible mode."""
        mode = FakeMode(
            name="multi",
            mcp_config={"command": "server"},
            agent_config="/tmp",
            wrapper=["timeout", "30"],
            env={"DEBUG": "1"},
        )
        runner = FakeRunner(name="codex", arg_map={}, invoke_template="")
        warnings = check_mode_runner_compat(mode, runner)
        # mcp_config + agent_config + wrapper + env
        assert len(warnings) == 4
        warning_text = " ".join(warnings).lower()
        assert "mcp_config" in warning_text
        assert "agent_config" in warning_text
        assert "wrapper" in warning_text
        assert "env" in warning_text
