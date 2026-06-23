"""Tests for the post-hoc symmetric trace gate (ISO-7).

The trace gate is a vendor-neutral contamination backstop that reads the
parsed tool trace (not config) to prove an A/B was clean:
- BASELINE arm: must contain NONE of the tool-under-test's tools in its
  tool_sequence. A contaminated baseline record is flagged CONTAMINATED_TRACE
  and excluded from the delta computation.
- EXPERIMENTAL arm: must have used the tool at least once (tool_adopted).

Architecture: analysis/contamination.py is a pure domain module —
no I/O, no subprocess, no network.
"""

from copeca.analysis.contamination import (
    derive_tool_under_test_prefixes,
    filter_clean_baseline,
    flag_contaminated_baseline,
)
from copeca.analysis.report import generate_report

# ── Helpers ───────────────────────────────────────────────────────────────────


def _rec(
    task: str = "task_a",
    mode: str = "baseline",
    total_cost_usd: float = 0.10,
    correct: bool = True,
    tool_sequence: list[str] | None = None,
    tool_adopted: bool | None = None,
    control: bool | None = None,
) -> dict:
    """Minimal JSONL record for trace-gate tests."""
    r: dict = {
        "task": task,
        "mode": mode,
        "total_cost_usd": total_cost_usd,
        "correct": correct,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    if tool_sequence is not None:
        r["tool_sequence"] = tool_sequence
    if tool_adopted is not None:
        r["tool_adopted"] = tool_adopted
    if control is not None:
        r["control"] = control
    return r


# ── Unit: derive_tool_under_test_prefixes ─────────────────────────────────────


class TestDeriveToolUnderTestPrefixes:
    """The gate infers the tool-under-test set from the experimental arm's
    tool_sequence entries — specifically the mcp__ names actually called."""

    def test_derives_prefix_from_experimental_records(self):
        recs = [
            _rec(mode="baseline", tool_sequence=[]),
            _rec(
                mode="tilth",
                tool_adopted=True,
                tool_sequence=["mcp__tilth__tilth_read", "mcp__tilth__tilth_search"],
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes

    def test_empty_when_no_mcp_tools_called(self):
        recs = [
            _rec(mode="baseline", tool_sequence=[]),
            _rec(mode="experimental", tool_adopted=False, tool_sequence=["str_replace_editor"]),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert prefixes == set()

    def test_empty_when_no_experimental_arm(self):
        recs = [_rec(mode="baseline", tool_sequence=[])]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert prefixes == set()

    def test_multiple_servers_collected(self):
        recs = [
            _rec(mode="baseline", tool_sequence=[]),
            _rec(
                mode="exp",
                tool_adopted=True,
                tool_sequence=["mcp__alpha__do_thing", "mcp__beta__other"],
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__alpha__" in prefixes
        assert "mcp__beta__" in prefixes

    def test_only_uses_experimental_arm_not_baseline(self):
        # Even if a baseline record accidentally has mcp tools, the PREFIX
        # derivation ignores baseline records — it only reads experimental.
        recs = [
            _rec(
                mode="baseline",
                tool_sequence=["mcp__rogue__leaked"],
                # tool_adopted is None (baseline)
            ),
            _rec(mode="tilth", tool_adopted=True, tool_sequence=["mcp__tilth__tilth_grok"]),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes
        assert "mcp__rogue__" not in prefixes


# ── Unit: flag_contaminated_baseline ─────────────────────────────────────────


class TestFlagContaminatedBaseline:
    """Baseline records whose tool_sequence overlaps the tool-under-test
    prefixes are flagged CONTAMINATED_TRACE."""

    def test_clean_baseline_not_flagged(self):
        r = _rec(mode="baseline", tool_sequence=["str_replace_editor", "read_file"])
        prefixes = {"mcp__tilth__"}
        flagged = flag_contaminated_baseline(r, prefixes)
        assert flagged is False

    def test_contaminated_baseline_flagged(self):
        r = _rec(mode="baseline", tool_sequence=["mcp__tilth__tilth_read", "str_replace_editor"])
        prefixes = {"mcp__tilth__"}
        flagged = flag_contaminated_baseline(r, prefixes)
        assert flagged is True

    def test_empty_tool_sequence_never_flagged(self):
        r = _rec(mode="baseline", tool_sequence=[])
        prefixes = {"mcp__tilth__"}
        flagged = flag_contaminated_baseline(r, prefixes)
        assert flagged is False

    def test_missing_tool_sequence_never_flagged(self):
        r = _rec(mode="baseline")  # no tool_sequence key
        prefixes = {"mcp__tilth__"}
        flagged = flag_contaminated_baseline(r, prefixes)
        assert flagged is False

    def test_empty_prefixes_never_flags_anything(self):
        r = _rec(mode="baseline", tool_sequence=["mcp__tilth__tilth_read"])
        flagged = flag_contaminated_baseline(r, set())
        assert flagged is False

    def test_experimental_record_never_flagged(self):
        # The gate only applies to baseline records
        r = _rec(
            mode="tilth",
            tool_adopted=True,
            tool_sequence=["mcp__tilth__tilth_read"],
        )
        prefixes = {"mcp__tilth__"}
        flagged = flag_contaminated_baseline(r, prefixes)
        assert flagged is False


# ── Unit: filter_clean_baseline ───────────────────────────────────────────────


class TestFilterCleanBaseline:
    """filter_clean_baseline returns (clean_records, contaminated_records)
    splitting the full record set."""

    def test_all_clean_passes_through(self):
        recs = [
            _rec(mode="baseline", tool_sequence=[], correct=True),
            _rec(mode="tilth", tool_adopted=True, tool_sequence=["mcp__tilth__tilth_read"]),
        ]
        clean, contaminated = filter_clean_baseline(recs)
        assert len(clean) == 2
        assert contaminated == []

    def test_contaminated_baseline_excluded(self):
        recs = [
            _rec(task="t", mode="baseline", tool_sequence=["mcp__tilth__tilth_read"]),
            _rec(
                task="t", mode="tilth", tool_adopted=True, tool_sequence=["mcp__tilth__tilth_read"]
            ),
        ]
        clean, contaminated = filter_clean_baseline(recs)
        # The contaminated baseline is excluded from clean
        assert all(r["mode"] != "baseline" for r in clean)
        assert len(contaminated) == 1
        assert contaminated[0]["mode"] == "baseline"

    def test_partial_contamination_only_bad_records_excluded(self):
        recs = [
            _rec(task="t1", mode="baseline", tool_sequence=[], correct=True),
            _rec(
                task="t1", mode="tilth", tool_adopted=True, tool_sequence=["mcp__tilth__tilth_read"]
            ),
            _rec(
                task="t2", mode="baseline", tool_sequence=["mcp__tilth__tilth_read"], correct=True
            ),
            _rec(
                task="t2", mode="tilth", tool_adopted=True, tool_sequence=["mcp__tilth__tilth_read"]
            ),
        ]
        clean, contaminated = filter_clean_baseline(recs)
        assert len(contaminated) == 1  # only t2 baseline is contaminated
        # t1 baseline is clean
        t1_baselines = [r for r in clean if r["task"] == "t1" and r["mode"] == "baseline"]
        assert len(t1_baselines) == 1

    def test_no_experimental_arm_no_prefixes_derived(self):
        # If there's no experimental arm with mcp tools, nothing is contaminated
        recs = [_rec(mode="baseline", tool_sequence=["str_replace_editor"])]
        clean, contaminated = filter_clean_baseline(recs)
        assert len(clean) == 1
        assert contaminated == []


# ── Integration: report renders Trace Gate section ────────────────────────────


class TestReportTraceGate:
    """generate_report surfaces contaminated baseline records and excludes
    them from the delta computation."""

    def _make_clean_ab(self) -> list[dict]:
        """Clean A/B: baseline has no tool-under-test tools."""
        return [
            _rec(
                task="cap1",
                mode="baseline",
                correct=True,
                total_cost_usd=0.10,
                tool_sequence=[],
                tool_adopted=None,
            ),
            _rec(
                task="cap1",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
        ]

    def _make_contaminated_ab(self) -> list[dict]:
        """Contaminated A/B: baseline used tilth tool."""
        return [
            _rec(
                task="cap1",
                mode="baseline",
                correct=True,
                total_cost_usd=0.10,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=None,
            ),
            _rec(
                task="cap1",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
        ]

    def test_trace_gate_section_absent_when_no_tool_sequence(self):
        """Gate section omitted when records carry no tool_sequence at all."""
        recs = [
            _rec(task="t", mode="baseline", correct=True),
            _rec(task="t", mode="exp", correct=True, tool_adopted=True),
        ]
        report = generate_report(recs)
        assert "Trace Gate" not in report
        assert "CONTAMINATED_TRACE" not in report

    def test_trace_gate_section_absent_when_clean(self):
        """Gate section omitted when no baseline records are contaminated."""
        recs = self._make_clean_ab()
        report = generate_report(recs)
        assert "CONTAMINATED_TRACE" not in report

    def test_trace_gate_section_present_when_contaminated(self):
        """Gate section appears when a baseline record is contaminated."""
        recs = self._make_contaminated_ab()
        report = generate_report(recs)
        assert "Trace Gate" in report
        assert "CONTAMINATED_TRACE" in report

    def test_contaminated_baseline_excluded_from_delta(self):
        """The contaminated baseline record must be excluded from the delta.

        Setup: two tasks — one clean, one contaminated baseline.
        The contaminated baseline would produce a large delta if included.
        After exclusion the delta is computed only from the clean task pair.
        """
        # task_clean: baseline $0.10, tilth $0.05 → -50% delta
        # task_dirty: baseline uses tilth tool (CONTAMINATED_TRACE) → excluded
        recs = [
            # clean task
            _rec(
                task="clean",
                mode="baseline",
                correct=True,
                total_cost_usd=0.10,
                tool_sequence=[],
                tool_adopted=None,
            ),
            _rec(
                task="clean",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
            # dirty task — baseline is contaminated
            _rec(
                task="dirty",
                mode="baseline",
                correct=True,
                total_cost_usd=999.0,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=None,
            ),
            _rec(
                task="dirty",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
        ]
        report = generate_report(recs)
        # The contaminated record at $999 would heavily distort the delta;
        # after exclusion the delta should reflect only the clean task.
        # The delta for the clean task is -50%, so the report should NOT show
        # an extreme value dominated by $999 baseline cost.
        assert "CONTAMINATED_TRACE" in report
        # If $999 were included, delta would be >> 0 (baseline far cheaper than
        # the excluded-dirty baseline distorts the ratio). The clean pair alone
        # shows tilth cheaper, so delta must be negative (tilth better).
        # We check that the delta line is NOT positive-dominant from the bad record.
        # Concrete: -50% expected; $999 baseline inclusion would give a wildly
        # different direction. We just assert delta contains "-" (negative).
        assert "-50.0%" in report or "-50%" in report

    def test_clean_ab_full_baseline_included_in_delta(self):
        """When no contamination, all baseline records contribute to the delta."""
        recs = self._make_clean_ab()
        report = generate_report(recs)
        # -50% delta expected: tilth $0.05 vs baseline $0.10
        assert "-50.0%" in report or "-50%" in report
        assert "Trace Gate" not in report

    def test_contamination_report_names_the_task_and_mode(self):
        """The contamination section names the contaminated task."""
        recs = self._make_contaminated_ab()
        report = generate_report(recs)
        # The task name should appear in the contamination section
        assert "cap1" in report

    def test_multiple_contaminated_records_all_listed(self):
        """All contaminated records are surfaced, not just the first."""
        recs = [
            _rec(
                task="t1",
                mode="baseline",
                correct=True,
                total_cost_usd=0.10,
                tool_sequence=["mcp__tilth__tilth_read"],
            ),
            _rec(
                task="t1",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
            _rec(
                task="t2",
                mode="baseline",
                correct=True,
                total_cost_usd=0.10,
                tool_sequence=["mcp__tilth__tilth_search"],
            ),
            _rec(
                task="t2",
                mode="tilth",
                correct=True,
                total_cost_usd=0.05,
                tool_sequence=["mcp__tilth__tilth_search"],
                tool_adopted=True,
            ),
        ]
        report = generate_report(recs)
        assert "t1" in report
        assert "t2" in report
