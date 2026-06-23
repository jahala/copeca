"""ISO-8 Part 4: declared tool identity closes the ISO-7 trace-gate limitation.

When experimental records carry `tool_under_test` (the declared identity list),
`derive_tool_under_test_prefixes` must PREFER those values over usage inference.
This makes the gate robust even when the experimental arm never called the tool.

The existing ISO-7 tests in test_trace_gate.py must remain green.
"""

from copeca.analysis.contamination import (
    derive_tool_under_test_prefixes,
    filter_clean_baseline,
)


def _exp(
    task: str = "t",
    tool_under_test: list[str] | None = None,
    tool_sequence: list[str] | None = None,
    tool_adopted: bool | None = True,
) -> dict:
    """Experimental arm record."""
    r: dict = {
        "task": task,
        "mode": "tilth",
        "tool_adopted": tool_adopted,
        "total_cost_usd": 0.05,
        "correct": True,
    }
    if tool_under_test is not None:
        r["tool_under_test"] = tool_under_test
    if tool_sequence is not None:
        r["tool_sequence"] = tool_sequence
    return r


def _base(
    task: str = "t",
    tool_sequence: list[str] | None = None,
) -> dict:
    """Baseline arm record."""
    r: dict = {
        "task": task,
        "mode": "baseline",
        "total_cost_usd": 0.10,
        "correct": True,
    }
    if tool_sequence is not None:
        r["tool_sequence"] = tool_sequence
    return r


# ── Unit: derive_tool_under_test_prefixes prefers declared identity ────────────


class TestDeclaredIdentityPreferred:
    def test_declared_identity_used_when_no_tool_calls(self) -> None:
        """Experimental arm has tool_under_test but called NO mcp tools.

        Without declared identity, inference returns {} (empty tool_sequence).
        With declared identity, prefixes come from the tool_under_test field.
        """
        recs = [
            _base(tool_sequence=[]),
            _exp(
                tool_under_test=["mcp__tilth__"],
                tool_sequence=[],  # never called the tool
                tool_adopted=False,
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes

    def test_declared_identity_takes_precedence_over_inference(self) -> None:
        """If declared and inferred differ, declared wins.

        Experimental called mcp__other__ in its sequence but declares
        tool_under_test = ['mcp__tilth__'].  The gate uses mcp__tilth__.
        """
        recs = [
            _base(tool_sequence=[]),
            _exp(
                tool_under_test=["mcp__tilth__"],
                tool_sequence=["mcp__other__some_fn"],
                tool_adopted=True,
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes
        # When declared is present, inferred-only tools from sequence are NOT added
        assert "mcp__other__" not in prefixes

    def test_multiple_declared_servers_all_included(self) -> None:
        """Multiple entries in tool_under_test are all included in prefixes."""
        recs = [
            _base(tool_sequence=[]),
            _exp(
                tool_under_test=["mcp__tilth__", "mcp__alpha__"],
                tool_sequence=[],
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes
        assert "mcp__alpha__" in prefixes

    def test_falls_back_to_inference_when_no_declared_field(self) -> None:
        """Records without tool_under_test field fall back to usage inference."""
        recs = [
            _base(tool_sequence=[]),
            _exp(
                # no tool_under_test key
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes

    def test_empty_declared_list_falls_back_to_inference(self) -> None:
        """An empty tool_under_test list is treated as absent → falls back to inference."""
        recs = [
            _base(tool_sequence=[]),
            _exp(
                tool_under_test=[],  # explicitly empty
                tool_sequence=["mcp__tilth__tilth_read"],
                tool_adopted=True,
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes

    def test_baseline_with_tool_call_flagged_via_declared_identity(self) -> None:
        """Core ISO-8 scenario: experimental never called tool but declared it.
        Baseline DID call it → must be flagged CONTAMINATED_TRACE.
        """
        recs = [
            _base(
                task="t1",
                tool_sequence=["mcp__tilth__tilth_read"],  # baseline used the tool
            ),
            _exp(
                task="t1",
                tool_under_test=["mcp__tilth__"],
                tool_sequence=[],  # experimental never called it
                tool_adopted=False,
            ),
        ]
        clean, contaminated = filter_clean_baseline(recs)
        assert len(contaminated) == 1
        assert contaminated[0]["mode"] == "baseline"
        # The experimental record is in clean (it's not a baseline)
        exp_records = [r for r in clean if r["mode"] == "tilth"]
        assert len(exp_records) == 1

    def test_declared_identity_union_across_multiple_experimental_records(self) -> None:
        """Union of all experimental records' declared identities is used."""
        recs = [
            _base(tool_sequence=[]),
            _exp(
                task="t1",
                tool_under_test=["mcp__tilth__"],
                tool_sequence=[],
            ),
            _exp(
                task="t2",
                tool_under_test=["mcp__alpha__"],
                tool_sequence=[],
            ),
        ]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert "mcp__tilth__" in prefixes
        assert "mcp__alpha__" in prefixes

    def test_no_experimental_records_returns_empty(self) -> None:
        """Baseline-only run → no prefixes derived."""
        recs = [_base(tool_sequence=["str_replace_editor"])]
        prefixes = derive_tool_under_test_prefixes(recs)
        assert prefixes == set()
