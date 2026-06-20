"""Contamination self-check for comprehension tasks.

Pure functions — no I/O, no LLM calls. Contamination is detected by
structural matching against known-contaminated task patterns and
output substrings.

A task is flagged (returned as contaminated) if:
1. Its name matches a known-contaminated prefix in the blocklist.
2. Its probe text (name + first 10 prompt words) contains any blocklist pattern.
3. Its required_strings contain known-leaked output substrings.

Architecture: domain-adjacent utility. Takes data in, returns bool out.
"""

from __future__ import annotations


def build_probe(task_name: str, prompt: str) -> str:
    """Build a contamination probe from task identity alone.

    Returns the task name + first 10 words of the prompt.
    If the model can reproduce the gold solution from this probe
    alone, the task is likely contaminated.

    Args:
        task_name: The task's unique identifier (e.g., "t001_find_matcher_trait").
        prompt: The full task prompt text.

    Returns:
        A space-joined string of the task name and the first 10 words
        of the prompt.
    """
    words = prompt.split()[:10]
    return f"{task_name} {' '.join(words)}"


def check_contamination(
    task_name: str,
    prompt: str,
    required_strings: list[str],
    blocklist: set[str],
) -> bool:
    """Check if a comprehension task shows signs of contamination.

    Returns True if the task should be EXCLUDED (contaminated).
    Returns False if the task passes the self-check.

    A task is flagged if:
    1. Its name matches a known-contaminated prefix in the blocklist
    2. Its probe text (name + first 10 prompt words) contains any
       blocklist pattern
    3. The required_strings contain known-leaked output substrings

    Args:
        task_name: The task's unique identifier.
        prompt: The full task prompt text.
        required_strings: The ground truth required_strings for the task.
        blocklist: A set of known-contaminated patterns to check against.

    Returns:
        True if the task is contaminated (should be excluded),
        False if it passes the self-check.
    """
    if not blocklist:
        return False

    # Check 1: task name matches a known-contaminated prefix
    for pattern in blocklist:
        if task_name.lower().startswith(pattern.lower()):
            return True

    # Check 2: probe text contains any blocklist pattern
    probe = build_probe(task_name, prompt)
    probe_lower = probe.lower()
    for pattern in blocklist:
        if pattern.lower() in probe_lower:
            return True

    # Check 3: required_strings contain known-leaked output substrings
    for required in required_strings:
        required_lower = required.lower()
        for pattern in blocklist:
            if pattern.lower() in required_lower:
                return True

    return False
