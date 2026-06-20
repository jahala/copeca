"""Edit task mutation validity verification.

Architecture invariant #5: Every edit task proves its mutation bites.
check-task verifies the test passes on clean code and fails on mutated code.

Architecture: orchestration layer. Coordinates domain + adapters.
Depends on port interfaces, never on concrete adapters.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from copeca.config.models import Task
from copeca.tasks.mutations import MutationError, apply_mutations

logger = logging.getLogger(__name__)


def verify_mutation_validity(
    task: Task,
    repo_mgr: Any,
    repos: dict[str, Any],
) -> tuple[bool, str]:
    """Verify edit task mutation validity.

    Architecture invariant #5: Test must pass on clean code AND fail on
    mutated code. A task that passes on mutated code has a weak test and
    must not enter the corpus.

    Args:
        task: The edit task to verify.
        repo_mgr: Repo manager providing worktree operations.
        repos: Dict mapping repo keys to Repo models (for URIs and commits).

    Returns:
        (valid: bool, message: str) tuple. valid=True means the mutation
        is correctly detected by the test command.
    """
    if task.type.value != "edit":
        return False, f"Task '{task.name}' is not an edit task (type={task.type.value})"

    if not task.mutations:
        return False, f"Task '{task.name}' is an edit task but has no mutations"

    gt = task.ground_truth
    if not hasattr(gt, "test_command") or not gt.test_command:
        return False, f"Task '{task.name}' has no test_command in ground_truth"

    test_command: list[str] = list(gt.test_command)  # pyright: ignore[reportAttributeAccessIssue]

    # Resolve repo info
    repo_info = repos.get(task.repo)
    if repo_info is None:
        return False, f"Repo '{task.repo}' not found in repo registry"

    repo_uri: str = repo_info.url
    repo_commit: str = repo_info.commit

    # 1. Verify toolchain
    repo_mgr.verify_toolchain(task.repo)

    # 2. Create worktree at pinned commit
    worktree = repo_mgr.create_worktree(
        task.repo, commit=repo_commit, uri=repo_uri
    )

    try:
        # 3. Run setup
        setup_cmd = list(repo_info.setup_command) if repo_info.setup_command else None
        repo_mgr.setup(worktree, setup_command=setup_cmd)

        # 4. Run test_command on CLEAN code — must pass (exit 0)
        #    Set PYTHONDONTWRITEBYTECODE to prevent stale .pyc from
        #    contaminating the mutated run.
        logger.info("Running test_command on clean code: %s", " ".join(test_command))
        no_bytecode_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        clean_result = subprocess.run(
            test_command,
            cwd=worktree,
            capture_output=True,
            text=True,
            env=no_bytecode_env,
        )
        if clean_result.returncode != 0:
            return (
                False,
                f"Test command failed on CLEAN code (exit {clean_result.returncode}): "
                f"{clean_result.stderr.strip()[:200]}",
            )

        # 5. Apply mutations (resolved relative to worktree)
        logger.info("Applying %d mutation(s)", len(task.mutations))
        apply_mutations(task.mutations, base_path=Path(worktree))
        # 6. Run test_command on MUTATED code — must FAIL (exit != 0)
        logger.info("Running test_command on mutated code: %s", " ".join(test_command))
        mutated_result = subprocess.run(
            test_command,
            cwd=worktree,
            capture_output=True,
            text=True,
            env=no_bytecode_env,
        )
        if mutated_result.returncode == 0:
            return (
                False,
                "Mutation does not break the test — weak test, task must not enter corpus",
            )

        # Both checks passed
        return (
            True,
            f"Valid edit task: test passes on clean code, fails on mutated code "
            f"(exit {mutated_result.returncode})",
        )

    except MutationError as exc:
        return (False, f"Mutation application failed: {exc}")

    finally:
        # 7. Reset worktree
        repo_mgr.reset(worktree)
