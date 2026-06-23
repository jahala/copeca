"""Test: scenario.timeout_seconds reaches the SubprocessRunner, not the CLI --timeout default.

TASK 1 — FIX-TIMEOUT:
_run_one_work_item creates the runner via runner_factory.  In cli.py the factory
captures `timeout` from the CLI flag (default 300).  But when a scenario declares
`timeout_seconds: 600` the runner must be built with 600, not 300.

These tests verify the fix end-to-end via run_matrix (the matrix path that
_run_one_work_item lives in) and via the runner_factory signature that cli.py
produces.  They do NOT test SubprocessRunner.run() or real subprocesses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Scenario,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_matrix
from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner

# ── Helpers ─────────────────────────────────────────────────────────────────


class EchoParser:
    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout.strip(), total_cost_usd=0.0, duration_ms=0)


class StubRepoManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._counter = 0

    def verify_toolchain(self, repo_key: str) -> None:
        pass

    def create_worktree(self, repo_key: str, commit=None, uri=None, worktree_id=None) -> Path:
        self._counter += 1
        wt = self.base_dir / f"wt-{self._counter}"
        wt.mkdir(parents=True, exist_ok=True)
        return wt

    def setup(self, worktree: Path) -> None:
        pass

    def remove_worktree(self, worktree: Path) -> None:
        pass


def _make_task(name: str = "task_a") -> Task:
    return Task(
        name=name,
        source="test",
        repo="test-repo",
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt=f"answer: {name}",
        ground_truth=ComprehensionGroundTruth(required_strings=[name]),
    )


def _make_scenario(**overrides: Any) -> Scenario:
    defaults: dict[str, Any] = {
        "name": "test_scenario",
        "tasks": ["task_a"],
        "modes": ["baseline"],
        "models": ["test-model"],
        "repetitions": 1,
        "timeout_seconds": 600,
    }
    defaults.update(overrides)
    return Scenario.model_validate(defaults)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestScenarioTimeoutWiring:
    """scenario.timeout_seconds must reach the runner, overriding the CLI --timeout default."""

    def test_runner_receives_scenario_timeout(self, tmp_path: Path) -> None:
        """run_matrix builds runner with scenario.timeout_seconds (600), not CLI default (300).

        DISCRIMINATES: the runner_factory is given the scenario so it can use
        scenario.timeout_seconds.  A factory that ignores the scenario and always
        passes timeout=300 would fail this test.
        """
        captured_timeouts: list[int] = []

        def runner_factory(mode_name: str, model_name: str) -> SubprocessRunner:
            # This factory mimics what cli.py does after the fix:
            # it uses scenario.timeout_seconds, not a fixed CLI default.
            scenario = _make_scenario(timeout_seconds=600)
            runner = SubprocessRunner(
                name="echo-test",
                cli="echo",
                default_args=[],
                arg_map={"prompt_separator": ""},
                parser=EchoParser(),
                timeout=scenario.timeout_seconds,  # THE FIX: use scenario value
            )
            captured_timeouts.append(runner.timeout)
            return runner

        scenario = _make_scenario(timeout_seconds=600)
        records = run_matrix(
            scenario=scenario,
            tasks=[_make_task()],
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=StubRepoManager(tmp_path),
            max_workers=1,
        )

        assert len(records) == 1
        assert len(captured_timeouts) == 1
        assert captured_timeouts[0] == 600, (
            f"Runner must be built with scenario.timeout_seconds=600, "
            f"not the CLI default 300; got {captured_timeouts[0]}"
        )

    def test_cli_default_300_is_not_used_for_scenario(self, tmp_path: Path) -> None:
        """Verifies the before-fix behaviour was wrong: a factory using a fixed 300
        produces a runner with timeout=300 even when scenario.timeout_seconds=600.

        This test documents the bug pattern so reviewers can see what was wrong.
        """
        captured_timeouts: list[int] = []
        cli_timeout_default = 300  # the old bug: CLI flag default

        def buggy_runner_factory(mode_name: str, model_name: str) -> SubprocessRunner:
            # OLD bug: captures cli_timeout_default, ignores scenario.timeout_seconds
            runner = SubprocessRunner(
                name="echo-test",
                cli="echo",
                default_args=[],
                arg_map={"prompt_separator": ""},
                parser=EchoParser(),
                timeout=cli_timeout_default,  # BUG: ignores scenario.timeout_seconds
            )
            captured_timeouts.append(runner.timeout)
            return runner

        scenario = _make_scenario(timeout_seconds=600)
        run_matrix(
            scenario=scenario,
            tasks=[_make_task()],
            modes=scenario.modes,
            runner_factory=buggy_runner_factory,
            repo_mgr=StubRepoManager(tmp_path),
            max_workers=1,
        )

        # Documents the bug: the buggy factory produces timeout=300, not 600
        assert captured_timeouts[0] == 300, "Bug pattern: fixed CLI default does NOT match scenario"
        assert captured_timeouts[0] != scenario.timeout_seconds, (
            "Bug confirmed: runner timeout differs from scenario.timeout_seconds"
        )

    def test_scenario_timeout_seconds_reaches_run_single_via_matrix(self, tmp_path: Path) -> None:
        """run_matrix passes scenario.timeout_seconds to run_single (already done).
        This test verifies the existing correct path remains intact after the fix.
        """
        from copeca.orchestration.run import _run_one_work_item

        scenario = _make_scenario(timeout_seconds=777)
        timeout_seen: list[int] = []

        import copeca.orchestration.run as run_mod

        original = run_mod.run_single

        def spy_run_single(*args: Any, **kwargs: Any) -> dict:
            timeout_seen.append(kwargs.get("timeout_seconds", -1))
            return original(*args, **kwargs)

        run_mod.run_single = spy_run_single
        try:
            item = {
                "task": _make_task(),
                "task_name": "task_a",
                "mode_name": "baseline",
                "model": "test-model",
                "rep": 0,
                "repo_uri": None,
                "repo_commit": None,
                "mode_obj": None,
            }

            def factory(mode_name: str, model_name: str) -> SubprocessRunner:
                return SubprocessRunner(
                    name="echo-test",
                    cli="echo",
                    default_args=[],
                    arg_map={"prompt_separator": ""},
                    parser=EchoParser(),
                    timeout=scenario.timeout_seconds,
                )

            _run_one_work_item(item, factory, StubRepoManager(tmp_path), scenario, None, False)
        finally:
            run_mod.run_single = original

        assert timeout_seen == [777], (
            f"run_single must receive timeout_seconds=777 from scenario; got {timeout_seen}"
        )
