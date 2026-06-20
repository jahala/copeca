"""Test B — mcp_config materialization in provision_arm.

provision_arm must write mode.mcp_config (dict) as JSON to
arms_dir/mcp.json and set harness.mcp_config_path to that file's path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copeca.config.models import Mode
from copeca.orchestration.state import ArmHarness, provision_arm


def _mode(**kwargs: object) -> Mode:
    """Minimal valid Mode with at least one integration path."""
    defaults: dict[str, object] = {"name": "test", "tools": ["Bash"]}
    defaults.update(kwargs)
    return Mode(**defaults)  # type: ignore[arg-type]


class TestMcpMaterialization:
    """provision_arm must write mcp_config dict to disk and set mcp_config_path."""

    def test_mcp_config_written_as_json(self, tmp_path: Path) -> None:
        """mode.mcp_config dict is written to arms_dir/mcp.json."""
        mcp_dict = {
            "mcpServers": {
                "my-server": {
                    "command": "npx",
                    "args": ["-y", "@company/mcp-server"],
                }
            }
        }
        mode = _mode(name="mcpmode", mcp_config=mcp_dict)
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, arm_name="arm")

        # The file must exist under the per-arm directory
        mcp_file = worktree / ".copeca-arms" / "arm" / "mcp.json"
        assert mcp_file.exists(), f"mcp.json must be written at {mcp_file}"

        parsed = json.loads(mcp_file.read_text())
        assert parsed == mcp_dict, (
            "Written JSON must round-trip to the original dict"
        )

    def test_harness_mcp_config_path_set(self, tmp_path: Path) -> None:
        """provision_arm sets harness.mcp_config_path to the written file's path."""
        mcp_dict = {"mcpServers": {"s": {"command": "uvx", "args": ["mcp-server"]}}}
        mode = _mode(name="mcpmode", mcp_config=mcp_dict)
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, arm_name="arm")

        assert harness.mcp_config_path is not None, (
            "harness.mcp_config_path must be set when mode.mcp_config is provided"
        )
        path = Path(harness.mcp_config_path)
        assert path.exists(), "mcp_config_path must point at the written file"
        assert path.name == "mcp.json"

    def test_mcp_config_path_none_when_no_mcp_config(self, tmp_path: Path) -> None:
        """When mode has no mcp_config, harness.mcp_config_path must be None."""
        mode = _mode(name="envonly", env={"K": "v"})
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, arm_name="arm")

        assert harness.mcp_config_path is None

    def test_mcp_config_arms_dir_created(self, tmp_path: Path) -> None:
        """The per-arm arms_dir is created when mode.mcp_config is the only path."""
        mcp_dict = {"mcpServers": {}}
        mode = _mode(name="mcponly", mcp_config=mcp_dict)
        worktree = tmp_path / "repo"
        worktree.mkdir()

        provision_arm(mode, worktree, arm_name="x")

        arms_dir = worktree / ".copeca-arms" / "x"
        assert arms_dir.exists(), "arms_dir must be created for mcp_config-only mode"

    def test_mcp_config_path_matches_actual_file(self, tmp_path: Path) -> None:
        """harness.mcp_config_path resolves to the same file as arms_dir/mcp.json."""
        mcp_dict = {"mcpServers": {"a": {"command": "cmd"}}}
        mode = _mode(name="m", mcp_config=mcp_dict)
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, arm_name="myarm")

        expected = worktree / ".copeca-arms" / "myarm" / "mcp.json"
        assert Path(harness.mcp_config_path).resolve() == expected.resolve()

    def test_baseline_mode_no_mcp_written(self, tmp_path: Path) -> None:
        """Baseline (has_paths False) must not create any mcp.json."""
        # tools=['Bash'] passes the validator but has_paths guard uses mcp_config etc
        mode = _mode(name="baseline")  # only tools — has_paths is False
        worktree = tmp_path / "repo"
        worktree.mkdir()

        harness = provision_arm(mode, worktree, arm_name="arm")

        assert harness.mcp_config_path is None
        arms_dir = worktree / ".copeca-arms"
        assert not arms_dir.exists()
