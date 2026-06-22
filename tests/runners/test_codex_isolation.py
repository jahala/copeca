"""Tests for ISO-4: codex.yaml isolation block + clean-room verification.

Covers:
- codex runner YAML declares the expected IsolationSpec fields
- build_command for the BASELINE arm contains --ignore-user-config + --ephemeral,
  and no -c mcp_servers.* tokens
- build_command for the TOOL ARM (mcp_config provided) contains the -c
  mcp_servers.* override tokens produced by _mcp_config_overrides
- provision_arm sets CODEX_HOME and HOME on the returned harness env
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copeca.cli import build_runner
from copeca.config.loader import load_runner
from copeca.config.models import IsolationSpec, Mode
from copeca.config.resources import data_path
from copeca.orchestration.state import provision_arm

RUNNER_DIRS = [data_path("defaults", "runners")]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg():
    return load_runner("codex", runner_dirs=RUNNER_DIRS)


def _runner():
    return build_runner("codex", timeout=300, runner_dirs=RUNNER_DIRS)


def _extract_c_pairs(cmd: list[str]) -> list[tuple[str, str]]:
    """Extract (key, value) from all '-c key=value' pairs in a command list."""
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


def _mode(**kwargs: object) -> Mode:
    defaults: dict[str, object] = {
        "name": "baseline",
        "description": "clean baseline",
        "tools": ["Bash", "Read"],
    }
    defaults.update(kwargs)
    return Mode(**defaults)  # type: ignore[arg-type]


# ── IsolationSpec field assertions ────────────────────────────────────────────


class TestCodexIsolationSpec:
    """codex.yaml must declare the correct IsolationSpec fields (ISO-4 data layer)."""

    def test_config_home_env_is_codex_home(self) -> None:
        iso: IsolationSpec = _cfg().isolation
        assert iso.config_home_env == "CODEX_HOME", (
            "codex isolation must set config_home_env to CODEX_HOME"
        )

    def test_strict_mcp_flags_contains_ignore_user_config(self) -> None:
        iso: IsolationSpec = _cfg().isolation
        assert "--ignore-user-config" in iso.strict_mcp_flags, (
            "codex strict_mcp_flags must contain --ignore-user-config"
        )

    def test_requires_api_key_env_is_openai(self) -> None:
        iso: IsolationSpec = _cfg().isolation
        assert iso.requires_api_key_env == "OPENAI_API_KEY", (
            "codex isolation must require OPENAI_API_KEY"
        )

    def test_ambient_files_contains_agents_md(self) -> None:
        iso: IsolationSpec = _cfg().isolation
        assert "AGENTS.md" in iso.ambient_files, "codex ambient_files must include AGENTS.md"

    def test_version_cmd_is_codex_version(self) -> None:
        iso: IsolationSpec = _cfg().isolation
        assert iso.version_cmd == ["codex", "--version"], (
            "codex version_cmd must be ['codex', '--version']"
        )


# ── Baseline command (no mcp_config) ─────────────────────────────────────────


class TestCodexBaselineCommand:
    """BASELINE arm: --ignore-user-config + --ephemeral present; no -c mcp_servers."""

    def test_baseline_contains_ignore_user_config(self) -> None:
        """--ignore-user-config must appear even when no mcp_config is supplied."""
        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="find the bug",
            isolation=cfg.isolation,
        )
        assert "--ignore-user-config" in cmd, (
            "Baseline command must contain --ignore-user-config (strict_mcp_flags)"
        )

    def test_baseline_contains_ephemeral(self) -> None:
        """--ephemeral is in default_args; must be present for every invocation."""
        cmd = _runner().build_command(model="gpt-5.5", prompt="task")
        assert "--ephemeral" in cmd, (
            "--ephemeral must be in the baseline command (from default_args)"
        )

    def test_baseline_has_no_mcp_servers_overrides(self) -> None:
        """Baseline (mcp_config=None) must emit no -c mcp_servers.* tokens."""
        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="task",
            mcp_config=None,
            isolation=cfg.isolation,
        )
        pairs = _extract_c_pairs(cmd)
        mcp_pairs = [(k, v) for k, v in pairs if "mcp_servers" in k]
        assert mcp_pairs == [], f"Baseline must have no -c mcp_servers.* tokens; got {mcp_pairs}"


# ── Tool-arm command (mcp_config provided) ────────────────────────────────────


class TestCodexToolArmCommand:
    """TOOL ARM: -c mcp_servers.* override tokens are emitted; _mcp_config_overrides path."""

    def test_tool_arm_emits_command_override(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/x/tilth",
                            "args": ["--mcp"],
                        }
                    }
                }
            )
        )

        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="task",
            mcp_config=str(mcp_json),
            isolation=cfg.isolation,
        )

        pairs = _extract_c_pairs(cmd)
        assert any(k == "mcp_servers.tilth.command" for k, _ in pairs), (
            f"Tool arm must emit -c mcp_servers.tilth.command; got pairs={pairs}"
        )

    def test_tool_arm_emits_args_override(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/x/tilth",
                            "args": ["--mcp"],
                        }
                    }
                }
            )
        )

        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="task",
            mcp_config=str(mcp_json),
            isolation=cfg.isolation,
        )

        pairs = _extract_c_pairs(cmd)
        args_pairs = [(k, v) for k, v in pairs if k == "mcp_servers.tilth.args"]
        assert len(args_pairs) == 1, (
            f"Tool arm must emit exactly one -c mcp_servers.tilth.args; got {pairs}"
        )
        _, val = args_pairs[0]
        assert json.loads(val) == ["--mcp"], (
            f"args override must round-trip to ['--mcp']; got {val!r}"
        )

    def test_tool_arm_args_value_matches_mcp_config(self, tmp_path: Path) -> None:
        """The command value in the -c override must match the JSON's command field."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "tilth": {
                            "command": "/x/tilth",
                            "args": ["--mcp"],
                        }
                    }
                }
            )
        )

        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="task",
            mcp_config=str(mcp_json),
            isolation=cfg.isolation,
        )

        pairs = _extract_c_pairs(cmd)
        cmd_pairs = [(k, v) for k, v in pairs if k == "mcp_servers.tilth.command"]
        assert len(cmd_pairs) == 1
        _, val = cmd_pairs[0]
        assert val == "/x/tilth", f"command override value must be '/x/tilth'; got {val!r}"

    def test_tool_arm_has_no_mcp_config_flag(self, tmp_path: Path) -> None:
        """codex has no --mcp-config flag; it must never appear in the command."""
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"tilth": {"command": "/x/tilth", "args": ["--mcp"]}}})
        )

        cfg = _cfg()
        cmd = _runner().build_command(
            model="gpt-5.5",
            prompt="task",
            mcp_config=str(mcp_json),
            isolation=cfg.isolation,
        )

        assert "--mcp-config" not in cmd, "codex must never emit --mcp-config (it has no such flag)"


# ── provision_arm env ─────────────────────────────────────────────────────────


class TestCodexProvisionArmEnv:
    """provision_arm must set CODEX_HOME and HOME to the private home directory."""

    def test_provision_arm_sets_codex_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        cfg = _cfg()
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, isolation=cfg.isolation)

        assert "CODEX_HOME" in harness.env, (
            "provision_arm must set CODEX_HOME when config_home_env=CODEX_HOME"
        )

    def test_provision_arm_codex_home_equals_private_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        cfg = _cfg()
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, isolation=cfg.isolation)

        assert harness.env["CODEX_HOME"] == harness.private_home, (
            "CODEX_HOME must point to the same private home dir as HOME"
        )

    def test_provision_arm_sets_home_to_private_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        cfg = _cfg()
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, isolation=cfg.isolation)

        assert "HOME" in harness.env, "provision_arm must set HOME"
        assert harness.env["HOME"] == harness.private_home, (
            "HOME must point to the private home dir"
        )

    def test_provision_arm_raises_without_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provision_arm must raise before creating state if OPENAI_API_KEY is absent."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        cfg = _cfg()
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            provision_arm(mode, worktree, isolation=cfg.isolation)
