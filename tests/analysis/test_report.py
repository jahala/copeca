"""Test markdown report generation — pure text generation from JSONL records."""

import pytest

from copeca.analysis.report import generate_report


def _make_record(
    task: str = "task_a",
    mode: str = "baseline",
    total_cost_usd: float = 0.10,
    correct: bool = True,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    adversarial_flags: dict | None = None,
    per_turn_output_tokens: list[int] | None = None,
    tool_sequence: list[str] | None = None,
    language: str | None = None,
    difficulty: str | None = None,
) -> dict:
    """Helper to build a minimal JSONL record."""
    record: dict = {
        "task": task,
        "mode": mode,
        "total_cost_usd": total_cost_usd,
        "correct": correct,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
    }
    if adversarial_flags is not None:
        record["adversarial_flags"] = adversarial_flags
    if per_turn_output_tokens is not None:
        record["per_turn_output_tokens"] = per_turn_output_tokens
    if tool_sequence is not None:
        record["tool_sequence"] = tool_sequence
    if language is not None:
        record["language"] = language
    if difficulty is not None:
        record["difficulty"] = difficulty
    return record


class TestGenerateReport:
    """Tests for generate_report — markdown report from records."""

    def test_report_contains_cost_per_correct_headline(self):
        """Report must show cost-per-correct for each mode and the delta."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=False),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=False),
        ]
        report = generate_report(records)

        # Should mention cost per correct
        assert "cost per correct" in report.lower()
        # Should mention both modes
        assert "baseline" in report.lower()
        assert "experimental" in report.lower()
        # Should mention delta
        assert "delta" in report.lower()

    def test_report_contains_per_task_table(self):
        """Report must include a per-task breakdown table."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=False),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=False),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=True),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=False),
            _make_record(task="task_b", mode="experimental", total_cost_usd=0.10, correct=True),
            _make_record(task="task_b", mode="experimental", total_cost_usd=0.10, correct=False),
        ]
        report = generate_report(records)

        # Should mention both tasks
        assert "task_a" in report
        assert "task_b" in report
        # Should have a table structure (markdown table uses pipes)
        assert "|" in report

    def test_report_contains_cost_breakdown(self):
        """Report must include token/cost breakdown per mode."""
        records = [
            _make_record(
                task="task_a", mode="baseline",
                input_tokens=2000, output_tokens=1000,
                cache_creation_tokens=500, cache_read_tokens=100,
            ),
            _make_record(
                task="task_a", mode="experimental",
                input_tokens=1500, output_tokens=800,
                cache_creation_tokens=300, cache_read_tokens=50,
            ),
        ]
        report = generate_report(records)

        # Should mention token types
        assert "input" in report.lower()
        assert "output" in report.lower()

    def test_report_single_mode_no_delta(self):
        """When only one mode is present, the report should not show delta."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=False),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=True),
        ]
        report = generate_report(records)

        # Should still produce a report
        assert "baseline" in report.lower()
        assert "task_a" in report
        assert "task_b" in report
        # No delta if single mode
        assert "delta" not in report.lower()

    def test_report_correct_summary_per_mode(self):
        """Report shows correct/total per mode."""
        records = [
            _make_record(task="task_a", mode="baseline", correct=True),
            _make_record(task="task_a", mode="baseline", correct=True),
            _make_record(task="task_a", mode="baseline", correct=False),
            _make_record(task="task_a", mode="experimental", correct=True),
            _make_record(task="task_a", mode="experimental", correct=False),
            _make_record(task="task_a", mode="experimental", correct=False),
        ]
        report = generate_report(records)

        # Should show correct counts somewhere
        assert "2" in report  # baseline has 2 correct
        assert "1" in report  # experimental has 1 correct

    def test_report_empty_returns_header_only(self):
        """Empty records should return a valid (if minimal) markdown string."""
        report = generate_report([])
        assert isinstance(report, str)
        assert len(report) > 0

    # ── Bug 1: Bootstrap CI tests ──────────────────────────────────────────

    def test_report_contains_ci_in_headline(self):
        """When multiple modes exist, the delta headline includes a 95% CI."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=False),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=False),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=True),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=False),
            _make_record(task="task_b", mode="experimental", total_cost_usd=0.15, correct=True),
            _make_record(task="task_b", mode="experimental", total_cost_usd=0.15, correct=False),
        ]
        report = generate_report(records)

        # CI annotation must appear in the delta headline
        assert "95% CI" in report
        assert "[" in report and "]" in report  # bracket notation for CI
        # Per-task table should also have CI column header
        assert "Delta%" in report

    def test_report_no_ci_when_single_mode(self):
        """Single mode records produce no CI annotations."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.20, correct=True),
        ]
        report = generate_report(records)

        assert "95% CI" not in report
        assert "delta" not in report.lower()

    # ── Bug 2: Adversarial flags + sparklines tests ────────────────────────

    def test_report_contains_adversarial_summary(self):
        """Report includes an Adversarial Flags section when records have flags."""
        records = [
            _make_record(
                task="task_a", mode="baseline",
                adversarial_flags={
                    "token_snowball": True,
                    "talkative_failure": False,
                    "error": False,
                    "timeout": True,
                    "budget_exhausted": False,
                },
            ),
            _make_record(
                task="task_a", mode="baseline",
                adversarial_flags={
                    "token_snowball": False,
                    "talkative_failure": False,
                    "error": True,
                    "timeout": False,
                    "budget_exhausted": False,
                },
            ),
            _make_record(
                task="task_b", mode="experimental",
                adversarial_flags={
                    "token_snowball": False,
                    "talkative_failure": True,
                    "error": False,
                    "timeout": False,
                    "budget_exhausted": True,
                },
            ),
        ]
        report = generate_report(records)

        assert "adversarial" in report.lower()
        assert "token_snowball" in report
        assert "talkative_failure" in report
        assert "budget_exhausted" in report
        assert "33.3%" in report  # 1 of 3 token_snowball True (33.3%)

    def test_report_handles_missing_flags(self):
        """Records without adversarial_flags — section is gracefully skipped."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
        ]
        report = generate_report(records)

        # Should not contain adversarial section
        assert "Adversarial Flags" not in report
        # Report should still be valid
        assert "Copeca Report" in report

    def test_report_contains_token_usage_sparklines(self):
        """When records have per-turn data, sparklines section appears."""
        records = [
            _make_record(
                task="task_a", mode="baseline",
                per_turn_output_tokens=[100, 250, 400, 300, 500],
            ),
            _make_record(
                task="task_a", mode="experimental",
                per_turn_output_tokens=[80, 120, 200, 180, 220],
            ),
        ]
        report = generate_report(records)

        assert "Token Usage Sparklines" in report
        # Sparklines contain Unicode block elements
        assert any(c in report for c in "▁▂▃▄▅▆▇█")

    def test_report_handles_missing_turn_data(self):
        """Records without per-turn data — sparklines section skipped gracefully."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
        ]
        report = generate_report(records)

        assert "Token Usage Sparklines" not in report
        assert "Copeca Report" in report

    # ── Bug 3: Tool adoption + per-category breakdowns ────────────────────

    def test_report_contains_tool_adoption(self):
        """Report includes Tool Adoption section when records carry tool_sequence."""
        records = [
            _make_record(task="task_a", mode="baseline", tool_sequence=["read", "edit"]),
            _make_record(task="task_a", mode="baseline", tool_sequence=[]),
            _make_record(task="task_a", mode="baseline", tool_sequence=["read"]),
            _make_record(task="task_a", mode="experimental", tool_sequence=[]),
            _make_record(task="task_a", mode="experimental", tool_sequence=["read"]),
        ]
        report = generate_report(records)

        assert "Tool Adoption" in report
        assert "Adoption %" in report
        # baseline: 2 of 3 have tools → 66.7%
        assert "66.7%" in report
        # experimental: 1 of 2 have tools → 50.0%
        assert "50.0%" in report

    def test_report_contains_per_language_breakdown(self):
        """Report includes Per-Language Breakdown when records carry language."""
        records = [
            _make_record(task="task_a", mode="baseline", language="python",
                         total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", language="python",
                         total_cost_usd=0.10, correct=False),
            _make_record(task="task_a", mode="experimental", language="python",
                         total_cost_usd=0.05, correct=True),
            _make_record(task="task_b", mode="baseline", language="javascript",
                         total_cost_usd=0.20, correct=True),
            _make_record(task="task_b", mode="experimental", language="javascript",
                         total_cost_usd=0.10, correct=True),
        ]
        report = generate_report(records)

        assert "Per-Language Breakdown" in report
        assert "python" in report
        assert "javascript" in report
        # python baseline CPC: 0.20 / 1 = 0.2000
        assert "$0.2000" in report

    def test_report_contains_per_difficulty_breakdown(self):
        """Report includes Per-Difficulty Breakdown when records carry difficulty."""
        records = [
            _make_record(task="task_a", mode="baseline", difficulty="easy",
                         total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="experimental", difficulty="easy",
                         total_cost_usd=0.05, correct=True),
            _make_record(task="task_b", mode="baseline", difficulty="hard",
                         total_cost_usd=0.30, correct=True),
            _make_record(task="task_b", mode="baseline", difficulty="hard",
                         total_cost_usd=0.30, correct=False),
            _make_record(task="task_b", mode="experimental", difficulty="hard",
                         total_cost_usd=0.20, correct=True),
        ]
        report = generate_report(records)

        assert "Per-Difficulty Breakdown" in report
        assert "easy" in report
        assert "hard" in report
        # hard baseline CPC: 0.60 / 1 = 0.6000
        assert "$0.6000" in report

    def test_report_skips_sections_when_no_data(self):
        """Sections should be skipped gracefully when data fields are absent."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
        ]
        report = generate_report(records)

        assert "Tool Adoption" not in report
        assert "Per-Language Breakdown" not in report
        assert "Per-Difficulty Breakdown" not in report
        # Report should still be valid
        assert "Copeca Report" in report
        assert "Cost Per Correct Answer" in report

    # ── Bug F-C1: zero-correct mode must not render as $0.0000 or -100% ──────

    def test_report_zero_correct_experimental_shows_na(self):
        """Experimental mode with 0 correct answers must show 'n/a' not '$0.0000'.

        Repro: experimental gets everything wrong at 5× baseline spend.
        A $0.0000 CPC entry and a -100% delta would make the WORSE tool look BETTER.
        """
        records = [
            # baseline: 2 runs, both correct
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_b", mode="baseline", total_cost_usd=0.10, correct=True),
            # experimental: 2 runs, NONE correct, 5× spend
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.50, correct=False),
            _make_record(task="task_b", mode="experimental", total_cost_usd=0.50, correct=False),
        ]
        report = generate_report(records)

        # (i) Cost-per-correct column shows n/a for the 0-correct mode
        assert "n/a" in report.lower()
        # (ii) Must NOT show a negative percentage delta (the inversion)
        assert "-100" not in report
        # (iii) Accuracy column must be present
        assert "accuracy" in report.lower() or "rate" in report.lower()

    def test_report_zero_correct_headline_describes_situation(self):
        """When experimental has 0 correct overall, the delta headline says so explicitly."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.50, correct=False),
        ]
        report = generate_report(records)

        # Headline must not claim a percentage improvement
        assert "-100" not in report
        # Headline must communicate that 0/N were correct
        assert "0/" in report or "0 correct" in report.lower() or "n/a" in report.lower()

    def test_report_accuracy_shown_alongside_cost_per_correct(self):
        """Accuracy (correct/total) must appear as a column next to cost-per-correct."""
        records = [
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", mode="baseline", total_cost_usd=0.10, correct=False),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", mode="experimental", total_cost_usd=0.05, correct=True),
        ]
        report = generate_report(records)

        # accuracy/rate column must appear in the Cost Per Correct Answer section header
        assert "accuracy" in report.lower() or "rate" in report.lower()


class TestReportExcludesFailedRuns:
    """Crashed runs (error set) are excluded from the accuracy denominator and
    surfaced in a Failed Runs note — never silently counted as a result (SD-B).
    """

    def test_failed_run_excluded_from_accuracy_and_noted(self):
        records = [
            {
                "task": "t1", "mode": "baseline", "total_cost_usd": 0.20,
                "correct": True, "input_tokens": 100, "output_tokens": 50,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
            },
            {
                "task": "t1", "mode": "baseline", "total_cost_usd": 0.0,
                "correct": False, "input_tokens": 0, "output_tokens": 0,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
                "error": "runner exited with code 1",
            },
        ]
        report = generate_report(records)
        # accuracy denominator excludes the crash -> 1/1, not 1/2
        assert "1/1" in report
        assert "1/2" not in report
        # the failure stays visible, not hidden
        assert "Failed" in report
