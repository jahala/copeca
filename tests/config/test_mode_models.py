"""Test Mode model — integration paths and validation.

These are pure unit tests: no I/O, no subprocess, no filesystem.
"""

import pytest
from pydantic import ValidationError

from copeca.config.models import Mode


class TestModeConstruction:
    """Mode(name, ...) constructs with at least one integration path."""

    def test_mode_with_mcp_config_validates(self):
        mode = Mode(
            name="mcp_server",
            description="Tool connects via MCP server",
            mcp_config={"command": "npx", "args": ["-y", "my-server"]},
        )
        assert mode.name == "mcp_server"
        assert mode.mcp_config == {"command": "npx", "args": ["-y", "my-server"]}

    def test_mode_with_env_validates(self):
        mode = Mode(
            name="env_proxy",
            description="Tool connects through env vars",
            env={"API_KEY": "test-key", "ENDPOINT": "https://api.example.com"},
        )
        assert mode.name == "env_proxy"
        assert mode.env == {"API_KEY": "test-key", "ENDPOINT": "https://api.example.com"}

    def test_mode_with_agent_config_validates(self):
        mode = Mode(
            name="config_overlay",
            description="Agent settings overlay",
            agent_config="settings/custom.toml",
        )
        assert mode.name == "config_overlay"
        assert mode.agent_config == "settings/custom.toml"

    def test_mode_with_wrapper_validates(self):
        mode = Mode(
            name="wrapper_mode",
            description="Command prefix wrapper",
            wrapper=["env", "DEBUG=1"],
        )
        assert mode.name == "wrapper_mode"
        assert mode.wrapper == ["env", "DEBUG=1"]

    def test_mode_with_setup_validates(self):
        mode = Mode(
            name="setup_mode",
            description="Runs setup commands per worktree",
            setup=["pip install -e .", "npm ci"],
        )
        assert mode.name == "setup_mode"
        assert mode.setup == ["pip install -e .", "npm ci"]

    def test_mode_with_tools_only_validates(self):
        mode = Mode(
            name="baseline",
            description="Baseline mode with just tool list",
            tools=["copeca-baseline-agent"],
        )
        assert mode.name == "baseline"
        assert mode.tools == ["copeca-baseline-agent"]

    def test_mode_with_none_of_any_raises(self):
        with pytest.raises(ValidationError, match="at least one integration path"):
            Mode(
                name="empty_mode",
                description="This should fail",
            )

    def test_mode_with_two_paths_validates(self):
        mode = Mode(
            name="multi_path",
            description="MCP + env combined",
            mcp_config={"command": "npx", "args": ["-y", "my-server"]},
            env={"API_KEY": "test-key"},
        )
        assert mode.name == "multi_path"
        assert mode.mcp_config is not None
        assert mode.env is not None

    def test_name_pattern_enforced(self):
        with pytest.raises(ValidationError, match="name"):
            Mode(
                name="Invalid Name!",
                description="This should fail",
                tools=["some-tool"],
            )
