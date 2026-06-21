"""Tool-agnosticism lint for task text — pure functions, no I/O.

A copeca task must name the INFORMATION or OUTCOME it requires, never the METHOD
the agent should use to get it: no tool names, no "search for / grep", and no cue
that rewards one tool's output shape ("one structured answer", "not piecemeal
searches"). This keeps the A/B fair — the retrieval method is the variable under
test, so a task that prescribes it pre-judges the experiment. It is the same
neutrality rule the corpus applies to prompts, made checkable.

Architecture (S.U.P.E.R.): pure functions, text in / violations out. The repo name
(ripgrep, gin, express, fastapi) is the task's SUBJECT and is never flagged; only
tool naming, single-shot-aggregator priming, and explicit method prescription are.
Patterns are curated for precision — domain words like "search" (ripgrep's whole
purpose) are not flagged unless used as a prescribed method ("search the codebase").
"""

from __future__ import annotations

import re

# (compiled pattern, human-readable reason). All case-insensitive.
_FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    # Explicit tool / product names (the experimental tool or any named retriever).
    # Underscore-aware boundary: tool names appear as `tilth_search` / `grok_gin_new`
    # (a plain \b fails before `_`). Excluding letters on both sides avoids matching
    # words that merely contain the substring (e.g. "grokking").
    (re.compile(r"(?<![a-z])tilth(?![a-z])", re.I), "names the tilth tool"),
    (re.compile(r"(?<![a-z])grok(?![a-z])", re.I), "names the grok tool"),
    (re.compile(r"\bctags\b", re.I), "names a specific tool (ctags)"),
    (re.compile(r"\b(language server|lsp)\b", re.I), "names a specific tool (LSP)"),
    # Single-shot-aggregator priming — rewards a tool that returns one bundled answer.
    (
        re.compile(r"structured answer", re.I),
        "primes a single-shot aggregator ('structured answer')",
    ),
    (
        re.compile(r"consolidated view", re.I),
        "primes a single-shot aggregator ('consolidated view')",
    ),
    (re.compile(r"piecemeal", re.I), "disparages multi-step retrieval ('piecemeal')"),
    (re.compile(r"in (?:a )?single call|in one call", re.I), "primes a single-call tool"),
    (
        re.compile(r"(?:several|multiple|partial) (?:searches|calls|answers)", re.I),
        "frames retrieval as a count of searches/calls",
    ),
    # Explicit method prescription (how to retrieve, not what to retrieve).
    (
        re.compile(r"grep for|run a search|do a search|search the codebase", re.I),
        "prescribes a search method",
    ),
    (re.compile(r"use (?:your |the )?[\w-]+ tool", re.I), "prescribes using a specific tool"),
]


def check_tool_agnostic(name: str, prompt: str, description: str = "") -> list[str]:
    """Return tool-coupling violations in a task's text (empty list = clean).

    Scans ``name`` + ``prompt`` + ``description`` (case-insensitive) for forbidden
    tool names, single-shot-aggregator priming, and explicit method prescription.
    Repo names are NOT flagged — they are the task's subject, not a method.

    Args:
        name: The task's ``name`` field.
        prompt: The prompt sent to the agent (the main surface to keep neutral).
        description: The human-readable ``description`` field (optional).

    Returns:
        A list of distinct human-readable violation reasons; empty when clean.
    """
    text = f"{name}\n{prompt}\n{description}"
    violations: list[str] = []
    for pattern, reason in _FORBIDDEN:
        if pattern.search(text) and reason not in violations:
            violations.append(reason)
    return violations
