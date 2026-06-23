"""Test the matrix runner — tasks x modes x repetitions produce correct cardinality."""

import json
from pathlib import Path

import pytest

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
from copeca.results.writer import append_jsonl
from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner

# ── EchoParser — same pattern as test_single_run.py ─────────────────────────


class EchoParser:
    """Parser that returns a RunResult with raw stdout as result_text."""

    def parse(self, stdout, supported_events=None):
        return RunResult(
            result_text=stdout.strip(),
            total_cost_usd=0.05,
            duration_ms=200,
        )


# ── StubRepoManager — no real git needed for matrix shape tests ─────────────


class StubRepoManager:
    """Stub repo manager that fakes worktree operations for matrix tests.

    Each call creates a unique path under a temp directory so runs don't collide.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._counter = 0
        self.worktrees_created: list[Path] = []
        self.setups_called = 0
        self.resets_called = 0
        self.removes_called = 0

    def verify_toolchain(self, repo_key: str) -> None:
        pass

    def create_worktree(self, repo_key: str, commit=None, uri=None, worktree_id=None) -> Path:
        self._counter += 1
        wt = self.base_dir / f"worktree-{self._counter}"
        wt.mkdir(parents=True, exist_ok=True)
        self.worktrees_created.append(wt)
        return wt

    def setup(self, worktree: Path) -> None:
        self.setups_called += 1

    def reset(self, worktree: Path) -> None:
        self.resets_called += 1

    def remove_worktree(self, worktree: Path) -> None:
        self.removes_called += 1


def _make_task(name: str, repo: str = "test-repo") -> Task:
    """Helper: build a minimal comprehension task for matrix tests."""
    return Task(
        name=name,
        source="test",
        repo=repo,
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt=f"answer: {name}",
        ground_truth=ComprehensionGroundTruth(required_strings=[name]),
    )


def _make_scenario(**overrides) -> Scenario:
    """Helper: build a minimal scenario with overrides."""
    defaults = {
        "name": "test_scenario",
        "tasks": ["task_a", "task_b"],
        "modes": ["baseline"],
        "models": ["test-model"],
        "repetitions": 1,
    }
    defaults.update(overrides)
    return Scenario.model_validate(defaults)


def _make_runner() -> SubprocessRunner:
    """Helper: echo runner with EchoParser."""
    return SubprocessRunner(
        name="echo-test",
        cli="echo",
        default_args=[],
        arg_map={"prompt_separator": ""},
        parser=EchoParser(),
    )


# ── Tests ───────────────────────────────────────────────────────────────────


class TestMatrixCardinality:
    """The matrix shape: tasks x modes x reps = total records."""

    def test_matrix_produces_correct_cardinality(self, tmp_path):
        """2 tasks x 1 mode x 1 rep = 2 records."""
        tasks = {
            "task_a": _make_task("task_a"),
            "task_b": _make_task("task_b"),
        }
        scenario = _make_scenario(
            tasks=["task_a", "task_b"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        assert len(records) == 2
        task_names = sorted(r["task"] for r in records)
        assert task_names == ["task_a", "task_b"]

    def test_matrix_repetitions_work(self, tmp_path):
        """1 task x 1 mode x 2 reps = 2 records with different rep indices."""
        tasks = {"task_a": _make_task("task_a")}
        scenario = _make_scenario(
            tasks=["task_a"],
            modes=["baseline"],
            repetitions=2,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        assert len(records) == 2
        reps = [r["repetition"] for r in records]
        assert sorted(reps) == [0, 1]

    def test_matrix_multiple_modes(self, tmp_path):
        """1 task x 2 modes x 1 rep = 2 records with different modes."""
        tasks = {"task_a": _make_task("task_a")}
        scenario = _make_scenario(
            tasks=["task_a"],
            modes=["baseline", "mcp-tool"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        assert len(records) == 2
        mode_names = sorted(r["mode"] for r in records)
        assert mode_names == ["baseline", "mcp-tool"]


class TestConcurrentExecution:
    """max_workers > 1 dispatches work items across threads."""

    def test_concurrent_execution_with_max_workers(self, tmp_path):
        """2 tasks x 1 mode x 1 rep x 1 model with max_workers=2 produces 2 records."""
        tasks = {
            "task_a": _make_task("task_a"),
            "task_b": _make_task("task_b"),
        }
        scenario = _make_scenario(
            tasks=["task_a", "task_b"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=2,
        )

        assert len(records) == 2
        task_names = sorted(r["task"] for r in records)
        assert task_names == ["task_a", "task_b"]

    def test_max_workers_1_is_sequential(self, tmp_path):
        """max_workers=1 still works correctly (backward compat)."""
        tasks = {
            "task_a": _make_task("task_a"),
            "task_b": _make_task("task_b"),
        }
        scenario = _make_scenario(
            tasks=["task_a", "task_b"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        assert len(records) == 2
        task_names = sorted(r["task"] for r in records)
        assert task_names == ["task_a", "task_b"]


class TestMatrixFailureIsolation:
    """One run failing must not kill the remaining runs."""

    def test_matrix_run_failure_does_not_kill_remaining(self, tmp_path):
        """When one task fails, other tasks still produce records."""
        tasks = {
            "good_task": _make_task("good_task"),
            "bad_task": _make_task("bad_task"),
        }
        scenario = _make_scenario(
            tasks=["good_task", "bad_task"],
            modes=["baseline"],
            repetitions=1,
        )
        repo_mgr = StubRepoManager(tmp_path)

        # Runner factory: a runner whose run() will fail for the bad task
        class FailingRunner:
            def __init__(self, name, fail_on):
                self.name = name
                self._fail_on = fail_on
                self._commands: list[list[str]] = []

            def build_command(self, model, prompt, **kwargs):
                return ["echo", prompt]

            def run(self, command, cwd=None, env=None, exclude=None):
                self._commands.append(command)
                if self._fail_on in command[1]:
                    raise RuntimeError("simulated runner failure")
                return RunResult(
                    result_text=command[1].strip(),
                    total_cost_usd=0.05,
                    duration_ms=200,
                )

        def runner_factory(mode, model):
            return FailingRunner("test-runner", fail_on="bad_task")

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        # good_task should have produced a record; bad_task should have an error record
        assert len(records) == 2
        good = [r for r in records if r["task"] == "good_task"]
        bad = [r for r in records if r["task"] == "bad_task"]
        assert len(good) == 1
        assert len(bad) == 1
        assert good[0]["error"] is None
        assert bad[0]["error"] is not None


# ── Task 50: run_matrix error paths ───────────────────────────────────────


class TestMatrixErrorPaths:
    """Discriminate tests: unknown tasks, missing pricing, build command args."""

    def test_matrix_skips_unknown_task(self, tmp_path):
        """Scenario with 2 tasks but only 1 loaded: unknown is skipped, 1 record."""
        tasks = {"known_task": _make_task("known_task")}
        scenario = _make_scenario(
            tasks=["known_task", "unknown_task"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        # Only known_task runs — exactly 1 record, no crash
        assert len(records) == 1
        assert records[0]["task"] == "known_task"

    def test_matrix_model_not_in_pricing_table(self, tmp_path):
        """Model not in pricing dict: pricing fallback to parser cost."""
        tasks = {"task_a": _make_task("task_a")}
        scenario = _make_scenario(
            tasks=["task_a"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        # Pricing dict exists but model="test-model" is NOT in it
        pricing = {
            "some-other-model": {
                "input": 3.0,
                "cache_creation": 3.75,
                "cache_read": 0.30,
                "output": 15.0,
            }
        }

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
            pricing=pricing,
        )

        # Matrix completes; cost comes from parser (EchoParser returns 0.05)
        assert len(records) == 1
        assert records[0]["total_cost_usd"] == 0.05
        # vendor_cost_usd should not be present (pricing was None for this model)
        assert "vendor_cost_usd" not in records[0]

    def test_matrix_empty_work_items_returns_empty(self, tmp_path):
        """Scenario with no matching tasks produces 0 records (edge case)."""
        tasks: dict = {}
        scenario = _make_scenario(
            tasks=["no_such_task"],
            modes=["baseline"],
            repetitions=1,
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
        )

        assert len(records) == 0


class TestStreamingPersistence:
    """RUN-A: run_matrix streams each record to an injected sink as it completes."""

    def test_matrix_streams_each_record_to_sink(self, tmp_path):
        """run_matrix hands each record to on_record as it completes, not batched at the end."""
        tasks = {"task_a": _make_task("task_a"), "task_b": _make_task("task_b")}
        scenario = _make_scenario(tasks=["task_a", "task_b"], modes=["baseline"], repetitions=1)

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)
        seen: list[str] = []

        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            max_workers=1,
            on_record=lambda r: seen.append(r["task"]),
        )

        assert sorted(seen) == ["task_a", "task_b"]  # the sink saw every record
        assert len(records) == 2  # and the returned list is unchanged

    def test_matrix_persisted_records_survive_mid_run_interruption(self, tmp_path):
        """A sink that raises mid-run (a simulated Ctrl-C) leaves already-completed records on disk.

        The crash-safety guarantee: records stream to disk as they complete, so an interrupted
        run keeps its finished work instead of losing the whole in-memory batch.
        """
        tasks = {
            "task_a": _make_task("task_a"),
            "task_b": _make_task("task_b"),
            "task_c": _make_task("task_c"),
        }
        scenario = _make_scenario(
            tasks=["task_a", "task_b", "task_c"], modes=["baseline"], repetitions=1
        )

        def runner_factory(mode, model):
            return _make_runner()

        repo_mgr = StubRepoManager(tmp_path)
        out = tmp_path / "stream.jsonl"
        calls = {"n": 0}

        def sink(record):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt("simulated interrupt mid-run")
            append_jsonl(record, out)

        with pytest.raises(KeyboardInterrupt):
            run_matrix(
                scenario=scenario,
                tasks=list(tasks.values()),
                modes=scenario.modes,
                runner_factory=runner_factory,
                repo_mgr=repo_mgr,
                max_workers=1,
                on_record=sink,
            )

        lines = out.read_text().splitlines() if out.exists() else []
        assert (
            len(lines) == 1
        )  # exactly the pre-interrupt record persisted — nothing lost in a buffer
        assert json.loads(lines[0])["task"] == "task_a"  # the first completed record


class TestInterruption:
    """RUN-E: the abort flag stops new work items without spawning agents."""

    def test_abort_flag_api(self):
        from copeca.orchestration.run import abort_requested, clear_abort, request_abort

        clear_abort()
        assert abort_requested() is False
        request_abort()
        assert abort_requested() is True
        clear_abort()
        assert abort_requested() is False

    def test_work_item_bails_before_spawning_when_aborted(self, tmp_path):
        """When aborted, _run_one_work_item raises BEFORE building a runner — no agent spawns.

        DISCRIMINATES: asserts runner_factory was never called, so an interrupted run
        cannot launch new agents for queued work.
        """
        from copeca.orchestration.run import _run_one_work_item, clear_abort, request_abort

        scenario = _make_scenario(tasks=["task_a"], modes=["baseline"], repetitions=1)
        item = {
            "task": _make_task("task_a"),
            "task_name": "task_a",
            "mode_name": "baseline",
            "model": "test-model",
            "rep": 0,
            "repo_uri": None,
            "repo_commit": None,
            "mode_obj": None,
        }
        factory_calls: list[tuple] = []

        def runner_factory(mode, model):
            factory_calls.append((mode, model))
            return _make_runner()

        clear_abort()
        request_abort()
        try:
            with pytest.raises(RuntimeError, match="interrupt"):
                _run_one_work_item(
                    item, runner_factory, StubRepoManager(tmp_path), scenario, None, False
                )
            assert factory_calls == []  # bailed before building a runner / spawning an agent
        finally:
            clear_abort()
