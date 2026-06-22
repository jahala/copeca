"""Tests for ISO-3: claude.yaml isolation: block — data correctness + build_command wiring.

Verifies that:
  - load_runner("claude") produces an IsolationSpec with every expected field populated.
  - build_command with a baseline (mcp_config=None) includes --strict-mcp-config and
    --no-session-persistence, both appearing BEFORE the "--" prompt separator.
  - build_command with mcp_config set includes both --mcp-config <path> AND
    --strict-mcp-config.

Architecture §13.4: the isolation: block is data; the engine reads it uniformly with no
per-CLI branches. These tests guard the data, not the engine.
"""

from __future__ import annotations

from copeca.cli import build_runner
from copeca.config.loader import load_runner
from copeca.config.models import IsolationSpec
from copeca.config.resources import data_path

DEFAULT_RUNNERS_DIR = data_path("defaults", "runners")


# ── Isolation data correctness ─────────────────────────────────────────────────


class TestClaudeIsolationSpec:
    """load_runner("claude") must carry a fully-populated IsolationSpec."""

    def _cfg(self):
        return load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])

    def test_isolation_is_isolation_spec(self):
        assert isinstance(self._cfg().isolation, IsolationSpec)

    def test_config_home_env(self):
        assert self._cfg().isolation.config_home_env == "CLAUDE_CONFIG_DIR"

    def test_strict_mcp_flags(self):
        assert self._cfg().isolation.strict_mcp_flags == ["--strict-mcp-config"]

    def test_disable_session_flags(self):
        assert self._cfg().isolation.disable_session_flags == ["--no-session-persistence"]

    def test_disable_ambient_env(self):
        assert self._cfg().isolation.disable_ambient_env == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}

    def test_disable_telemetry_env(self):
        assert self._cfg().isolation.disable_telemetry_env == {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
        }

    def test_ambient_files(self):
        assert self._cfg().isolation.ambient_files == ["CLAUDE.md", "CLAUDE.local.md"]

    def test_requires_api_key_env(self):
        assert self._cfg().isolation.requires_api_key_env == "ANTHROPIC_API_KEY"

    def test_version_cmd(self):
        assert self._cfg().isolation.version_cmd == ["claude", "--version"]


# ── build_command wiring ───────────────────────────────────────────────────────


def _make_runner():
    """Construct a SubprocessRunner from the real claude.yaml — same path as production."""
    return build_runner("claude", timeout=300, runner_dirs=[DEFAULT_RUNNERS_DIR])


class TestClaudeBuildCommandBaseline:
    """Baseline (no mcp_config): isolation flags must be present and ordered correctly."""

    def test_strict_mcp_flag_present(self):
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            isolation=runner.isolation,
        )
        assert "--strict-mcp-config" in cmd

    def test_no_session_persistence_flag_present(self):
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            isolation=runner.isolation,
        )
        assert "--no-session-persistence" in cmd

    def test_isolation_flags_before_prompt_separator(self):
        """Both isolation flags must appear before the '--' separator."""
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="my-prompt",
            isolation=runner.isolation,
        )
        sep_idx = cmd.index("--")
        strict_idx = cmd.index("--strict-mcp-config")
        session_idx = cmd.index("--no-session-persistence")
        assert strict_idx < sep_idx, "--strict-mcp-config must appear before '--'"
        assert session_idx < sep_idx, "--no-session-persistence must appear before '--'"

    def test_no_mcp_config_flag_for_baseline(self):
        """Baseline has no mcp_config — --mcp-config must not appear."""
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            isolation=runner.isolation,
        )
        assert "--mcp-config" not in cmd


class TestClaudeBuildCommandWithMcpConfig:
    """Tool arm (mcp_config set): both --mcp-config and --strict-mcp-config must appear."""

    def test_mcp_config_flag_present(self, tmp_path):
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text('{"mcpServers": {}}')
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            mcp_config=str(mcp_file),
            isolation=runner.isolation,
        )
        assert "--mcp-config" in cmd
        mcp_idx = cmd.index("--mcp-config")
        assert cmd[mcp_idx + 1] == str(mcp_file)

    def test_strict_mcp_flag_also_present_with_mcp_config(self, tmp_path):
        """--strict-mcp-config must accompany --mcp-config on the tool arm."""
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text('{"mcpServers": {}}')
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="hello",
            mcp_config=str(mcp_file),
            isolation=runner.isolation,
        )
        assert "--strict-mcp-config" in cmd

    def test_both_isolation_flags_before_prompt_separator_with_mcp_config(self, tmp_path):
        mcp_file = tmp_path / "mcp.json"
        mcp_file.write_text('{"mcpServers": {}}')
        runner = _make_runner()
        cmd = runner.build_command(
            model="claude-haiku-4-5",
            prompt="my-prompt",
            mcp_config=str(mcp_file),
            isolation=runner.isolation,
        )
        sep_idx = cmd.index("--")
        strict_idx = cmd.index("--strict-mcp-config")
        session_idx = cmd.index("--no-session-persistence")
        assert strict_idx < sep_idx
        assert session_idx < sep_idx
