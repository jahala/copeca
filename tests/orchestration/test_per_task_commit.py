"""SD-O: a task's `commit` overrides the repos.yaml commit at worktree creation.

copeca's own corpus and migrated tilth tasks were authored against different code
states of the same repo; a single repos.yaml pin can't serve both. A per-task
`commit` lets each task pin the state its ground truth / mutations were verified
against, without a global repin that would break the other corpus.
"""

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.runners.parsers.base import RunResult


class _RecordingMgr:
    """Repo manager stub that records the commit passed to create_worktree."""

    def __init__(self, worktree) -> None:
        self.worktree = str(worktree)
        self.commit = "UNSET"

    def verify_toolchain(self, repo):
        pass

    def create_worktree(self, repo, commit=None, uri=None, worktree_id=None):
        self.commit = commit
        return self.worktree

    def setup(self, worktree):
        pass

    def reset(self, worktree):
        pass

    def remove_worktree(self, worktree):
        pass


class _StubRunner:
    name = "stub"
    cli = "echo"

    def build_command(self, **kwargs):
        return ["echo", "hi"]

    def run(self, command, cwd=None, env=None, exclude=None):
        return RunResult(result_text="answer x", total_cost_usd=0.0, duration_ms=1)


def _task(**over):
    base = dict(
        name="t",
        source="s",
        repo="r",
        type=TaskType.comprehension,
        category=Category.locate,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="p",
        ground_truth=ComprehensionGroundTruth(required_strings=["x"]),
    )
    base.update(over)
    return Task(**base)


def test_task_commit_overrides_repos_commit(tmp_path):
    mgr = _RecordingMgr(tmp_path)
    run_single(
        task=_task(commit="a" * 40),
        mode_name="baseline",
        model="m",
        runner=_StubRunner(),
        repo_mgr=mgr,
        repo_uri="file:///x",
        repo_commit="b" * 40,
    )
    assert mgr.commit == "a" * 40  # task.commit wins over the repos.yaml commit


def test_no_task_commit_falls_back_to_repos_commit(tmp_path):
    mgr = _RecordingMgr(tmp_path)
    run_single(
        task=_task(),
        mode_name="baseline",
        model="m",
        runner=_StubRunner(),
        repo_mgr=mgr,
        repo_uri="file:///x",
        repo_commit="b" * 40,
    )
    assert mgr.commit == "b" * 40  # no task.commit -> the repos.yaml commit
