"""Multi-strategy correctness checking for copeca tasks.

ADAPTED from tilth benchmark/tasks/base.py check_correctness().

Architecture: domain layer. Pure functions — no I/O, no subprocess.
Takes a RunResult (or raw text) and GroundTruth, returns (correct, detail).
"""

from dataclasses import dataclass

from copeca.config.models import ComprehensionGroundTruth, EditGroundTruth


@dataclass
class CorrectnessDetail:
    """Per-strategy correctness breakdown."""

    required_strings_passed: bool = False
    all_of_passed: bool | None = None  # None = not applicable
    forbidden_strings_passed: bool = True
    test_command_passed: bool | None = None  # None = not applicable (comprehension task)
    reason: str = ""


def _check_strings(text: str, strings: list[str]) -> bool:
    """Check that all strings appear in text (case-insensitive substring)."""
    lowered = text.lower()
    return all(s.lower() in lowered for s in strings)


def check_correctness(
    ground_truth: ComprehensionGroundTruth | EditGroundTruth,
    result_text: str,
    test_command_passed: bool | None = None,
) -> tuple[bool, CorrectnessDetail]:
    """Check correctness of an agent's output against ground truth.

    Comprehension tasks: correct = required AND all_of AND forbidden.
    Edit tasks: correct = test_command_passed (strings are diagnostic only).

    Args:
        ground_truth: The task's correctness criteria.
        result_text: The agent's textual output.
        test_command_passed: Whether the test_command exited 0 (edit tasks).

    Returns:
        (correct: bool, detail: CorrectnessDetail) tuple.
    """
    detail = CorrectnessDetail()

    # required_strings (applies to both task types)
    if ground_truth.required_strings:
        detail.required_strings_passed = _check_strings(
            result_text, ground_truth.required_strings
        )
    else:
        # No required strings → trivially pass
        detail.required_strings_passed = True

    # forbidden_strings (applies to both)
    if ground_truth.forbidden_strings:
        detail.forbidden_strings_passed = not _check_strings(
            result_text, ground_truth.forbidden_strings
        )

    if isinstance(ground_truth, ComprehensionGroundTruth):
        # Comprehension: required + all_of + forbidden all must pass
        detail.test_command_passed = None

        # all_of
        if ground_truth.all_of:
            detail.all_of_passed = _check_strings(result_text, ground_truth.all_of)

        # Correct if every check that applies passed
        checks = [detail.required_strings_passed]
        if detail.all_of_passed is not None:
            checks.append(detail.all_of_passed)
        checks.append(detail.forbidden_strings_passed)

        correct = all(checks)
        if not correct:
            failures = []
            if not detail.required_strings_passed:
                failures.append("missing required strings")
            if detail.all_of_passed is False:
                failures.append("missing all_of entries")
            if not detail.forbidden_strings_passed:
                failures.append("contains forbidden strings")
            detail.reason = "; ".join(failures)
        else:
            detail.reason = "All checks passed"

        return correct, detail

    elif isinstance(ground_truth, EditGroundTruth):
        # Edit: test_command is authoritative
        detail.all_of_passed = None

        if test_command_passed is not None:
            detail.test_command_passed = test_command_passed
            correct = test_command_passed
            if correct:
                detail.reason = "Test command passed"
            else:
                detail.reason = "Test command failed"
        else:
            # No test result — treat as failing
            detail.test_command_passed = False
            correct = False
            detail.reason = "No test command result"

        return correct, detail

    # Fallback (shouldn't reach)
    return False, detail
