"""Test that run_single wires provision_arm env into runner.run().

Engineering.md §4: env construction belongs at the I/O boundary.
Architecture.md §7 invariant 3: the baseline must be clean.

These tests are hermetic — no real subprocess agent, no network.
"""

from pathlib import Path

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Mode,
    Scenario,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_matrix, run_single
from copeca.runners.parsers.base import RunResult


class EnvCapturingRunner:
    """Spy runner — records the env kwarg it receives from run_single."""

    name: str = "spy"
    captured_env: dict[str, str] | None

    def __init__(self) -> None:
        self.captured_env = None

    def build_command(self, model: str, prompt: str, **kwargs: object) -> list[str]:
        return ["echo", "ok"]

    def run(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        exclude: set[str] | None = None,
    ) -> RunResult:
        self.captured_env = dict(env) if env is not None else {}
        return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)


class StubRepoMgr:
    """Minimal repo manager that provides a worktree path without touching disk."""

    def __init__(self, worktree: Path) -> None:
        self._wt = worktree
        self.reset_called = False

    def verify_toolchain(self, key: str) -> None:
        pass

    def create_worktree(self, *args: object, **kwargs: object) -> Path:
        self._wt.mkdir(parents=True, exist_ok=True)
        return self._wt

    def setup(self, wt: Path) -> None:
        pass

    def reset(self, wt: Path) -> None:
        self.reset_called = True

    def remove_worktree(self, wt: Path) -> None:
        pass


def _task(name: str = "t") -> Task:
    return Task(
        name=name,
        source="test",
        repo="test-repo",
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="ok",
        ground_truth=ComprehensionGroundTruth(required_strings=[]),
    )


class TestProvisionArmWiring:
    """provision_arm env must flow to runner.run() on every code path."""

    def test_baseline_mode_runner_receives_env(self, tmp_path: Path) -> None:
        """Even baseline (no Mode object) must pass an env dict to runner.run().

        The env must be the allowlisted subset — NOT None (which would let
        the OS inherit everything).
        """
        runner = EnvCapturingRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
        )

        # runner.run MUST have been called with an explicit env dict
        assert runner.captured_env is not None, (
            "runner.run() must receive an explicit env= (not None)"
        )

    def test_experimental_mode_env_reaches_runner(self, tmp_path: Path) -> None:
        """Mode.env keys must appear in the env passed to runner.run()."""
        runner = EnvCapturingRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        mode = Mode(name="exp", env={"TOOL_API_KEY": "abc123", "TOOL_ENDPOINT": "http://x"})

        run_single(
            task=_task(),
            mode_name="exp",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=mode,
        )

        assert runner.captured_env is not None
        assert runner.captured_env.get("TOOL_API_KEY") == "abc123", (
            "Mode.env key must appear in child env"
        )
        assert runner.captured_env.get("TOOL_ENDPOINT") == "http://x"

    def test_experimental_env_absent_from_baseline(self, tmp_path: Path) -> None:
        """Baseline run must NOT see experimental mode's tool vars."""
        runner_baseline = EnvCapturingRunner()
        mgr_baseline = StubRepoMgr(tmp_path / "wt_baseline")

        run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner_baseline,
            repo_mgr=mgr_baseline,
        )

        assert runner_baseline.captured_env is not None
        assert "TOOL_API_KEY" not in runner_baseline.captured_env, (
            "Baseline must not see experimental tool vars"
        )

    def test_mode_none_gives_clean_baseline(self, tmp_path: Path) -> None:
        """run_single with mode=None (baseline) must not inject extra vars."""
        runner = EnvCapturingRunner()
        mgr = StubRepoMgr(tmp_path / "wt")

        run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
            mode=None,
        )

        assert runner.captured_env is not None
        # No tool-specific keys must appear
        tool_keys = [k for k in runner.captured_env if k.startswith("TOOL_")]
        assert tool_keys == [], f"Unexpected tool vars in baseline env: {tool_keys}"


class TestMatrixPathModeWiring:
    """Mode.env must reach runner.run() via run_matrix's OWN work-item construction.

    This is the decisive end-to-end test for the mode-wiring fix. It does NOT
    hand-build a work item with a pre-injected ``mode_obj`` — that would bypass
    the actual bug (run_matrix never populating mode_obj) and pass on broken
    production code. Instead it calls run_matrix and lets run_matrix thread the
    Mode through to provision_arm → run_single → runner.run().
    """

    def test_run_matrix_threads_mode_env_to_runner(self, tmp_path: Path) -> None:
        """run_matrix must populate mode_obj from mode_defs so the experimental
        arm's env reaches runner.run() while the baseline arm stays clean.

        Before the fix run_matrix has no ``mode_defs`` param and never sets
        ``mode_obj``, so every arm runs the clean baseline harness (delta ≈ 0).
        """
        baseline = Mode(name="baseline", tools=["Bash"])
        exp = Mode(name="exp", env={"COPECA_TEST_SIGNAL": "experimental"})
        mode_defs = {"baseline": baseline, "exp": exp}

        scenario = Scenario.model_validate(
            {
                "name": "test-scenario",
                "tasks": ["t"],
                "modes": ["baseline", "exp"],
                "models": ["m"],
                "repetitions": 1,
            }
        )

        spies: dict[str, EnvCapturingRunner] = {}
        runner_factory = lambda mode_name, model: spies.setdefault(  # noqa: E731
            mode_name, EnvCapturingRunner()
        )

        run_matrix(
            scenario=scenario,
            tasks=[_task("t")],
            modes=["baseline", "exp"],
            runner_factory=runner_factory,
            repo_mgr=StubRepoMgr(tmp_path / "wt"),
            mode_defs=mode_defs,
        )

        # Experimental arm's Mode.env must reach its runner.
        assert spies["exp"].captured_env is not None
        assert spies["exp"].captured_env.get("COPECA_TEST_SIGNAL") == "experimental", (
            "Mode.env must reach runner.run() via run_matrix's own work-item "
            "construction (mode_defs → mode_obj → run_single mode=)"
        )
        # Baseline arm must stay clean — no experimental signal leaks in.
        assert "COPECA_TEST_SIGNAL" not in (spies["baseline"].captured_env or {}), (
            "Baseline arm must not see the experimental mode's env"
        )
