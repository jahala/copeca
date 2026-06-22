"""Test IsolationSpec — per-CLI clean-room descriptor attached to RunnerConfig.

Architecture §13.4: each runner YAML carries an isolation: block.
These are pure unit tests: no I/O, no subprocess, no filesystem.
"""

from copeca.config.loader import load_runner
from copeca.config.models import IsolationSpec, RunnerConfig
from copeca.config.resources import data_path

DEFAULT_RUNNERS_DIR = data_path("defaults", "runners")


class TestIsolationSpecDefaults:
    """A RunnerConfig with no isolation: block yields safe empty defaults."""

    def test_isolation_field_present_with_defaults(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert isinstance(rc.isolation, IsolationSpec)

    def test_config_home_env_defaults_to_none(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.config_home_env is None

    def test_strict_mcp_flags_defaults_to_empty_list(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.strict_mcp_flags == []

    def test_disable_ambient_env_defaults_to_empty_dict(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.disable_ambient_env == {}

    def test_disable_session_flags_defaults_to_empty_list(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.disable_session_flags == []

    def test_disable_telemetry_env_defaults_to_empty_dict(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.disable_telemetry_env == {}

    def test_ambient_files_defaults_to_empty_list(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.ambient_files == []

    def test_requires_api_key_env_defaults_to_none(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.requires_api_key_env is None

    def test_version_cmd_defaults_to_empty_list(self):
        rc = RunnerConfig(arg_map={"model": "--model"}, parser="stream_json")
        assert rc.isolation.version_cmd == []


class TestIsolationSpecRoundTrip:
    """A RunnerConfig with a full isolation: block round-trips into a typed IsolationSpec."""

    def test_full_isolation_block_round_trips(self):
        fields = {
            "cli": "claude",
            "arg_map": {"model": "--model", "prompt_separator": "--"},
            "parser": "stream_json",
            "isolation": {
                "config_home_env": "CLAUDE_CONFIG_DIR",
                "strict_mcp_flags": ["--strict-mcp-config"],
                "disable_ambient_env": {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
                "disable_session_flags": ["--no-session-persistence"],
                "disable_telemetry_env": {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
                "ambient_files": ["CLAUDE.md", "CLAUDE.local.md"],
                "requires_api_key_env": "ANTHROPIC_API_KEY",
                "version_cmd": ["claude", "--version"],
            },
        }
        rc = RunnerConfig.model_validate(fields)

        assert isinstance(rc.isolation, IsolationSpec)
        assert rc.isolation.config_home_env == "CLAUDE_CONFIG_DIR"
        assert rc.isolation.strict_mcp_flags == ["--strict-mcp-config"]
        assert rc.isolation.disable_ambient_env == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
        assert rc.isolation.disable_session_flags == ["--no-session-persistence"]
        assert rc.isolation.disable_telemetry_env == {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
        }
        assert rc.isolation.ambient_files == ["CLAUDE.md", "CLAUDE.local.md"]
        assert rc.isolation.requires_api_key_env == "ANTHROPIC_API_KEY"
        assert rc.isolation.version_cmd == ["claude", "--version"]

    def test_partial_isolation_block_leaves_other_fields_at_defaults(self):
        fields = {
            "arg_map": {"model": "--model"},
            "parser": "stream_json",
            "isolation": {
                "config_home_env": "CODEX_HOME",
                "requires_api_key_env": "OPENAI_API_KEY",
            },
        }
        rc = RunnerConfig.model_validate(fields)

        assert rc.isolation.config_home_env == "CODEX_HOME"
        assert rc.isolation.requires_api_key_env == "OPENAI_API_KEY"
        # unset fields stay at their safe defaults
        assert rc.isolation.strict_mcp_flags == []
        assert rc.isolation.disable_ambient_env == {}
        assert rc.isolation.ambient_files == []
        assert rc.isolation.version_cmd == []


class TestIsolationSpecUnknownKeys:
    """Unknown keys inside isolation: are silently ignored (Pydantic default, no extra=forbid)."""

    def test_unknown_key_in_isolation_is_ignored(self):
        fields = {
            "arg_map": {"model": "--model"},
            "parser": "stream_json",
            "isolation": {
                "config_home_env": "MY_HOME",
                "unknown_future_key": "some_value",
            },
        }
        # Should not raise — matches the codebase convention (no model_config extra=forbid)
        rc = RunnerConfig.model_validate(fields)
        assert rc.isolation.config_home_env == "MY_HOME"


class TestIsolationSpecViaLoadRunner:
    """load_runner() with a YAML containing isolation: returns a typed IsolationSpec."""

    def test_load_runner_claude_has_isolation_spec(self):
        """The packaged claude.yaml loader produces an IsolationSpec (defaults if no block)."""
        rc = load_runner("claude", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert isinstance(rc.isolation, IsolationSpec)

    def test_load_runner_with_isolation_yaml(self, tmp_path):
        d = tmp_path / "runners"
        d.mkdir()
        (d / "testcli.yaml").write_text(
            "runner:\n"
            "  cli: testcli\n"
            "  arg_map: {model: --model, prompt_separator: --}\n"
            "  parser: stream_json\n"
            "  isolation:\n"
            "    config_home_env: TESTCLI_HOME\n"
            "    strict_mcp_flags: [--strict-mcp-config]\n"
            "    requires_api_key_env: TEST_API_KEY\n"
            "    version_cmd: [testcli, --version]\n"
        )
        rc = load_runner("testcli", runner_dirs=[d])

        assert isinstance(rc.isolation, IsolationSpec)
        assert rc.isolation.config_home_env == "TESTCLI_HOME"
        assert rc.isolation.strict_mcp_flags == ["--strict-mcp-config"]
        assert rc.isolation.requires_api_key_env == "TEST_API_KEY"
        assert rc.isolation.version_cmd == ["testcli", "--version"]
        # unspecified fields stay at defaults
        assert rc.isolation.disable_ambient_env == {}
        assert rc.isolation.disable_session_flags == []
        assert rc.isolation.ambient_files == []

    def test_load_runner_without_isolation_yaml_uses_defaults(self, tmp_path):
        d = tmp_path / "runners"
        d.mkdir()
        (d / "nocli.yaml").write_text(
            "runner:\n  cli: nocli\n  arg_map: {model: -m}\n  parser: stream_json\n"
        )
        rc = load_runner("nocli", runner_dirs=[d])

        assert isinstance(rc.isolation, IsolationSpec)
        assert rc.isolation.config_home_env is None
        assert rc.isolation.strict_mcp_flags == []
        assert rc.isolation.disable_ambient_env == {}
        assert rc.isolation.disable_session_flags == []
        assert rc.isolation.disable_telemetry_env == {}
        assert rc.isolation.ambient_files == []
        assert rc.isolation.requires_api_key_env is None
        assert rc.isolation.version_cmd == []
