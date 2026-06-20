"""Test per-arm harness provisioning for copeca benchmark modes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from copeca.config.models import Mode
from copeca.orchestration.state import ArmHarness, provision_arm


# ── Mode factories ────────────────────────────────────────────────────────────


def _mode(**kwargs: object) -> Mode:
    """Minimal valid Mode — tools list satisfies 'at least one path' validator."""
    defaults: dict[str, object] = {
        "name": "test_mode",
        "description": "test",
        "tools": ["Bash", "Read"],
    }
    defaults.update(kwargs)
    return Mode(**defaults)  # type: ignore[arg-type]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBaselineModeCleanHarness:
    def test_baseline_returns_clean_harness(self, tmp_path: Path) -> None:
        """Baseline mode (no integration paths) → env empty, config_dir None, wrapper None."""
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert harness.env == {}
        assert harness.config_dir is None
        assert harness.wrapper is None

    def test_baseline_does_not_create_arms_dir(self, tmp_path: Path) -> None:
        """Baseline produces no side effects on the worktree."""
        mode = _mode(name="baseline")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        provision_arm(mode, worktree)

        arms_dir = worktree / ".copeca-arms"
        assert not arms_dir.exists()


class TestEnvModeSetsEnv:
    def test_gateway_mode_sets_env(self, tmp_path: Path) -> None:
        """Gateway mode → env contains ANTHROPIC_BASE_URL."""
        mode = _mode(
            name="gateway",
            env={"ANTHROPIC_BASE_URL": "http://localhost:8080/v1"},
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert harness.env == {"ANTHROPIC_BASE_URL": "http://localhost:8080/v1"}

    def test_env_is_a_copy_not_a_reference(self, tmp_path: Path) -> None:
        """Mutating the returned env dict does not affect the mode."""
        mode = _mode(
            name="gateway",
            env={"ANTHROPIC_BASE_URL": "http://localhost:8080/v1"},
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)
        harness.env["EXTRA"] = "should-not-persist"

        # Original mode env is unchanged
        assert mode.env == {"ANTHROPIC_BASE_URL": "http://localhost:8080/v1"}


class TestWrapperModeSetsWrapper:
    def test_headroom_mode_sets_wrapper(self, tmp_path: Path) -> None:
        """Headroom mode → wrapper list is returned."""
        mode = _mode(
            name="headroom",
            wrapper=["headroom", "run", "--compress"],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert harness.wrapper == ["headroom", "run", "--compress"]

    def test_wrapper_is_a_copy_not_a_reference(self, tmp_path: Path) -> None:
        """Mutating the returned wrapper list does not affect the mode."""
        mode = _mode(
            name="headroom",
            wrapper=["headroom", "run", "--compress"],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)
        harness.wrapper.append("--debug")  # type: ignore[union-attr]

        assert mode.wrapper == ["headroom", "run", "--compress"]


class TestAgentConfigCopiesSettings:
    def test_rtk_mode_creates_config_dir_and_copies_settings(
        self, tmp_path: Path
    ) -> None:
        """RTK mode creates config dir and copies settings file."""
        settings = {"hooks": {"PreToolUse": [{"command": "rtk compress"}]}}
        settings_file = tmp_path / "rtk-settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = _mode(name="rtk", agent_config=str(settings_file))
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert harness.config_dir is not None
        assert harness.config_dir.exists()
        # The config dir should be under .copeca-arms/arm/config/
        assert ".copeca-arms" in harness.config_dir.parts

        copied_file = harness.config_dir / "rtk-settings.json"
        assert copied_file.exists()
        copied_data = json.loads(copied_file.read_text())
        assert copied_data == settings

    def test_missing_settings_file_raises(self, tmp_path: Path) -> None:
        """Nonexistent agent_config file raises FileNotFoundError."""
        mode = _mode(
            name="rtk", agent_config=str(tmp_path / "nonexistent.json")
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        with pytest.raises(FileNotFoundError, match="agent_config file not found"):
            provision_arm(mode, worktree)


class TestSetupRunsCommand:
    def test_indexed_mode_runs_setup_command(self, tmp_path: Path) -> None:
        """Indexed mode runs setup command; verify side effect."""
        marker = tmp_path / "marker.txt"
        mode = _mode(
            name="indexed",
            setup=[f"echo done > {marker}"],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert marker.exists()
        assert marker.read_text().strip() == "done"
        # Harness is still returned
        assert isinstance(harness, ArmHarness)

    def test_setup_runs_in_worktree_directory(self, tmp_path: Path) -> None:
        """Setup commands execute with cwd set to the worktree."""
        mode = _mode(
            name="indexed",
            setup=["pwd > cwd_check.txt"],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        provision_arm(mode, worktree)

        cwd_file = worktree / "cwd_check.txt"
        assert cwd_file.exists()
        written_cwd = Path(cwd_file.read_text().strip())
        assert written_cwd.resolve() == worktree.resolve()


class TestSetupCommandFailureRaises:
    def test_failing_setup_command_raises_runtimeerror(self, tmp_path: Path) -> None:
        """Setup command that exits non-zero raises RuntimeError."""
        mode = _mode(
            name="bad-indexed",
            setup=["exit 1"],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        with pytest.raises(RuntimeError, match="Setup command"):
            provision_arm(mode, worktree)

    def test_first_command_fails_second_never_runs(self, tmp_path: Path) -> None:
        """When the first setup command fails, subsequent commands are not executed."""
        marker = tmp_path / "second_ran.txt"
        mode = _mode(
            name="bad-indexed",
            setup=[
                "exit 1",
                f"echo ran > {marker}",
            ],
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        with pytest.raises(RuntimeError):
            provision_arm(mode, worktree)

        assert not marker.exists()


class TestArmConfigDirIsIsolatedPerArm:
    def test_two_arms_get_different_config_dirs(self, tmp_path: Path) -> None:
        """Two different arm names get different config directories."""
        settings = {"hooks": {"PreToolUse": [{"command": "rtk compress"}]}}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = _mode(name="rtk", agent_config=str(settings_file))
        worktree = tmp_path / "repo"
        worktree.mkdir()

        baseline = provision_arm(mode, worktree, arm_name="baseline")
        experimental = provision_arm(mode, worktree, arm_name="experimental")

        assert baseline.config_dir is not None
        assert experimental.config_dir is not None
        assert baseline.config_dir != experimental.config_dir

        # Each has its own copy of the settings file
        assert (baseline.config_dir / "settings.json").exists()
        assert (experimental.config_dir / "settings.json").exists()

    def test_same_arm_name_is_idempotent(self, tmp_path: Path) -> None:
        """Calling provision_arm twice with the same arm name overwrites cleanly."""
        settings = {"version": 1}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = _mode(name="rtk", agent_config=str(settings_file))
        worktree = tmp_path / "repo"
        worktree.mkdir()

        first = provision_arm(mode, worktree, arm_name="my-arm")
        second = provision_arm(mode, worktree, arm_name="my-arm")

        assert first.config_dir == second.config_dir


class TestWorktreeNotModifiedByConfigCopy:
    def test_config_copy_does_not_modify_tracked_files(self, tmp_path: Path) -> None:
        """Copying settings does not modify tracked files in worktree.

        We verify this by creating a git repo in the worktree, recording
        the state, then running provision_arm and confirming the working tree
        is clean of unintended modifications.
        """
        worktree = tmp_path / "repo"
        worktree.mkdir()

        # Initialize a git repo so we can detect modifications
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=worktree, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@copeca.dev"],
            cwd=worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Copeca Test"],
            cwd=worktree,
            check=True,
        )
        (worktree / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=worktree, check=True
        )

        settings = {"hooks": {"PreToolUse": [{"command": "rtk compress"}]}}
        settings_file = tmp_path / "rtk-settings.json"
        settings_file.write_text(json.dumps(settings))

        mode = _mode(name="rtk", agent_config=str(settings_file))

        provision_arm(mode, worktree)

        # The .copeca-arms directory is untracked — verify no tracked files changed
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == ""

        # .copeca-arms should be the only untracked addition
        status = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        untracked = status.stdout.strip().split("\n")
        assert any(".copeca-arms" in u for u in untracked)


class TestMcpConfigOnly:
    def test_mcp_config_mode_provisions_harness(self, tmp_path: Path) -> None:
        """Mode with only mcp_config still creates the arms dir."""
        mode = _mode(
            name="mcp-test",
            mcp_config={"server": {"command": "npx", "args": ["-y", "@company/server"]}},
        )
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree)

        assert isinstance(harness, ArmHarness)
        # mcp_config itself is NOT stored in ArmHarness (caller handles it)
        # but the arms dir is created for potential use
        assert (worktree / ".copeca-arms" / "arm").exists()
