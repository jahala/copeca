"""Test multi-strategy correctness validator — required_strings, all_of, forbidden, test_command."""

from copeca.config.models import ComprehensionGroundTruth, EditGroundTruth
from copeca.tasks.validator import check_correctness


class TestRequiredStrings:
    def test_all_present_passes(self):
        gt = ComprehensionGroundTruth(required_strings=["Matcher", "find_at"])
        correct, detail = check_correctness(gt, "answer: Matcher find_at RegexMatcher")
        assert correct is True
        assert detail.required_strings_passed is True

    def test_one_missing_fails(self):
        gt = ComprehensionGroundTruth(required_strings=["Matcher", "missing_term"])
        correct, detail = check_correctness(gt, "answer: Matcher find_at")
        assert correct is False
        assert detail.required_strings_passed is False
        assert "missing required strings" in detail.reason

    def test_empty_required_strings_trivially_passes(self):
        """Empty required_strings trivially passes — nothing to check."""
        gt = ComprehensionGroundTruth(required_strings=[])
        correct, detail = check_correctness(gt, "any output")
        assert detail.required_strings_passed is True
        assert correct is True  # all checks pass with no required strings


class TestAllOf:
    def test_all_present_passes(self):
        gt = ComprehensionGroundTruth(
            required_strings=["base"],
            all_of=["Alpha", "Beta"],
        )
        correct, detail = check_correctness(gt, "base Alpha Beta")
        assert correct is True
        assert detail.all_of_passed is True

    def test_one_missing_fails(self):
        gt = ComprehensionGroundTruth(
            required_strings=["base"],
            all_of=["Alpha", "Missing"],
        )
        correct, detail = check_correctness(gt, "base Alpha")
        assert correct is False
        assert detail.all_of_passed is False
        assert "missing all_of entries" in detail.reason

    def test_empty_all_of_is_none(self):
        gt = ComprehensionGroundTruth(required_strings=["base"], all_of=[])
        correct, detail = check_correctness(gt, "base")
        assert detail.all_of_passed is None


class TestForbiddenStrings:
    def test_no_forbidden_found_passes(self):
        gt = ComprehensionGroundTruth(
            required_strings=["base"],
            forbidden_strings=["panic", "unreachable"],
        )
        correct, detail = check_correctness(gt, "base: safe output")
        assert correct is True
        assert detail.forbidden_strings_passed is True

    def test_forbidden_found_fails(self):
        gt = ComprehensionGroundTruth(
            required_strings=["base"],
            forbidden_strings=["panic"],
        )
        correct, detail = check_correctness(gt, "base: panic! at the disco")
        assert correct is False
        assert detail.forbidden_strings_passed is False
        assert "contains forbidden strings" in detail.reason

    def test_partial_refusal_one_forbidden_present_fails(self):
        """ANY forbidden phrase must trip the guard, not just when ALL are present.

        Regression for F-H3: forbidden_strings used AND logic (via _check_strings/all()),
        so a partial refusal like "I cannot be certain" scored correct=True when the
        second phrase ("unable to") was absent.
        """
        gt = ComprehensionGroundTruth(
            required_strings=["Matcher"],
            forbidden_strings=["I cannot", "unable to"],
        )
        answer = "I cannot be certain, but the Matcher type is the answer"
        correct, detail = check_correctness(gt, answer)
        assert correct is False
        assert detail.forbidden_strings_passed is False
        assert "contains forbidden strings" in detail.reason


class TestComprehensionCorrect:
    def test_all_strategies_pass_returns_true(self):
        gt = ComprehensionGroundTruth(
            required_strings=["Matcher", "find_at"],
            all_of=["trait"],
            forbidden_strings=["panic"],
        )
        correct, detail = check_correctness(gt, "Matcher find_at trait implementation")
        assert correct is True
        assert detail.reason == "All checks passed"
        assert detail.test_command_passed is None  # not applicable

    def test_required_missing_returns_false(self):
        gt = ComprehensionGroundTruth(
            required_strings=["Matcher", "find_at"],
            all_of=["trait"],
            forbidden_strings=["panic"],
        )
        correct, detail = check_correctness(gt, "trait only, no matcher here")
        assert correct is False
        assert not detail.required_strings_passed

    def test_forbidden_found_returns_false(self):
        gt = ComprehensionGroundTruth(
            required_strings=["Matcher"],
            forbidden_strings=["panic"],
        )
        correct, detail = check_correctness(gt, "Matcher found but panic! happened")
        assert correct is False
        assert not detail.forbidden_strings_passed


class TestEditCorrect:
    def test_test_command_passed_returns_true(self):
        gt = EditGroundTruth(test_command=["cargo test"])
        correct, detail = check_correctness(gt, "some output", test_command_passed=True)
        assert correct is True
        assert detail.test_command_passed is True
        assert detail.reason == "Test command passed"

    def test_test_command_failed_returns_false(self):
        gt = EditGroundTruth(test_command=["cargo test"])
        correct, detail = check_correctness(gt, "compile error", test_command_passed=False)
        assert correct is False
        assert detail.test_command_passed is False
        assert detail.reason == "Test command failed"

    def test_strings_are_diagnostic_only(self):
        """Required strings failing should NOT affect correct for edit tasks."""
        gt = EditGroundTruth(
            required_strings=["expected_output"],
            test_command=["cargo test"],
        )
        correct, detail = check_correctness(gt, "wrong output", test_command_passed=True)
        # test_command passed → correct is True, even though required_strings failed
        assert correct is True
        assert detail.required_strings_passed is False  # diagnostic
        assert detail.test_command_passed is True  # authoritative

    def test_no_test_result_defaults_false(self):
        gt = EditGroundTruth(test_command=["cargo test"])
        correct, detail = check_correctness(gt, "some output")
        assert correct is False
        assert detail.test_command_passed is False
        assert detail.reason == "No test command result"


class TestCaseInsensitive:
    def test_case_differences_still_match(self):
        gt = ComprehensionGroundTruth(required_strings=["matcher", "FIND_AT"])
        correct, detail = check_correctness(gt, "Matcher find_at")
        assert correct is True
        assert detail.required_strings_passed is True


class TestEmptyResponse:
    def test_empty_response_fails_all_checks(self):
        gt = ComprehensionGroundTruth(required_strings=["Matcher"])
        correct, detail = check_correctness(gt, "")
        assert correct is False
        assert detail.required_strings_passed is False
        assert detail.reason == "missing required strings"

    def test_empty_response_with_forbidden_still_fails(self):
        gt = ComprehensionGroundTruth(
            required_strings=["Matcher"],
            forbidden_strings=["panic"],
        )
        correct, detail = check_correctness(gt, "")
        assert correct is False
        # required_strings check fails on empty string
        assert detail.required_strings_passed is False
        # forbidden_strings check passes (none found in empty string)
        assert detail.forbidden_strings_passed is True
