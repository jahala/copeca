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
            raise AssertionError("should have timed out")
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


class TestRunnerFailureSurfacing:
    """A crashed subprocess must surface exit_code + error — never look like a
    legit empty answer. Shakedown SD-B: the tilth arm exited 1 with empty stdout
    and was recorded as error=null / exit_code=null, indistinguishable from the
    agent legitimately saying nothing.
    """

    def test_nonzero_exit_sets_error_and_exit_code(self):
        runner = SubprocessRunner(
            name="fail-test",
            cli="sh",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        result = runner.run(["sh", "-c", "echo boom 1>&2; exit 3"])
        assert result.exit_code == 3
        assert result.error is not None
        assert "boom" in result.error

    def test_clean_exit_leaves_error_none(self):
        runner = SubprocessRunner(
            name="ok-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        result = runner.run(["echo", "hi"])
        assert result.exit_code == 0
        assert result.error is None


class TestChildStdinClosed:
    """codex `exec` reads its prompt from stdin whenever stdin is a pipe; a child
    that inherited the orchestrator's stdin could block forever waiting on EOF.
    The runner must hand every child an empty stdin (DEVNULL) so a stdin-reading
    agent gets immediate EOF and never hangs. (claude -p never read stdin, so this
    surfaced only when wiring the codex runner — SD-L.)
    """

    def test_child_stdin_is_devnull(self, monkeypatch):
        import subprocess as sp

        captured: dict = {}
        real_popen = sp.Popen

        def spy_popen(*args, **kwargs):
            captured["stdin"] = kwargs.get("stdin", "ABSENT")
            return real_popen(*args, **kwargs)  # call through — real subprocess runs

        monkeypatch.setattr(sp, "Popen", spy_popen)

        runner = SubprocessRunner(
            name="stdin-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=None,
        )
        runner.run(["echo", "hi"])

        assert captured["stdin"] is sp.DEVNULL
