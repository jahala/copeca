"""Test the single-run orchestrator — end-to-end pipeline integration."""

import json
import subprocess
from pathlib import Path

import pytest

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    EditGroundTruth,
    Language,
    Mutation,
    Task,
    TaskType,
)
from copeca.orchestration.run import _check_token_snowball, run_single
from copeca.repos.manager import GitWorktreeManager
from copeca.results.writer import append_jsonl
from copeca.runners.parsers.base import RunResult, Turn
from copeca.runners.subprocess import SubprocessRunner


class EchoParser:
    """Parser that returns a RunResult with raw stdout as result_text."""

    def parse(self, stdout, supported_events=None):
        return RunResult(
            result_text=stdout.strip(),
            total_cost_usd=0.05,
            duration_ms=200,
        )


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a local git repo for orchestration tests."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    return repo_dir


class TestRunSingle:
    def test_comprehension_task_correct(self, tmp_path, test_repo):
        task = Task(
            name="test_task",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: Matcher find_at RegexMatcher",
            ground_truth=ComprehensionGroundTruth(
                required_strings=["Matcher", "find_at"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["correct"] is True
        assert result["task"] == "test_task"
        assert result["total_cost_usd"] == 0.05
        assert result["control"] is False

    def test_edit_task_with_mutations(self, tmp_path, test_repo):
        task = Task(
            name="test_edit",
            source="test",
            repo="test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.rust,
            difficulty=Difficulty.medium,
            version=1,
            prompt="fix the bug",
            ground_truth=ComprehensionGroundTruth(required_strings=[]),
            mutations=[Mutation(file="src/bug.rs", action="create", content="fixed")],
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        # Mutations apply inside worktree before subprocess runs.
        # git clean -fd in reset removes the untracked file afterward,
        # so we verify correctness instead of filesystem state.
        assert result["correct"] is True

    def test_writes_jsonl(self, tmp_path, test_repo):
        """run_single returns a record; caller persists it (architecture.md §2)."""
        task = Task(
            name="test_task3",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: Matcher",
            ground_truth=ComprehensionGroundTruth(required_strings=["Matcher"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        record = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )

        results_file = tmp_path / "results.jsonl"
        append_jsonl(record, results_file)

        lines = results_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["task"] == "test_task3"
        assert parsed["correct"] is True

    def test_context_tokens_computed(self, tmp_path, test_repo):
        """context_tokens = input_tokens + cache_creation_tokens."""
        task = Task(
            name="test_ctx",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="test",
            ground_truth=ComprehensionGroundTruth(required_strings=["ok"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["context_tokens"] == 0
        assert "context_tokens" in result

    def test_repo_commit_is_passed_through(self, tmp_path, test_repo):
        """repo_commit=None is passed through to create_worktree."""
        task = Task(
            name="test_pin",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="say ok please",
            ground_truth=ComprehensionGroundTruth(required_strings=["ok"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["task"] == "test_pin"
        assert result["correct"] is True

    def test_control_flag_carried_into_record(self, tmp_path, test_repo):
        """A control task's record carries control=True (#52 non-regression)."""
        task = Task(
            name="test_control",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.reason,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: ok",
            ground_truth=ComprehensionGroundTruth(required_strings=["ok"]),
            control=True,
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["control"] is True


class TestEditTaskTestCommand:
    """P0 bug fix: test_command execution in edit tasks."""

    def test_edit_task_with_test_command_passes(self, tmp_path, test_repo):
        """Edit task with a shell command that exits 0 should be correct=True."""
        task = Task(
            name="test_edit_pass",
            source="test",
            repo="test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="fix the bug",
            ground_truth=EditGroundTruth(
                test_command=["true"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["correct"] is True
        assert result["correctness_detail"]["test_command_passed"] is True
        assert result["test_command_output"]["passed"] is True
        assert result["test_command_output"]["command"] == ["true"]
        assert result["test_command_output"]["stdout"] == ""
        assert result["test_command_output"]["stderr"] == ""

    def test_edit_task_with_failing_test_command(self, tmp_path, test_repo):
        """Edit task with a shell command that exits 1 should be correct=False."""
        task = Task(
            name="test_edit_fail",
            source="test",
            repo="test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="fix the bug",
            ground_truth=EditGroundTruth(
                test_command=["false"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["correct"] is False
        assert result["correctness_detail"]["test_command_passed"] is False
        assert result["test_command_output"]["passed"] is False
        assert result["test_command_output"]["command"] == ["false"]

    def test_edit_task_with_test_command_timeout(self, tmp_path, test_repo):
        """Command that sleeps forever should be killed by timeout."""
        task = Task(
            name="test_edit_timeout",
            source="test",
            repo="test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="fix the bug",
            ground_truth=EditGroundTruth(
                test_command=["sleep", "200"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        # Use a short timeout_seconds to make the timeout test fast
        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            timeout_seconds=1,
        )
        assert result["correct"] is False
        assert result["test_command_output"]["passed"] is False

    def test_test_command_binary_not_found(self, tmp_path, test_repo):
        """Edit task with nonexistent binary -> test_command_passed=False, no crash."""
        task = Task(
            name="test_binary_not_found",
            source="test",
            repo="test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="fix the bug",
            ground_truth=EditGroundTruth(
                test_command=["nonexistent_binary_xyz_12345"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["correct"] is False
        assert result["correctness_detail"]["test_command_passed"] is False
        assert result["test_command_output"]["passed"] is False
        assert "error" in result


class TestTokenSnowball:
    """Discriminate tests for _check_token_snowball token growth heuristics."""

    def test_token_snowball_flat_returns_false(self) -> None:
        """Three turns with no output token growth -> returns False."""
        parsed = RunResult(
            turns=[
                Turn(output_tokens=100),
                Turn(output_tokens=100),
                Turn(output_tokens=100),
            ]
        )
        result = _check_token_snowball(parsed)
        assert result is False

    def test_token_snowball_growth_returns_true(self) -> None:
        """Last turn output > 3x average of first three -> returns True."""
        parsed = RunResult(
            turns=[
                Turn(output_tokens=100),
                Turn(output_tokens=100),
                Turn(output_tokens=100),
                Turn(output_tokens=1000),
            ]
        )
        result = _check_token_snowball(parsed)
        assert result is True

    def test_token_snowball_insufficient_turns_returns_none(self) -> None:
        """Fewer than 3 turns -> returns None (insufficient data)."""
        parsed = RunResult(
            turns=[
                Turn(output_tokens=100),
            ]
        )
        result = _check_token_snowball(parsed)
        assert result is None

    def test_token_snowball_zero_avg_returns_none(self) -> None:
        """Average of first three turns is zero -> returns None (division safety)."""
        parsed = RunResult(
            turns=[
                Turn(output_tokens=0),
                Turn(output_tokens=0),
                Turn(output_tokens=0),
            ]
        )
        result = _check_token_snowball(parsed)
        assert result is None


class TestErrorRecovery:
    """Discriminate tests for error-recovery paths in run_single."""

    def test_create_worktree_failure_does_not_call_reset(self, tmp_path: Path) -> None:
        """When create_worktree raises, reset should NOT be called."""
        task = Task(
            name="err_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )

        class FailingRepoMgr:
            reset_called: bool = False

            def verify_toolchain(self, key: str) -> None:
                pass

            def create_worktree(self, *a: object, **kw: object) -> Path:
                raise RuntimeError("simulated clone failure")

            def setup(self, wt: Path) -> None:
                pass

            def reset(self, wt: Path) -> None:
                self.reset_called = True

        mgr = FailingRepoMgr()
        with pytest.raises(RuntimeError, match="clone"):
            run_single(
                task=task,
                mode_name="baseline",
                model="m",
                runner=runner,
                repo_mgr=mgr,
            )
        assert not mgr.reset_called, "reset should not be called if create_worktree failed"

    def test_setup_failure_still_calls_reset(self, tmp_path: Path) -> None:
        """When setup raises after worktree created, reset MUST be called."""
        task = Task(
            name="err_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )

        class SetupFailingMgr:
            reset_called: bool = False

            def verify_toolchain(self, key: str) -> None:
                pass

            def create_worktree(self, *a: object, **kw: object) -> Path:
                return tmp_path / "wt"

            def setup(self, wt: Path) -> None:
                raise RuntimeError("simulated setup failure")

            def reset(self, wt: Path) -> None:
                self.reset_called = True

        mgr = SetupFailingMgr()
        with pytest.raises(RuntimeError, match="setup"):
            run_single(
                task=task,
                mode_name="baseline",
                model="m",
                runner=runner,
                repo_mgr=mgr,
            )
        assert mgr.reset_called, "reset MUST be called after setup failure (finally block)"

    def test_runner_failure_propagates_and_reset_called(self, tmp_path: Path) -> None:
        """Runner.run() failure propagates exception; reset is still called."""
        task = Task(
            name="err_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )

        class FailingRunner:
            name: str = "fail"

            def build_command(self, *a: object, **kw: object) -> list[str]:
                return ["echo", "x"]

            def run(self, *a: object, **kw: object) -> RunResult:
                raise RuntimeError("crash")

        class StubMgr:
            reset_called: bool = False

            def verify_toolchain(self, key: str) -> None:
                pass

            def create_worktree(self, *a: object, **kw: object) -> Path:
                import tempfile

                return Path(tempfile.mkdtemp())

            def setup(self, wt: Path) -> None:
                pass

            def reset(self, wt: Path) -> None:
                self.reset_called = True

        mgr = StubMgr()
        with pytest.raises(RuntimeError, match="crash"):
            run_single(
                task=task,
                mode_name="baseline",
                model="m",
                runner=FailingRunner(),
                repo_mgr=mgr,
            )
        assert mgr.reset_called, "reset MUST be called even when runner.run() raises"
