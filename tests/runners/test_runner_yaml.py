"""Tests for the runner YAML interface block in defaults/runners/claude.yaml.

The packaged claude.yaml must carry the verified Claude CLI interface so the
runner is constructed from data, not from hardcoded flags in cli.py.
"""

import yaml

from copeca.config.resources import data_path

CLAUDE_YAML = data_path("defaults", "runners", "claude.yaml")


def _load() -> dict:
    with open(CLAUDE_YAML) as f:
        return yaml.safe_load(f)


class TestClaudeRunnerInterfaceBlock:
    def test_has_runner_block(self):
        doc = _load()
        assert "runner" in doc, "claude.yaml must declare a `runner:` interface block"

    def test_pricing_preserved(self):
        doc = _load()
        assert "pricing" in doc

    def test_default_args_verified(self):
        doc = _load()
        default_args = doc["runner"]["default_args"]
        assert "-p" in default_args
        assert "--output-format" in default_args
        assert "stream-json" in default_args
        assert "--verbose" in default_args
        assert "--dangerously-skip-permissions" in default_args
        # The bogus flag from the old hardcoded set must be gone.
        assert "--no-session-persistence" not in default_args

    def test_arg_map_verified(self):
        doc = _load()
        arg_map = doc["runner"]["arg_map"]
        assert arg_map["model"] == "--model"
        assert arg_map["budget"] == "--max-budget-usd"
        assert arg_map["system_prompt"] == "--system-prompt"
        assert arg_map["mcp_config"] == "--mcp-config"
        assert arg_map["prompt_separator"] == "--"

    def test_config_dir_env_verified(self):
        doc = _load()
        assert doc["runner"]["config_dir_env"] == "CLAUDE_CONFIG_DIR"

    def test_parser_name(self):
        doc = _load()
        assert doc["runner"]["parser"] == "stream_json"
