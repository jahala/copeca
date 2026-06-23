"""AUTH-3: auth-error fail-fast in run_matrix.

When the first completed run carries an auth-error (is_error from the CLI),
run_matrix must abort the remaining work items with an actionable message
instead of continuing with a scenario full of doomed runs.
"""

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
from copeca.runners.parsers.base import RunResult  # noqa: F401

# ── Helpers (same pattern as test_worker_pool.py) ───────────────────────────


class StubRepoManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._counter = 0

    def verify_toolchain(self, repo_key: str) -> None:
        pass

    def create_worktree(self, repo_key: str, commit=None, uri=None, worktree_id=None) -> Path:
        self._counter += 1
        wt = self.base_dir / f"worktree-{self._counter}"
        wt.mkdir(parents=True, exist_ok=True)
        return wt

    def setup(self, worktree: Path) -> None:
        pass

    def reset(self, worktree: Path) -> None:
        pass

    def remove_worktree(self, worktree: Path) -> None:
        pass


def _make_task(name: str, repo: str = "test-repo") -> Task:
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
    defaults = {
        "name": "test_scenario",
        "tasks": ["task_a", "task_b", "task_c"],
        "modes": ["baseline"],
        "models": ["test-model"],
        "repetitions": 1,
    }
    defaults.update(overrides)
    return Scenario.model_validate(defaults)


# ── Auth-error runner stubs ──────────────────────────────────────────────────


class AuthErrorRunner:
    """Runner whose first call returns a 'Not logged in' auth error; subsequent calls
    would return a valid answer — but the fail-fast must prevent them."""

    name = "auth-error-runner"
    isolation = None
    config_dir_env = None

    def __init__(self):
        self.call_count = 0

    def build_command(self, model, prompt, **kwargs):
        return ["echo", prompt]

    def run(self, command, cwd=None, env=None, exclude=None):
        self.call_count += 1
        # Every call returns an auth error (simulates a fully unauthenticated CLI)
        return RunResult(error="Not logged in · Please run /login")


class CountingRunner:
    """Counts how many times run() is called — used to assert fail-fast stops subsequent calls."""

    name = "counting-runner"
    isolation = None
    config_dir_env = None

    def __init__(self):
        self.call_count = 0

    def build_command(self, model, prompt, **kwargs):
        return ["echo", prompt]

    def run(self, command, cwd=None, env=None, exclude=None):
        self.call_count += 1
        return RunResult(error="Not logged in · Please run /login")


# ── Tests ────────────────────────────────────────────────────────────────────


class TestAuthFailFast:
    """AUTH-3: an auth error on the first run aborts the remaining scenario items."""

    def test_auth_error_aborts_scenario_with_actionable_message(self, tmp_path):
        """run_matrix raises RuntimeError with actionable 'login' hint on auth error."""
        tasks = [_make_task("task_a"), _make_task("task_b"), _make_task("task_c")]
        scenario = _make_scenario(tasks=["task_a", "task_b", "task_c"])
        runner = AuthErrorRunner()

        def runner_factory(mode, model):
            return runner

        with pytest.raises(RuntimeError, match="not authenticated|not logged in|login"):
            run_matrix(
                scenario=scenario,
                tasks=tasks,
                modes=scenario.modes,
                runner_factory=runner_factory,
                repo_mgr=StubRepoManager(tmp_path),
                max_workers=1,
            )

    def test_auth_error_aborts_before_running_remaining_items(self, tmp_path):
        """After the first auth-error record, no additional agent runs are spawned."""
        tasks = [_make_task("task_a"), _make_task("task_b"), _make_task("task_c")]
        scenario = _make_scenario(tasks=["task_a", "task_b", "task_c"])
        runner = CountingRunner()

        def runner_factory(mode, model):
            return runner

        with pytest.raises(RuntimeError):
            run_matrix(
                scenario=scenario,
                tasks=tasks,
                modes=scenario.modes,
                runner_factory=runner_factory,
                repo_mgr=StubRepoManager(tmp_path),
                max_workers=1,
            )

        # Fewer than all 3 tasks were run — the abort prevents the full scenario.
        # With max_workers=1 and thread-pool pre-submission, at most 2 runs may
        # complete before request_abort() stops further work (race between the
        # pool thread picking up the next item and the main thread setting the flag).
        assert runner.call_count < 3

    def test_non_auth_error_does_not_abort(self, tmp_path):
        """A generic (non-auth) error record does NOT trigger the fail-fast — scenario continues."""

        class GenericErrorRunner:
            name = "generic-error-runner"
            isolation = None
            config_dir_env = None

            def build_command(self, model, prompt, **kwargs):
                return ["echo", prompt]

            def run(self, command, cwd=None, env=None, exclude=None):
                return RunResult(error="some transient tool error")

        tasks = [_make_task("task_a"), _make_task("task_b")]
        scenario = _make_scenario(tasks=["task_a", "task_b"])
        runner = GenericErrorRunner()

        def runner_factory(mode, model):
            return runner

        # Should NOT raise — generic errors are isolated, not fatal to the scenario
        records = run_matrix(
            scenario=scenario,
            tasks=tasks,
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=StubRepoManager(tmp_path),
            max_workers=1,
        )
        assert len(records) == 2
        for r in records:
            assert r["error"] is not None

    def test_credit_balance_error_also_aborts(self, tmp_path):
        """'credit balance' auth-family errors also trigger the fail-fast."""

        class CreditRunner:
            name = "credit-runner"
            isolation = None
            config_dir_env = None

            def build_command(self, model, prompt, **kwargs):
                return ["echo", prompt]

            def run(self, command, cwd=None, env=None, exclude=None):
                return RunResult(error="Insufficient credit balance — top up your account")

        tasks = [_make_task("task_a"), _make_task("task_b")]
        scenario = _make_scenario(tasks=["task_a", "task_b"])

        def runner_factory(mode, model):
            return CreditRunner()

        with pytest.raises(RuntimeError):
            run_matrix(
                scenario=scenario,
                tasks=tasks,
                modes=scenario.modes,
                runner_factory=runner_factory,
                repo_mgr=StubRepoManager(tmp_path),
                max_workers=1,
            )
