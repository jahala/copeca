"""Post-hoc symmetric trace gate (ISO-7 + ISO-8).

Architecture: domain. Pure functions — no I/O, no imports from
runners/repos/results/orchestration.

The gate proves an A/B was clean by reading the parsed tool trace, not config:
- BASELINE arm: its tool_sequence must contain NONE of the tool-under-test's
  tools.  A contaminated baseline record is flagged and excluded from the
  delta computation.
- EXPERIMENTAL arm: it must have used the tool at least once (tool_adopted).
  That surface is already handled by _tool_validity_section in report.py; this
  module owns the baseline side.

Tool-under-test detection (ISO-8 upgrade)
──────────────────────────────────────────
ISO-8 adds a ``tool_under_test`` field to each experimental record — the list
of ``mcp__<srv>__`` prefixes DECLARED by the mode's mcp_config (e.g.
``["mcp__tilth__"]``).  When any experimental record carries a non-empty
``tool_under_test`` list, ``derive_tool_under_test_prefixes`` PREFERS the union
of those declared values over usage inference.

This closes the ISO-7 limitation: the gate is now robust even when the
experimental arm never called the tool (tool_adopted=False) — the declared
identity still exposes a contaminated baseline.

Fallback: records that lack the field (or carry an empty list) fall back to the
original usage-inference logic (any ``mcp__`` call in tool_sequence of an
experimental record).
"""

from typing import Any

_MCP_PREFIX = "mcp__"


def derive_tool_under_test_prefixes(records: list[dict[str, Any]]) -> set[str]:
    """Return the set of ``mcp__<srv>__`` prefixes for the tool-under-test.

    Strategy (ISO-8):
    1. DECLARED IDENTITY: collect all non-empty ``tool_under_test`` values from
       experimental records (``tool_adopted`` is not None).  If any are found,
       return their union immediately — the declared identity is authoritative.
    2. USAGE INFERENCE (fallback): if no record carries ``tool_under_test``,
       derive prefixes from ``tool_sequence`` entries of experimental records
       exactly as before (ISO-7 logic).

    Only records where ``tool_adopted`` is not None are the experimental arm
    (the baseline arm carries ``tool_adopted=None`` or omits the field).

    Returns an empty set when no experimental arm exists.
    """
    declared: set[str] = set()
    inferred: set[str] = set()

    for r in records:
        if r.get("tool_adopted") is None:
            continue  # baseline arm — skip

        # Declared identity (ISO-8): prefer tool_under_test field when present
        tut = r.get("tool_under_test")
        if tut:  # non-None, non-empty list
            declared.update(tut)
            continue  # don't fall through to inference for this record

        # Usage inference (ISO-7 fallback): read tool_sequence
        for name in r.get("tool_sequence") or []:
            if not name.startswith(_MCP_PREFIX):
                continue
            # name = "mcp__<srv>__<tool_fn>" → prefix = "mcp__<srv>__"
            parts = name.split("__")
            if len(parts) >= 3:  # ["mcp", "<srv>", "<fn>", ...]
                prefix = f"mcp__{parts[1]}__"
                inferred.add(prefix)

    # Declared identity takes precedence; fall back to inferred when no
    # experimental record carries a non-empty tool_under_test.
    return declared if declared else inferred


def flag_contaminated_baseline(record: dict[str, Any], prefixes: set[str]) -> bool:
    """Return True if *record* is a baseline record contaminated by a tool-under-test.

    A record is contaminated when ALL of:
    1. It is a baseline record (``tool_adopted`` is None or absent).
    2. ``prefixes`` is non-empty (there is a known tool-under-test set).
    3. At least one name in ``tool_sequence`` starts with a prefix in *prefixes*.

    Experimental arm records (``tool_adopted`` is True/False) are never flagged
    by this function — they are handled by ``_tool_validity_section``.
    """
    if prefixes == set():
        return False
    if record.get("tool_adopted") is not None:
        return False  # experimental arm — not our concern here
    seq: list[str] = record.get("tool_sequence") or []
    return any(name.startswith(tuple(prefixes)) for name in seq)


def filter_clean_baseline(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records into (clean, contaminated).

    Derives the tool-under-test prefix set from *records* then classifies
    every baseline record.  Non-baseline (experimental) records always go into
    ``clean``.  Contaminated baseline records go into ``contaminated`` and are
    excluded from the clean set.

    Returns:
        (clean_records, contaminated_records) — both are new lists; the input
        is not mutated.
    """
    prefixes = derive_tool_under_test_prefixes(records)
    if not prefixes:
        return list(records), []

    clean: list[dict[str, Any]] = []
    contaminated: list[dict[str, Any]] = []
    for r in records:
        if flag_contaminated_baseline(r, prefixes):
            contaminated.append(r)
        else:
            clean.append(r)
    return clean, contaminated
