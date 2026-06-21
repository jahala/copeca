"""Test D — MCP delivered as -c mcp_servers.* overrides (codex convention).

codex has no --mcp-config flag. Instead it accepts repeated:
  -c 'mcp_servers.<name>.command="<cmd>"'
  -c 'mcp_servers.<name>.args=[...]'

A runner sets `mcp_via_config_overrides: true` in its YAML. When
build_command receives an mcp_config JSON file path it READS the file,
then emits one pair of -c overrides per server. No --mcp-config flag appears.

Runners WITHOUT this flag continue to use the --mcp-config path mechanism
(claude) — they must be completely unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path

from copeca.runners.base import BaseRunner
from copeca.runners.parsers.base import RunResult

# ── Stub runner ─────────────────────────────────────────────────────────────


class StubRunner(BaseRunner):
    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout)

    def run(self, command: list[str], cwd: str | None = None) -> RunResult:
        return self.parse("")


def _codex_like_runner() -> StubRunner:
    """Runner that mirrors the codex YAML — no mcp_config in arg_map, uses overrides."""
    return StubRunner(
        name="codex-like",
        cli="codex",
        default_args=["exec", "--json"],
        arg_map={"model": "-m", "prompt_separator": "--"},
        prepend_system_prompt=True,
        mcp_via_config_overrides=True,
    )


def _claude_like_runner() -> StubRunner:
    """Runner that mirrors the claude YAML — uses --mcp-config file path."""
    return StubRunner(
        name="claude-like",
        cli="claude",
        default_args=["-p"],
        arg_map={
            "model": "--model",
            "mcp_config": "--mcp-config",
            "prompt_separator": "--",
        },
    )


# ── Test class: codex -c override emission ───────────────────────────────────


class TestMcpViaConfigOverrides:
    """When mcp_via_config_overrides=True, build_command translates the JSON file
    into -c mcp_servers.* pairs rather than passing --mcp-config."""

    def test_single_server_emits_command_and_args_overrides(
        self, tmp_path: Path
    ) -> None:
        """One server → two -c tokens: one for command, one for args."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/home/user/.cargo/bin/tilth",
                            "args": ["--mcp", "--edit"],
                        }
                    }
                }
            )
        )

        runner = _codex_like_runner()
        cmd = runner.build_command(
            model="gpt-5.5",
            prompt="find the bug",
            mcp_config=str(mcp_json),
        )

        # Must have -c for command
        assert "-c" in cmd, "Expected -c overrides in command"
        pairs = _extract_c_pairs(cmd)
        assert any(
            k == "mcp_servers.tilth.command" for k, _ in pairs
        ), f"Expected mcp_servers.tilth.command override; got pairs={pairs}"
        # Must have -c for args
        assert any(
            k == "mcp_servers.tilth.args" for k, _ in pairs
        ), f"Expected mcp_servers.tilth.args override; got pairs={pairs}"

        # Must NOT have --mcp-config anywhere
        assert "--mcp-config" not in cmd, (
            "--mcp-config must NOT appear when mcp_via_config_overrides is set"
        )

    def test_command_override_value_is_quoted_string(self, tmp_path: Path) -> None:
        """The command value must be formatted as: "mcp_servers.<n>.command=\"<cmd>\""""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {"mcpServers": {"mytool": {"command": "/usr/bin/mytool", "args": []}}}
            )
        )

        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="p", mcp_config=str(mcp_json)
        )

        pairs = _extract_c_pairs(cmd)
        cmd_pairs = [(k, v) for k, v in pairs if k == "mcp_servers.mytool.command"]
        assert len(cmd_pairs) == 1, f"Expected exactly one command override; got {pairs}"
        _, val = cmd_pairs[0]
        # Must be the full "mcp_servers.mytool.command=\"/usr/bin/mytool\"" token
        assert val == '/usr/bin/mytool', (
            f"command value must be the bare path without quoting noise; got {val!r}"
        )

    def test_args_override_value_is_json_array(self, tmp_path: Path) -> None:
        """The args value must be a JSON array string: '["--mcp", "--edit"]'."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/bin/tilth",
                            "args": ["--mcp", "--edit"],
                        }
                    }
                }
            )
        )

        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="p", mcp_config=str(mcp_json)
        )

        pairs = _extract_c_pairs(cmd)
        args_pairs = [(k, v) for k, v in pairs if k == "mcp_servers.tilth.args"]
        assert len(args_pairs) == 1, f"Expected exactly one args override; got {pairs}"
        _, val = args_pairs[0]
        # Must be valid JSON that round-trips to the original list
        parsed = json.loads(val)
        assert parsed == ["--mcp", "--edit"], (
            f"args override must be JSON array ['--mcp', '--edit']; got {val!r}"
        )

    def test_multiple_servers_emit_two_pairs_each(self, tmp_path: Path) -> None:
        """Two servers → four -c overrides total (command+args for each)."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "alpha": {"command": "/bin/alpha", "args": ["--a"]},
                        "beta": {"command": "/bin/beta", "args": []},
                    }
                }
            )
        )

        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="p", mcp_config=str(mcp_json)
        )

        pairs = _extract_c_pairs(cmd)
        keys = {k for k, _ in pairs}
        assert "mcp_servers.alpha.command" in keys
        assert "mcp_servers.alpha.args" in keys
        assert "mcp_servers.beta.command" in keys
        assert "mcp_servers.beta.args" in keys
        assert len(pairs) == 4, f"Expected 4 -c pairs for 2 servers; got {pairs}"

    def test_no_mcp_config_produces_no_overrides(self) -> None:
        """mcp_config=None → no -c overrides at all."""
        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="p", mcp_config=None
        )

        pairs = _extract_c_pairs(cmd)
        mcp_pairs = [(k, v) for k, v in pairs if "mcp_servers" in k]
        assert mcp_pairs == [], (
            f"No mcp_servers -c pairs expected when mcp_config=None; got {mcp_pairs}"
        )

    def test_prompt_still_last_with_overrides(self, tmp_path: Path) -> None:
        """The positional prompt must still be the last token even with -c overrides."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"s": {"command": "/bin/s", "args": []}}})
        )

        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="do the thing", mcp_config=str(mcp_json)
        )

        assert cmd[-1] == "do the thing", (
            f"Prompt must be last token; got cmd={cmd}"
        )

    def test_default_args_still_present_with_overrides(self, tmp_path: Path) -> None:
        """default_args (exec, --json) must still appear alongside -c overrides."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"s": {"command": "/bin/s", "args": []}}})
        )

        cmd = _codex_like_runner().build_command(
            model="gpt-5.5", prompt="p", mcp_config=str(mcp_json)
        )

        assert "exec" in cmd
        assert "--json" in cmd


# ── Test class: claude unaffected ───────────────────────────────────────────


class TestClaudeUnaffected:
    """Claude (mcp_via_config_overrides=False by default) must keep --mcp-config."""

    def test_claude_emits_mcp_config_flag(self, tmp_path: Path) -> None:
        """Claude still uses --mcp-config <path>, not -c overrides."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"s": {"command": "/bin/s", "args": []}}})
        )
        path = str(mcp_json)

        cmd = _claude_like_runner().build_command(
            model="claude-sonnet-4-6", prompt="task", mcp_config=path
        )

        assert "--mcp-config" in cmd, "claude must still use --mcp-config"
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == path, "path must follow --mcp-config"
        # No -c overrides
        pairs = _extract_c_pairs(cmd)
        mcp_pairs = [(k, v) for k, v in pairs if "mcp_servers" in k]
        assert mcp_pairs == [], (
            f"claude must NOT emit -c mcp_servers.* pairs; got {mcp_pairs}"
        )

    def test_claude_mcp_config_absent_when_none(self) -> None:
        """Claude with mcp_config=None: no --mcp-config in command."""
        cmd = _claude_like_runner().build_command(
            model="claude-sonnet-4-6", prompt="task", mcp_config=None
        )
        assert "--mcp-config" not in cmd


# ── Test class: real codex YAML ──────────────────────────────────────────────


class TestCodexYamlMcpOverrides:
    """The packaged codex.yaml runner must use -c overrides for MCP."""

    def test_codex_runner_emits_c_overrides_not_mcp_config_flag(
        self, tmp_path: Path
    ) -> None:
        """Real codex runner: given an mcp_config JSON, emits -c pairs, no --mcp-config."""
        from copeca.cli import build_runner
        from copeca.config.resources import data_path

        runner_dirs = [data_path("defaults", "runners")]
        runner = build_runner("codex", timeout=300, runner_dirs=runner_dirs)

        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/home/user/.cargo/bin/tilth",
                            "args": ["--mcp", "--edit"],
                        }
                    }
                }
            )
        )

        cmd = runner.build_command(
            model="gpt-5.5",
            prompt="find the bug",
            mcp_config=str(mcp_json),
        )

        assert "--mcp-config" not in cmd, (
            "codex must NOT emit --mcp-config (it has no such flag)"
        )
        pairs = _extract_c_pairs(cmd)
        assert any(k == "mcp_servers.tilth.command" for k, _ in pairs), (
            f"codex must emit -c mcp_servers.tilth.command; got pairs={pairs}"
        )
        assert any(k == "mcp_servers.tilth.args" for k, _ in pairs), (
            f"codex must emit -c mcp_servers.tilth.args; got pairs={pairs}"
        )

    def test_claude_runner_still_uses_mcp_config_flag(self, tmp_path: Path) -> None:
        """Real claude runner: --mcp-config still used, no regression."""
        from copeca.cli import build_runner
        from copeca.config.resources import data_path

        runner_dirs = [data_path("defaults", "runners")]
        runner = build_runner("claude", timeout=300, runner_dirs=runner_dirs)

        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"s": {"command": "/bin/s", "args": []}}})
        )
        path = str(mcp_json)

        cmd = runner.build_command(
            model="claude-sonnet-4-6", prompt="task", mcp_config=path
        )

        assert "--mcp-config" in cmd
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == path
        pairs = _extract_c_pairs(cmd)
        mcp_pairs = [(k, v) for k, v in pairs if "mcp_servers" in k]
        assert mcp_pairs == [], (
            "claude runner must NOT emit -c mcp_servers.* pairs"
        )


# ── Helper ───────────────────────────────────────────────────────────────────


def _extract_c_pairs(cmd: list[str]) -> list[tuple[str, str]]:
    """Extract (key, value) from all '-c key=value' pairs in the command.

    Returns list of (key_part, value_part) tuples.
    Each '-c' must be followed by 'key=value'.
    """
    pairs = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-c" and i + 1 < len(cmd):
            token = cmd[i + 1]
            if "=" in token:
                k, _, v = token.partition("=")
                pairs.append((k, v))
            i += 2
        else:
            i += 1
    return pairs
