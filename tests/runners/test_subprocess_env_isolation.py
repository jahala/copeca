"""Test SubprocessRunner env isolation — BASE_ENV_ALLOWLIST correctness.

Engineering.md §4: env construction belongs at the I/O boundary (SUPER S).
The child must never inherit ambient hooks or CLAUDE_*/MCP_* vars.
"""

import json
import sys
from unittest.mock import patch

from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner


class JsonEnvParser:
    """Parser that deserializes stdout as JSON (our env-dump subprocess emits JSON)."""

    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout.strip(), duration_ms=0)


_CMD = [
    sys.executable,
    "-c",
    "import os, json; print(json.dumps(dict(os.environ)))",
]


def _make_runner() -> SubprocessRunner:
    return SubprocessRunner(
        name="env-test",
        cli=sys.executable,
        default_args=[],
        arg_map={"prompt_separator": ""},
        parser=JsonEnvParser(),
    )


class TestBaseEnvAllowlist:
    """The child env must be built from the allowlist, not the full host env."""

    def test_ambient_hook_vars_are_absent_from_child(self) -> None:
        """CLAUDE_CODE_CUSTOM_HOOK and MCP_SERVER_URL must not reach the child."""
        hostile_env = {
            "CLAUDE_CODE_CUSTOM_HOOK": "http://evil.example.com/hook",
            "MCP_SERVER_URL": "ws://evil.example.com/mcp",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
        }
        runner = _make_runner()

        with patch.dict("os.environ", hostile_env, clear=True):
            result = runner.run(_CMD)

        child_env: dict[str, str] = json.loads(result.result_text)
        assert "CLAUDE_CODE_CUSTOM_HOOK" not in child_env, (
            "Ambient hook var must be excluded by the allowlist"
        )
        assert "MCP_SERVER_URL" not in child_env, "MCP server URL must be excluded by the allowlist"

    def test_allowed_infra_vars_are_present_in_child(self) -> None:
        """PATH, HOME, and ANTHROPIC_API_KEY must survive to the child (real runs need them)."""
        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "CLAUDE_CODE_CUSTOM_HOOK": "should-be-stripped",
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD)

        child_env: dict[str, str] = json.loads(result.result_text)
        assert "PATH" in child_env, "PATH must be present in child env"
        assert "HOME" in child_env, "HOME must be present in child env"
        assert "ANTHROPIC_API_KEY" in child_env, (
            "ANTHROPIC_API_KEY must be present so real agent runs work"
        )

    def test_explicit_env_kwarg_reaches_child(self) -> None:
        """A key passed via env=... must appear in the child env (mode.env wiring)."""
        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD, env={"MODE_TOOL_VAR": "x"})

        child_env: dict[str, str] = json.loads(result.result_text)
        assert child_env.get("MODE_TOOL_VAR") == "x", "Key passed via env= kwarg must reach child"

    def test_explicit_env_overrides_allowlist_value(self) -> None:
        """An env= key that also appears in the allowlist must use the explicit value."""
        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
            "ANTHROPIC_API_KEY": "original-key",
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD, env={"ANTHROPIC_API_KEY": "override-key"})

        child_env: dict[str, str] = json.loads(result.result_text)
        assert child_env["ANTHROPIC_API_KEY"] == "override-key", (
            "Explicit env= must win over the allowlist value"
        )

    def test_claudecode_var_excluded(self) -> None:
        """CLAUDECODE must not appear — it was excluded before; still excluded now."""
        base_env = {
            "CLAUDECODE": "1",
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD)

        child_env: dict[str, str] = json.loads(result.result_text)
        assert "CLAUDECODE" not in child_env

    def test_lc_star_vars_pass_through(self) -> None:
        """LC_* locale vars must be forwarded (non-ASCII repos need them)."""
        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/testuser",
            "LC_ALL": "en_US.UTF-8",
            "LC_CTYPE": "en_US.UTF-8",
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD)

        child_env: dict[str, str] = json.loads(result.result_text)
        assert child_env.get("LC_ALL") == "en_US.UTF-8"
        assert child_env.get("LC_CTYPE") == "en_US.UTF-8"

    def test_arm_env_home_overrides_host_home(self) -> None:
        """ISO-2: an arm env HOME=/tmp/foo must override the allowlisted host HOME.

        _build_child_env copies HOST HOME from the allowlist, then merges *extra*
        on top — so the arm-env HOME must win (extra is merged last).
        """
        host_home = "/home/real-user"
        arm_home = "/tmp/copeca-home-abc123"
        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": host_home,
        }
        runner = _make_runner()

        with patch.dict("os.environ", base_env, clear=True):
            result = runner.run(_CMD, env={"HOME": arm_home})

        child_env: dict[str, str] = json.loads(result.result_text)
        assert child_env.get("HOME") == arm_home, (
            "Arm env HOME must override the allowlisted host HOME in the child env"
        )
