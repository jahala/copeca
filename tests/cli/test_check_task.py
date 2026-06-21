"""Test `copeca check-task` CLI command end-to-end.

Architecture invariant #5: Every edit task proves its mutation bites.
check-task verifies the test passes on clean code and fails on mutated code.

Uses real git repos in tmp_path — no mocks of git operations.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from copeca.config.loader import load_repos, load_task
from copeca.orchestration.check import verify_mutation_validity
from copeca.repos.manager import GitWorktreeManager

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EDIT_VALID = FIXTURES / "edit_valid.yaml"
EDIT_WEAK = FIXTURES / "edit_weak.yaml"


def copeca(*args: str) -> subprocess.CompletedProcess[str]:
    """Run copeca CLI via the installed entry point."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def edit_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a git repo with calc.py that has a function add(a, b) = a + b.

    Also create a repos.yaml pointing to it.

    Returns (repos_dir, task_dir). repos_dir passes as --repos-dir to
    check-task. task_dir is where we'll copy the fixture YAML files.
    """
    repo_dir = tmp_path / "edit-test-repo"
    repo_dir.mkdir()

    # git init
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@copeca.dev"],
        cwd=repo_dir,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Copeca Test"],
        cwd=repo_dir,
        check=True,
    )

    # Create calc.py
    calc_py = repo_dir / "calc.py"
    calc_py.write_text("# Add two numbers\ndef add(a, b):\n    return a + b\n")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)

    # Get commit hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    commit_hash = result.stdout.strip()

    # Create repos.yaml in the temp dir
    task_dir = tmp_path / "tasks"
    task_dir.mkdir()
    repos_yaml = tmp_path / "repos.yaml"
    repos_yaml.write_text(
        yaml.dump(
            {
                "edit-test-repo": {
                    "url": str(repo_dir),
                    "commit": commit_hash,
                    "language": "python",
                    "toolchain": {"python": "3.11"},
                    "setup_command": [],
                }
            }
        )
    )

    # Copy fixture YAMLs into task_dir with repo-relative paths via repos.yaml backref
    import shutil

    repos_dir = tmp_path / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    return repos_dir, task_dir


class TestCheckTaskOrchestration:
    """Test verify_mutation_validity directly (unit-like, uses real git)."""

    def test_valid_edit_task_passes_check(self, edit_repo: tuple[Path, Path]) -> None:
        """Task where test fails on mutated code -> check_task reports valid."""
        repos_dir, task_dir = edit_repo

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")
        task = load_task(EDIT_VALID)

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert valid, f"Expected valid, got: {message}"
        assert "Valid edit task" in message

    def test_weak_mutation_fails_check(self, edit_repo: tuple[Path, Path]) -> None:
        """Task where test still passes after mutation -> check_task reports invalid."""
        repos_dir, task_dir = edit_repo

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")
        task = load_task(EDIT_WEAK)

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert not valid, f"Expected invalid, got: {message}"
        assert "weak" in message.lower() or "does not break" in message.lower()

    def test_non_edit_task_rejected(self, edit_repo: tuple[Path, Path]) -> None:
        """Comprehension task passed to check-task -> reports not an edit task."""
        repos_dir, task_dir = edit_repo

        from copeca.config.models import (
            Category,
            ComprehensionGroundTruth,
            Difficulty,
            Language,
            Task,
            TaskType,
        )
        # Build a comprehension task dynamically
        task = Task(
            name="comprehension_test",
            description="A comprehension task",
            source="copeca-test (MIT)",
            repo="edit-test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="Find all functions in calc.py",
            ground_truth=ComprehensionGroundTruth(
                required_strings=["add"],
                all_of=["return"],
            ),
        )

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert not valid
        assert "not an edit task" in message.lower()

    def test_task_with_no_mutations_rejected(
        self, edit_repo: tuple[Path, Path]
    ) -> None:
        """Edit task with mutations=[] -> verify_mutation_validity returns False."""
        repos_dir, task_dir = edit_repo

        from copeca.config.models import (
            Category,
            Difficulty,
            EditGroundTruth,
            Language,
            Task,
            TaskType,
        )

        task = Task(
            name="no_mutations_test",
            description="Edit task with no mutations",
            source="copeca-test (MIT)",
            repo="edit-test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="Fix the function",
            ground_truth=EditGroundTruth(
                test_command=["true"],
            ),
            mutations=[],
        )

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert not valid
        assert "no mutations" in message.lower()

    def test_task_with_no_test_command_rejected(
        self, edit_repo: tuple[Path, Path]
    ) -> None:
        """Edit task with test_command=[] -> verify_mutation_validity returns False."""
        repos_dir, task_dir = edit_repo

        from copeca.config.models import (
            Category,
            Difficulty,
            EditGroundTruth,
            Language,
            Mutation,
            Task,
            TaskType,
        )

        task = Task(
            name="no_test_cmd_task",
            description="Edit task with empty test_command",
            source="copeca-test (MIT)",
            repo="edit-test-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="Fix the function",
            ground_truth=EditGroundTruth(
                test_command=[],
            ),
            mutations=[
                Mutation(
                    file="calc.py",
                    action="replace",
                    find="return a + b",
                    replace="return a * b",
                    occurrence=1,
                )
            ],
        )

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert not valid
        assert "no test_command" in message.lower()

    def test_task_referencing_unknown_repo_rejected(
        self, edit_repo: tuple[Path, Path]
    ) -> None:
        """Task.repo references unknown repo -> verify_mutation_validity returns False."""
        repos_dir, task_dir = edit_repo

        from copeca.config.models import (
            Category,
            Difficulty,
            EditGroundTruth,
            Language,
            Mutation,
            Task,
            TaskType,
        )

        task = Task(
            name="unknown_repo_task",
            description="Edit task referencing a nonexistent repo",
            source="copeca-test (MIT)",
            repo="nonexistent-repo",
            type=TaskType.edit,
            category=Category.fix,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="Fix the function",
            ground_truth=EditGroundTruth(
                test_command=["true"],
            ),
            mutations=[
                Mutation(
                    file="calc.py",
                    action="replace",
                    find="return a + b",
                    replace="return a * b",
                    occurrence=1,
                )
            ],
        )

        repo_mgr = GitWorktreeManager(repos_dir=repos_dir)
        repos = load_repos(task_dir.parent / "repos.yaml")

        valid, message = verify_mutation_validity(task, repo_mgr, repos)
        assert not valid
        assert "not found" in message.lower()


class TestCheckTaskCLI:
    """Test `copeca check-task` CLI command via subprocess."""

    def test_check_task_cli_exit_zero(
        self, edit_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Subprocess call to copeca check-task with valid task -> exit 0."""
        repos_dir, task_dir = edit_repo

        result = subprocess.run(
            [
                "copeca",
                "check-task",
                str(EDIT_VALID),
                "--repos-dir",
                str(repos_dir),
            ],
            cwd=str(task_dir.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Valid edit task" in result.stdout

    def test_check_task_cli_exit_one(
        self, edit_repo: tuple[Path, Path]
    ) -> None:
        """Subprocess call to copeca check-task with weak task -> exit 1."""
        repos_dir, task_dir = edit_repo

        result = subprocess.run(
            [
                "copeca",
                "check-task",
                str(EDIT_WEAK),
                "--repos-dir",
                str(repos_dir),
            ],
            cwd=str(task_dir.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1, (
            f"Expected exit 1, got {result.returncode}:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "FAILED" in result.stderr

    def test_check_task_cli_help(self) -> None:
        """copeca check-task --help shows usage."""
        result = subprocess.run(
            ["copeca", "check-task", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "check-task" in result.stdout
        assert "edit task" in result.stdout.lower()
