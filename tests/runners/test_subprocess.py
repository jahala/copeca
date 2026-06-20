"""Test SubprocessRunner — subprocess invocation with process-group isolation."""

import os

from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner


class EchoParser:
    """Parser that returns a RunResult with the raw stdout as result_text."""
    def parse(self, stdout, supported_events=None):
        return RunResult(result_text=stdout, duration_ms=100)


class TestSubprocessRunner:
    def test_runs_command(self):
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        result = runner.run(["echo", "hello", "world"])
        assert "hello" in result.result_text

    def test_env_filtering_removes_claudecode(self):
        runner = SubprocessRunner(
            name="env-test",
            cli="sh",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        os.environ["CLAUDECODE"] = "test_value"
        os.environ["KEEP_ME"] = "keep"
        result = runner.run(["sh", "-c", "echo $CLAUDECODE"])
        assert "test_value" not in result.result_text
        del os.environ["CLAUDECODE"]
        del os.environ["KEEP_ME"]

    def test_timeout_kills_process(self):
        runner = SubprocessRunner(
            name="sleep-test",
            cli="sleep",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
            timeout=1,
        )
        try:
            runner.run(["sleep", "10"])
            assert False, "should have timed out"
        except Exception:
            pass  # Expected — timeout or killed

    def test_run_without_parser_returns_raw_stdout(self):
        """When parser=None, run() returns RunResult with raw stdout as result_text."""
        runner = SubprocessRunner(
            name="no-parser-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        result = runner.run(["echo", "hello"])
        assert "hello" in result.result_text
        assert result.duration_ms > 0

    def test_parse_without_parser_returns_raw_stdout(self):
        """When parser=None, parse() returns RunResult wrapping stdout as-is."""
        runner = SubprocessRunner(
            name="no-parser-parse",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        result = runner.parse("raw text")
        assert result.result_text == "raw text"

    def test_parse_with_parser_delegates(self):
        """When parser is provided, parse() delegates to the parser."""
        runner = SubprocessRunner(
            name="parser-delegate",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        result = runner.parse("text")
        assert result.result_text == "text"
        assert result.duration_ms == 100  # EchoParser sets this

    def test_stderr_and_stdout_are_separated(self):
        """Runner captures stdout and stderr separately; stderr does not leak into stdout."""
        # Use parser=None so result_text is raw stdout (not parser-processed)
        runner = SubprocessRunner(
            name="stderr-test",
            cli="sh",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        result = runner.run(["sh", "-c", "echo stdout_line; echo stderr_line >&2"])
        assert "stdout_line" in result.result_text
        assert "stderr_line" not in result.result_text
        assert result.duration_ms > 0
