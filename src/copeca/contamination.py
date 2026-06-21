"""Source-provenance contamination defense — pure functions, no I/O.

Provides the shipped contamination check for the copeca task corpus:
a blocklist of known-contaminated source benchmarks matched against a
task's ``source:`` field.

A planned (not shipped) option: probe a live model with the task ID and
exclude if it reproduces the gold solution.  That requires an API key and
model calls — it is NOT part of this module.

Architecture (S.U.P.E.R.): pure functions, data in / result out.
I/O (reading the blocklist file, emitting warnings) lives in callers.
"""

from __future__ import annotations

from pathlib import Path


def check_source_provenance(
    source: str,
    blocked_sources: set[str],
) -> tuple[bool, str]:
    """Check whether a task's source field names a blocked benchmark.

    Matching is case-insensitive substring: if any blocked-source name
    appears anywhere inside the task's ``source:`` string, the task is
    flagged.

    Args:
        source: The task's ``source:`` field value
                (e.g., ``"SWE-bench Verified (MIT)"``).
        blocked_sources: Set of benchmark names to reject
                         (e.g., ``{"SWE-bench Verified", "ClassEval"}``).

    Returns:
        ``(flagged, reason)`` — ``flagged`` is ``True`` if the task should
        be excluded; ``reason`` is a human-readable string explaining the
        match (empty string when ``flagged`` is ``False``).
    """
    source_lower = source.lower()
    for name in blocked_sources:
        if name.lower() in source_lower:
            return True, f"source {source!r} matches blocked benchmark {name!r}"
    return False, ""


def load_blocked_sources(blocklist_path: Path) -> set[str]:
    """Load blocked source-benchmark names from the blocklist file.

    Lines starting with ``#`` and blank lines are ignored.  Lines that are
    all-lowercase with no spaces are treated as legacy task-name patterns
    (used by the older ``check_contamination`` function) and are skipped
    here.

    Args:
        blocklist_path: Absolute or cwd-relative path to
                        ``contamination_blocklist.txt``.

    Returns:
        A set of benchmark name strings to pass to
        ``check_source_provenance``.
    """
    blocked: set[str] = set()
    with open(blocklist_path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Legacy task-name patterns: all-lowercase, no spaces.
            # They belong to check_contamination, not check_source_provenance.
            if " " not in stripped and stripped == stripped.lower():
                continue
            blocked.add(stripped)
    return blocked
