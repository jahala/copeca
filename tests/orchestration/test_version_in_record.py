"""L2: copeca_version in run record must come from importlib.metadata, not a literal.

Engineering.md §5: reproducibility — every run records verified toolchain versions.
A hardcoded string drifts silently; importlib.metadata reads the installed package.
"""

import importlib.metadata
from pathlib import Path

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Mode,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.runners.parsers.base import RunResult


class _StubRunner:
    name = "stub"
    captured_env: dict | None = None

    def build_command(self, model: str, prompt: str, **kwargs: object) -> list[str]:
        return ["echo", "ok"]

    def run(self, command: list[str], cwd: str | None = None,
            env: dict | None = None) -> RunResult:
        self.captured_env = dict(env) if env is not None else {}
        return RunResult(result_text="ok", total_cost_usd=0.0, duration_ms=0)


class _StubRepoMgr:
    def __init__(self, worktree: Path) -> None:
        self._wt = worktree

    def verify_toolchain(self, key: str) -> None:
        pass

    def create_worktree(self, *args: object, **kwargs: object) -> Path:
        self._wt.mkdir(parents=True, exist_ok=True)
        return self._wt

    def setup(self, wt: Path) -> None:
        pass

    def reset(self, wt: Path) -> None:
        pass


def _task() -> Task:
    return Task(
        name="version_test_task",
        source="test",
        repo="test-repo",
        type=TaskType.comprehension, category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="ok",
        ground_truth=ComprehensionGroundTruth(required_strings=[]),
    )


class TestVersionInRecord:
    def test_run_record_copeca_version_matches_installed_package(
        self, tmp_path: Path
    ) -> None:
        """record['metadata']['copeca_version'] must equal importlib.metadata.version('copeca').

        A hardcoded '0.1.0' would fail if the package version ever changes, and —
        more importantly — it would record wrong provenance in a post-0.1.0 build.
        """
        expected = importlib.metadata.version("copeca")
        runner = _StubRunner()
        mgr = _StubRepoMgr(tmp_path / "wt")

        record = run_single(
            task=_task(),
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=mgr,
        )

        actual = record.get("metadata", {}).get("copeca_version")
        assert actual == expected, (
            f"record['metadata']['copeca_version'] is {actual!r} but "
            f"importlib.metadata.version('copeca') is {expected!r}. "
            "Replace the hardcoded string with a dynamic lookup."
        )
