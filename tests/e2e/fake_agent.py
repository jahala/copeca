#!/usr/bin/env python3
"""Deterministic fake CLI agent for copeca's hermetic e2e test.

This script stands in for a real coding agent (e.g. `claude`). The real
``SubprocessRunner`` spawns it as a child process exactly as it would the
real CLI, and the real ``StreamJsonParser`` consumes its stdout. It does NOT
call any model, touch the network, or read the repo — it just emits a fixed
Claude-Code ``stream-json`` event stream so the full measurement pipeline
(parse -> cost -> grade -> record -> report) runs deterministically and for
free.

Contract (must stay in lock-step with
``src/copeca/runners/parsers/stream_json.py`` and
``tests/fixtures/sample_stream_json.txt``):

* Each line is one JSON event.
* Assistant ``text`` blocks under ``message.content`` accumulate into the
  parser's ``result_text`` (this is what correctness grading reads).
* A ``message.usage`` block contributes a ``Turn`` whose token fields are
  summed across the run; those sums feed ``compute_cost``.
* A ``{"type": "result", ...}`` event carries the vendor's reported
  ``total_cost_usd`` and ``duration_ms``.

The token counts below are the SINGLE source of truth for the test's
hand-computed cost assertion — keep them in sync with EXPECTED_TOKENS in
``test_full_pipeline.py``.
"""

from __future__ import annotations

import json
import os
import sys

# ── Deterministic token budget (one usage block => these exact sums) ──────────
INPUT_TOKENS = 1000
OUTPUT_TOKENS = 500
CACHE_CREATION_TOKENS = 200
CACHE_READ_TOKENS = 300

# Vendor cost set equal to the hand-computed cost so no divergence warning fires.
# computed = (1000*3.0 + 200*3.75 + 300*0.30 + 500*15.0) / 1e6 = 0.01134
VENDOR_COST_USD = 0.01134
DURATION_MS = 1234

# Env var the experimental arm injects via Mode.env; echoed so the test can
# prove provision_arm's env override reached this child process.
ENV_MARKER_NAME = "COPECA_E2E_MARKER"


def _extract_prompt(argv: list[str]) -> str:
    """Return everything after the first ``--`` separator, joined by spaces.

    Mirrors how ``BaseRunner.build_command`` appends ``prompt_separator``
    followed by the positional prompt. If no ``--`` is present, fall back to
    the last argument so the agent is still usable under other invocations.
    """
    if "--" in argv:
        idx = argv.index("--")
        return " ".join(argv[idx + 1 :])
    return argv[-1] if argv else ""


def main() -> int:
    prompt = _extract_prompt(sys.argv[1:])
    marker = os.environ.get(ENV_MARKER_NAME, "absent")

    # The agent's "answer". It deterministically restates the task's required
    # facts (so grading -> correct=True) and echoes the env marker (so the test
    # can confirm the experimental arm's Mode.env reached this process).
    answer = (
        "The Matcher trait is defined in src/matcher.rs. "
        "It declares find_at as its single method. "
        f"env-marker={marker} prompt-len={len(prompt)}"
    )

    events = [
        # 1. init/system noise the parser ignores (no message dict of interest).
        {"type": "system", "message": "init"},
        # 2. Assistant text answer + usage block in one event (matches the
        #    sample fixture's final-answer-with-usage shape). The usage block
        #    is the ONLY one emitted, so the parser's token sums equal these
        #    exact values.
        {
            "type": "assistant",
            "message": {
                "model": "fake-model",
                "content": [{"type": "text", "text": answer}],
                "usage": {
                    "input_tokens": INPUT_TOKENS,
                    "output_tokens": OUTPUT_TOKENS,
                    "cache_creation_input_tokens": CACHE_CREATION_TOKENS,
                    "cache_read_input_tokens": CACHE_READ_TOKENS,
                },
            },
            "session_id": "e2e-session",
            "uuid": "e2e-0001",
        },
        # 3. Terminal result event with vendor cost + duration.
        {
            "type": "result",
            "total_cost_usd": VENDOR_COST_USD,
            "duration_ms": DURATION_MS,
            "session_id": "e2e-session",
            "uuid": "e2e-0002",
        },
    ]

    out = sys.stdout
    for event in events:
        out.write(json.dumps(event))
        out.write("\n")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
