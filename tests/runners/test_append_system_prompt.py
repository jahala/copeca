"""Test: per-mode append_system_prompt wiring for TASK 2 — PROMPT-1.

append_system_prompt on a Mode is a deployment knob: it lets a mode carry
usage-guidance text that is appended to the agent's base prompt.

For CLIs with a flag (claude: --append-system-prompt):
  - build_command emits the flag + text when the key is in arg_map.

For CLIs without a flag (codex, gemini: prepend_system_prompt=True):
  - the text is prepended to the positional prompt via the existing
    prepend path, so it is not silently dropped.

Disclosure:
  - run_single records mode_append_system_prompt in the JSONL output.
  - Baseline modes (no append_system_prompt) emit the field as null.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Mode,
    Task,
    TaskType,
)
from copeca.runners.base import BaseRunner
from copeca.runners.parsers.base import RunResult

# ── Stub runner ─────────────────────────────────────────────────────────────


class StubRunner(BaseRunner):
    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout)

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        exclude: set[str] | None = None,
    ) -> RunResult:
        return self.parse("")


# ── Mode model tests ─────────────────────────────────────────────────────────


class TestModeAppendSystemPromptField:
    """Mode.append_system_prompt is optional; None when absent."""

    def test_mode_without_append_system_prompt_defaults_none(self) -> None:
        mode = Mode(name="baseline", tools=["Read"])
        assert mode.append_system_prompt is None

    def test_mode_with_append_system_prompt_stores_text(self) -> None:
        text = "Use tilth_search for code navigation."
        mode = Mode(name="tilth", mcp_config={"mcpServers": {}}, append_system_prompt=text)
        assert mode.append_system_prompt == text

    def test_mode_append_system_prompt_none_explicit(self) -> None:
        mode = Mode(name="baseline", tools=["Read"], append_system_prompt=None)
        assert mode.append_system_prompt is None


# ── Claude runner: --append-system-prompt flag ───────────────────────────────


class TestClaudeAppendSystemPrompt:
    """claude: emits --append-system-prompt <text> when arg_map declares the key."""

    def _claude_runner(self) -> StubRunner:
        return StubRunner(
            name="claude",
            cli="claude",
            default_args=["-p", "--output-format", "stream-json"],
            arg_map={
                "model": "--model",
                "system_prompt": "--system-prompt",
                "append_system_prompt": "--append-system-prompt",
                "prompt_separator": "--",
            },
        )

    def test_append_system_prompt_flag_emitted(self) -> None:
        """--append-system-prompt <text> appears when the key is in arg_map."""
        runner = self._claude_runner()
        text = "Prefer tilth_search over Grep."
        cmd = runner.build_command(model="m", prompt="p", append_system_prompt=text)

        assert "--append-system-prompt" in cmd, (
            "--append-system-prompt must appear when arg_map declares it"
        )
        idx = cmd.index("--append-system-prompt")
        assert cmd[idx + 1] == text, "Text must immediately follow the flag"

    def test_append_system_prompt_absent_when_none(self) -> None:
        """No flag when append_system_prompt=None."""
        runner = self._claude_runner()
        cmd = runner.build_command(model="m", prompt="p", append_system_prompt=None)
        assert "--append-system-prompt" not in cmd

    def test_append_system_prompt_absent_when_not_in_arg_map(self) -> None:
        """No flag when the runner's arg_map does not declare the key."""
        runner = StubRunner(
            name="no-append",
            cli="agent",
            arg_map={"model": "--model", "prompt_separator": "--"},
        )
        cmd = runner.build_command(model="m", prompt="p", append_system_prompt="some text")
        assert "--append-system-prompt" not in cmd

    def test_prompt_still_last_with_append_system_prompt(self) -> None:
        """The positional prompt remains the last token."""
        runner = self._claude_runner()
        cmd = runner.build_command(model="m", prompt="my task", append_system_prompt="Use tilth.")
        assert cmd[-1] == "my task"

    def test_append_system_prompt_does_not_modify_positional_prompt(self) -> None:
        """For claude (flag-style), the positional prompt is NOT modified."""
        runner = self._claude_runner()
        cmd = runner.build_command(model="m", prompt="USER", append_system_prompt="INSTR")
        # The last token must be the raw prompt, not a concatenation
        assert cmd[-1] == "USER"


# ── Codex/Gemini: prepend to positional prompt ──────────────────────────────


class TestCodexGeminiAppendSystemPrompt:
    """codex/gemini: no --append-system-prompt flag; text is prepended to positional prompt."""

    def _codex_runner(self) -> StubRunner:
        return StubRunner(
            name="codex",
            cli="codex",
            default_args=["exec"],
            arg_map={"model": "-m", "prompt_separator": "--"},
            prepend_system_prompt=True,
        )

    def _gemini_runner(self) -> StubRunner:
        return StubRunner(
            name="gemini",
            cli="gemini",
            default_args=["-p"],
            arg_map={"model": "-m", "prompt_separator": "--"},
            prepend_system_prompt=True,
        )

    def test_codex_prepends_append_system_prompt(self) -> None:
        """append_system_prompt text is prepended to the positional prompt for codex."""
        runner = self._codex_runner()
        cmd = runner.build_command(model="m", prompt="USER TASK", append_system_prompt="INSTR")
        # Must be prepended — no separate flag
        assert "--append-system-prompt" not in cmd
        assert cmd[-1] == "INSTR\n\nUSER TASK", (
            f"Expected 'INSTR\\n\\nUSER TASK' but got {cmd[-1]!r}"
        )

    def test_gemini_prepends_append_system_prompt(self) -> None:
        """append_system_prompt text is prepended to the positional prompt for gemini."""
        runner = self._gemini_runner()
        cmd = runner.build_command(model="m", prompt="USER TASK", append_system_prompt="INSTR")
        assert "--append-system-prompt" not in cmd
        assert cmd[-1] == "INSTR\n\nUSER TASK"

    def test_codex_no_append_when_none(self) -> None:
        """No modification when append_system_prompt=None."""
        runner = self._codex_runner()
        cmd = runner.build_command(model="m", prompt="USER TASK", append_system_prompt=None)
        assert cmd[-1] == "USER TASK"

    def test_codex_both_system_prompt_and_append_combined(self) -> None:
        """When both system_prompt and append_system_prompt are set, both are prepended."""
        runner = self._codex_runner()
        cmd = runner.build_command(
            model="m",
            prompt="USER",
            system_prompt="SYS",
            append_system_prompt="APPEND",
        )
        # The effective prompt should contain SYS, APPEND, and USER
        positional = cmd[-1]
        assert "SYS" in positional
        assert "APPEND" in positional
        assert "USER" in positional


# ── Disclosure in JSONL record ────────────────────────────────────────────────


class TestAppendSystemPromptDisclosure:
    """run_single records mode_append_system_prompt in the JSONL output."""

    def _make_task(self) -> Task:
        return Task(
            name="disclose_task",
            source="test",
            repo="r",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="what is 2+2",
            ground_truth=ComprehensionGroundTruth(required_strings=[]),
        )

    def _stub_mgr(self, tmp_path: Path):
        class M:
            def __init__(self, p: Path) -> None:
                self._p = p

            def verify_toolchain(self, k: str) -> None:
                pass

            def create_worktree(self, *a: Any, **kw: Any) -> Path:
                self._p.mkdir(parents=True, exist_ok=True)
                return self._p

            def setup(self, wt: Path) -> None:
                pass

            def remove_worktree(self, wt: Path) -> None:
                pass

        return M(tmp_path / "wt")

    def test_record_contains_mode_append_system_prompt_when_set(self, tmp_path: Path) -> None:
        """When the mode has append_system_prompt, the record includes it."""
        from copeca.orchestration.run import run_single

        text = "Use tilth_search for code navigation."
        mode = Mode(name="tilth", mcp_config={"mcpServers": {}}, append_system_prompt=text)

        class EchoRunner:
            name = "echo"

            def build_command(self, **kwargs: Any) -> list[str]:
                return ["echo", "ok"]

            def run(self, cmd: list[str], **kwargs: Any) -> RunResult:
                return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)

        record = run_single(
            task=self._make_task(),
            mode_name="tilth",
            model="m",
            runner=EchoRunner(),
            repo_mgr=self._stub_mgr(tmp_path),
            mode=mode,
        )

        assert "mode_append_system_prompt" in record, (
            "Record must include 'mode_append_system_prompt' field"
        )
        assert record["mode_append_system_prompt"] == text

    def test_record_mode_append_system_prompt_null_for_baseline(self, tmp_path: Path) -> None:
        """When the mode has no append_system_prompt, the record field is null."""
        from copeca.orchestration.run import run_single

        mode = Mode(name="baseline", tools=["Read"])

        class EchoRunner:
            name = "echo"

            def build_command(self, **kwargs: Any) -> list[str]:
                return ["echo", "ok"]

            def run(self, cmd: list[str], **kwargs: Any) -> RunResult:
                return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)

        record = run_single(
            task=self._make_task(),
            mode_name="baseline",
            model="m",
            runner=EchoRunner(),
            repo_mgr=self._stub_mgr(tmp_path),
            mode=mode,
        )

        assert "mode_append_system_prompt" in record
        assert record["mode_append_system_prompt"] is None

    def test_record_mode_append_system_prompt_null_when_no_mode(self, tmp_path: Path) -> None:
        """When mode=None (clean baseline), the record field is null."""
        from copeca.orchestration.run import run_single

        class EchoRunner:
            name = "echo"

            def build_command(self, **kwargs: Any) -> list[str]:
                return ["echo", "ok"]

            def run(self, cmd: list[str], **kwargs: Any) -> RunResult:
                return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)

        record = run_single(
            task=self._make_task(),
            mode_name="baseline",
            model="m",
            runner=EchoRunner(),
            repo_mgr=self._stub_mgr(tmp_path),
            mode=None,
        )

        assert "mode_append_system_prompt" in record
        assert record["mode_append_system_prompt"] is None
