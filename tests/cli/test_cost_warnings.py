"""Test that cost safeguard warnings surface to stderr.

Two safeguards are tested:
  (a) vendor_cost_divergence >5% → warning echoed to stderr
  (b) stale pricing table → staleness warning echoed to stderr

Both tests call the helper functions in cli.py directly so they are
fully hermetic — no real subprocess/agent is needed.

Architecture: unit tests for the thin I/O helpers that live at the
cli.py boundary (S.U.P.E.R. — side effects at the edge).
"""

from __future__ import annotations

from unittest.mock import patch
from datetime import date


class TestVendorCostDivergenceWarning:
    """extract_vendor_divergence_warning returns warning when divergence >5%."""

    def test_returns_warning_when_divergence_exceeds_threshold(self) -> None:
        from copeca.cli import extract_vendor_divergence_warning

        record = {
            "metadata": {
                "vendor_cost_divergence": 0.08,
                "vendor_cost_divergence_warning": (
                    "Computed cost (0.1080) differs from vendor cost (0.1000) by 8.0%"
                ),
            }
        }
        warning = extract_vendor_divergence_warning(record)
        assert warning is not None
        assert "8.0%" in warning

    def test_returns_none_when_no_divergence_in_metadata(self) -> None:
        from copeca.cli import extract_vendor_divergence_warning

        record: dict = {"metadata": {"copeca_version": "0.1.0"}}
        assert extract_vendor_divergence_warning(record) is None

    def test_returns_none_when_no_metadata(self) -> None:
        from copeca.cli import extract_vendor_divergence_warning

        record: dict = {"correct": True}
        assert extract_vendor_divergence_warning(record) is None

    def test_returns_none_when_divergence_below_threshold(self) -> None:
        """A record without divergence_warning key (stored only when >5%) returns None."""
        from copeca.cli import extract_vendor_divergence_warning

        # run.py only writes vendor_cost_divergence_warning when >5%, so
        # a record without that key → no warning.
        record: dict = {"metadata": {"copeca_version": "0.1.0"}}
        assert extract_vendor_divergence_warning(record) is None


class TestPricingStalenessWarning:
    """check_pricing_staleness warnings are echoed via emit_staleness_warnings."""

    def test_stale_pricing_returns_warnings(self) -> None:
        """A pricing entry older than 30 days triggers staleness warnings."""
        from copeca.orchestration.validation import check_pricing_staleness

        stale_date = "2020-01-01"
        pricing = {
            "claude-opus-4-5": {
                "input": 15.0,
                "output": 75.0,
                "cache_creation": 18.75,
                "cache_read": 1.5,
                "updated": stale_date,
            }
        }
        warnings = check_pricing_staleness(pricing)
        assert len(warnings) == 1
        assert "claude-opus-4-5" in warnings[0]

    def test_fresh_pricing_returns_no_warnings(self) -> None:
        """A pricing entry updated today triggers no warnings."""
        from copeca.orchestration.validation import check_pricing_staleness

        today_str = date.today().isoformat()
        pricing = {
            "claude-sonnet-4-5": {
                "input": 3.0,
                "output": 15.0,
                "cache_creation": 3.75,
                "cache_read": 0.3,
                "updated": today_str,
            }
        }
        warnings = check_pricing_staleness(pricing)
        assert warnings == []

    def test_emit_staleness_warnings_prints_to_stderr(
        self, capsys
    ) -> None:
        """emit_staleness_warnings echoes each warning to stderr."""
        from copeca.cli import emit_staleness_warnings

        warnings = [
            "Pricing for 'model-a' is 45 days old (updated 2020-01-01)",
            "Pricing for 'model-b' is missing 'updated' field",
        ]
        emit_staleness_warnings(warnings)

        captured = capsys.readouterr()
        assert "model-a" in captured.err
        assert "model-b" in captured.err
        # Nothing on stdout
        assert captured.out == ""

    def test_emit_staleness_warnings_silent_when_empty(self, capsys) -> None:
        """emit_staleness_warnings produces no output when list is empty."""
        from copeca.cli import emit_staleness_warnings

        emit_staleness_warnings([])
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_emit_vendor_divergence_warning_prints_to_stderr(
        self, capsys
    ) -> None:
        """emit_vendor_divergence_warning echoes the warning to stderr."""
        from copeca.cli import emit_vendor_divergence_warning

        warning = "Computed cost (0.1080) differs from vendor cost (0.1000) by 8.0%"
        emit_vendor_divergence_warning(warning)

        captured = capsys.readouterr()
        assert "8.0%" in captured.err
        assert captured.out == ""

    def test_emit_vendor_divergence_warning_silent_when_none(
        self, capsys
    ) -> None:
        """emit_vendor_divergence_warning produces no output when warning is None."""
        from copeca.cli import emit_vendor_divergence_warning

        emit_vendor_divergence_warning(None)
        captured = capsys.readouterr()
        assert captured.err == ""
