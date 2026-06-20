"""Test load_runner — runner YAML interface loading (config-driven CLI support).

Mirrors test_loader.py's TestLoadMode: load_runner resolves <dir>/<name>.yaml,
parses the interface block, and returns a structured RunnerConfig exposing
pricing + the CLI interface (cli, default_args, arg_map, config_dir_env, parser).
"""

from pathlib import Path

import pytest

from copeca.config.loader import load_runner
from copeca.config.models import RunnerConfig
from copeca.config.resources import data_path

DEFAULT_RUNNERS_DIR = data_path("defaults", "runners")


class TestLoadRunnerClaude:
    """load_runner('claude') returns the verified Claude CLI interface."""

    def test_returns_runner_config(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert isinstance(rc, RunnerConfig)

    def test_cli_defaults_to_name(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.cli == "claude"

    def test_default_args_carry_verified_flags(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert "-p" in rc.default_args
        assert "--output-format" in rc.default_args
        assert "stream-json" in rc.default_args
        assert "--dangerously-skip-permissions" in rc.default_args

    def test_drops_bogus_no_session_persistence_flag(self):
        """The previously hardcoded --no-session-persistence is NOT a real
        Claude flag and must not appear in the config."""
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert "--no-session-persistence" not in rc.default_args

    def test_arg_map_maps_model_and_friends(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.arg_map["model"] == "--model"
        assert rc.arg_map["budget"] == "--max-budget-usd"
        assert rc.arg_map["system_prompt"] == "--system-prompt"
        assert rc.arg_map["mcp_config"] == "--mcp-config"
        assert rc.arg_map["prompt_separator"] == "--"

    def test_config_dir_env(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.config_dir_env == "CLAUDE_CONFIG_DIR"

    def test_parser_name(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.parser == "stream_json"

    def test_pricing_still_present(self):
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.pricing is not None
        assert "claude-sonnet-4-6" in rc.pricing


class TestLoadRunnerResolution:
    """Resolution semantics mirror load_mode (default dir, first-wins, missing)."""

    def test_default_dir_resolves_regardless_of_cwd(self, monkeypatch, tmp_path):
        """With no runner_dirs, load_runner resolves the packaged defaults/runners."""
        monkeypatch.chdir(tmp_path)
        rc = load_runner("claude")
        assert rc.cli == "claude"

    def test_missing_runner_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_runner("does-not-exist-xyz", runner_dirs=[DEFAULT_RUNNERS_DIR])

    def test_first_existing_dir_wins(self, tmp_path):
        first = tmp_path / "first"
        first.mkdir()
        (first / "custom.yaml").write_text(
            "runner:\n"
            "  cli: custom-bin\n"
            "  default_args: [run]\n"
            "  arg_map: {model: -m}\n"
            "  parser: stream_json\n"
        )
        rc = load_runner("custom", runner_dirs=[first, DEFAULT_RUNNERS_DIR])
        assert rc.cli == "custom-bin"


class TestLoadRunnerCustomCli:
    """A YAML for a different CLI is loaded with its own interface (config-driven)."""

    @pytest.fixture
    def fakecli_dir(self, tmp_path):
        d = tmp_path / "runners"
        d.mkdir()
        (d / "fakecli.yaml").write_text(
            "pricing:\n"
            "  fake-model-1:\n"
            "    input: 1.0\n"
            "    output: 2.0\n"
            "    cache_creation: 1.0\n"
            "    cache_read: 0.5\n"
            '    updated: "2026-06-20"\n'
            "runner:\n"
            "  cli: fakecli\n"
            "  default_args: [run, --json]\n"
            "  arg_map: {model: -m, prompt_separator: --}\n"
            "  parser: stream_json\n"
        )
        return d

    def test_loads_fake_cli_interface(self, fakecli_dir):
        rc = load_runner("fakecli", runner_dirs=[fakecli_dir])
        assert rc.cli == "fakecli"
        assert rc.default_args == ["run", "--json"]
        assert rc.arg_map["model"] == "-m"
        assert rc.parser == "stream_json"
        assert rc.pricing is not None
        assert "fake-model-1" in rc.pricing

    def test_cli_defaults_to_stem_when_omitted(self, tmp_path):
        """When the YAML omits `cli`, it defaults to the file stem (the name)."""
        d = tmp_path / "runners"
        d.mkdir()
        (d / "mycli.yaml").write_text(
            "runner:\n"
            "  default_args: [go]\n"
            "  arg_map: {model: --model}\n"
            "  parser: stream_json\n"
        )
        rc = load_runner("mycli", runner_dirs=[d])
        assert rc.cli == "mycli"

    def test_invoke_template_passed_through(self, tmp_path):
        """A CLI declaring invoke_template (instead of arg_map) is loaded as-is."""
        d = tmp_path / "runners"
        d.mkdir()
        (d / "tplcli.yaml").write_text(
            "runner:\n"
            "  cli: tplcli\n"
            '  invoke_template: "{cli} exec --json -m {model} -- {prompt}"\n'
            "  parser: stream_json\n"
        )
        rc = load_runner("tplcli", runner_dirs=[d])
        # Passed through verbatim — {cli}/{model}/{prompt} are resolved later at
        # build_command time, not at load time.
        assert rc.invoke_template == "{cli} exec --json -m {model} -- {prompt}"
