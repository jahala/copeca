# Copeca Integrity Audit Report
**Scope:** `src/copeca/results/{verification,artifact,writer}.py`, `cli.py` verify command, docs, tend features  
**Date:** 2026-06-20  
**Auditor:** Claude (Sonnet 4.6)

---

## 1. Claims Ledger

| Claim | Source file:line | Impl file:line | Status | Evidence |
|---|---|---|---|---|
| "SHA-256 hash chains" | README.md:67 | artifact.py:72-75, verification.py:76-78 | **OVERCLAIMED** | There is exactly one hash per artifact (content_hash = SHA-256 of sorted per-file hashes). That hash lives *inside the same zip it covers*. This is a self-hash, not a chain. A "chain" in cryptography means each artifact commits to the previous one; nothing here does that. See Finding F1. |
| "proves nothing was cherry-picked" | README.md:67 | verification.py:155-163 | **OVERCLAIMED** | verify_batch only computes `max(expected - actual_count, 0)`. It does not track which (task, mode, model, rep) are present vs absent. A cherry-picker who submits only their best reps produces artifacts that verify clean; the count discrepancy is reported only as a raw integer. See Finding F2. |
| `copeca verify --batch --scenario` | docs/tend/features/copeca-artifact-integrity.tend.html:2535,2567; docs/tend/features/no-verifiable-results.tend.html:2553; docs/tend/overview.html:3070 | cli.py:275-291 | **STALE / PHANTOM** | The `verify` CLI command accepts only a single `ARTIFACT` positional argument. There is no `--batch` or `--scenario` flag. The smoke command in the tend doc (`copeca verify --batch results/ --scenario scenarios/smoke_test.yaml`) is not wired up. See Finding F3. |
| "SHA-256 hash chains" (architecture doc) | docs/architecture.md:20 | artifact.py | **OVERCLAIMED** | Same as above — self-hash only, not a chain linking multiple artifacts. |
| "The hash chain covers every artifact file" | docs/engineering.md:157 | verification.py:60-69 | **HOLDS (with precision)** | Every non-manifest file's SHA-256 is computed and compared. The per-file coverage is complete. The weakness is that the attacker can recompute all hashes after tampering — it is not a chain, but it does cover all files. |
| Zip-slip / path traversal safe | (not claimed explicitly) | verification.py:66; artifact.py:91-94 | **HOLDS** | Neither verify_artifact nor build_artifact calls extractall/extract. Only ZipFile.read() is used, which returns bytes in memory. No disk write occurs. Member names with traversal sequences are silently read but not written. |
| Zip-bomb size limit | (not claimed) | verification.py (entire) | **UNVERIFIABLE / ABSENT** | No decompressed-size check anywhere. A malicious zip can trigger unbounded memory allocation via zf.read(). |
| Content hash is independently recomputable | copeca-artifact-integrity.tend.html:2563 | verification.py:74-78 | **HOLDS** | The algorithm (sorted file-hash concatenation, SHA-256) is simple and documented. Any third party can replicate it. |
| `.venv/` gitignored | .gitignore:4 | .gitignore | **PARTIALLY BROKEN** | `.gitignore` contains `.venv/` (directory pattern). The installed `.venv` is a symlink. Git's directory-pattern matching does NOT match symlinks. `git status` shows `.venv` as `??` (untracked). The venv contents can be accidentally committed. |

---

## 2. Findings (Ranked by Severity)

---

### F1 — "SHA-256 Hash Chain" Is a Self-Hash, Not a Chain
**Severity:** CRITICAL  
**Claim violated:** README.md:67 — "SHA-256 hash chains"; docs/tend/overview.html:3070,3073 — "hash chain proves the artifact wasn't doctored"

**Evidence (file:line):**
- `artifact.py:72-75` — content_hash is SHA-256 of the sorted per-file hashes, all computed from files inside the same zip.
- `artifact.py:88-94` — manifest.json (containing content_hash) is written into the same zip it hashes.
- `verification.py:74-78` — verifier recomputes content_hash from the zip's own members.

**The structural problem:**  
A "hash chain" in any security context means artifact N commits to artifact N-1 (linked list / Merkle tree). What copeca does is a single-level self-hash: the hash of all files is stored inside the file collection itself. An attacker with write access to the zip (which is the threat model) can:
1. Tamper any file.
2. Recompute the per-file SHA-256.
3. Recompute content_hash.
4. Replace manifest.json.
The zip now verifies clean. The "chain" adds zero tamper-evidence against anyone who can write the zip.

**Repro (FORGE — full output):**

```
$ /tmp/copeca_venv/bin/python /tmp/scratch_integrity/forge_repro.py

[1] Built authentic artifact: rg_search_dispatch__baseline__claude-sonnet-4-6.copeca.zip
[2] Original verify: valid=True, msg='Artifact valid: content_hash matches all files'
[3] Original result.json: correct=False, cost=0.031
[4] Tampered result.json: correct=True, cost=0.001
[5] Forged artifact written: FORGED__rg_search_dispatch__baseline__claude-sonnet-4-6.copeca.zip
[6] FORGED verify: valid=True, msg='Artifact valid: content_hash matches all files'

*** FORGE SUCCEEDED: copeca verify PASSES on tampered data ***
    Original: correct=False, cost=0.031
    Forged:   correct=True,  cost=0.001
    verify says: Artifact valid: content_hash matches all files
```

A run that was `correct=False` (cost $0.031) is forged to `correct=True` (cost $0.001) and passes `copeca verify`.

**What "hash chain" would actually mean:**  
A genuine chain requires an external anchor — a timestamp authority, a public ledger, or a linked sequence where artifact N includes the hash of artifact N-1. Without an external anchor, "hash-chained" is not a meaningful integrity guarantee against the artifact owner.

**Minimal fix (effort M):**  
Change the claim: rename "hash chain" to "self-contained integrity manifest." Optionally add: a public git-tag or log of content_hashes (one per run batch), so the sequence is externally anchored. Without that, no renaming of the implementation changes the fundamental weakness.

---

### F2 — Cherry-Pick Detection Counts Artifacts, Not Runs
**Severity:** CRITICAL  
**Claim violated:** README.md:67 — "proves nothing was cherry-picked"; docs/tend/overview.html:3070 — "proves nothing was cherry-picked"; copeca-artifact-integrity.tend.html:2530

**Evidence (file:line):**  
`verification.py:155-163`:
```python
missing = 0
if scenario is not None:
    expected = (
        len(scenario.tasks) * len(scenario.modes)
        * len(scenario.models) * scenario.repetitions
    )
    missing = max(expected - actual_count, 0)
```

`artifact.py:48`:
```python
zip_name = f"{safe_task}__{safe_mode}__{safe_model}.copeca.zip"
```

**Two compounding weaknesses:**

**Weakness A — Count only, no identity:**  
`verify_batch` computes `expected_count - actual_count`. It does not check which (task, mode, model, repetition) combinations are present. A user who re-runs a task 10 times and submits only the 3 favorable reps produces an artifact set that — when scenario is not provided — reports `missing=0`. When scenario IS provided, it reports a raw missing count but names no specific absent run.

**Weakness B — Filename collision erases repetitions:**  
The artifact filename is `{task}__{mode}__{model}.copeca.zip`. There is no repetition index. All repetitions of the same (task, mode, model) write to the same filename; the last written silently wins. `verify_batch` counts files, not runs. A scenario with `repetitions=3` and 2 tasks × 2 modes should produce 12 artifacts; the scheme can only ever produce 4 unique filenames. The `missing` count will always report `8` (12−4), even if all 4 files are authentic, because the repetitions are physically impossible to distinguish.

**Repro (CHERRY-PICK — full output):**

```
$ /tmp/copeca_venv/bin/python /tmp/scratch_integrity/cherry_pick_repro.py

Scenario expects 12 total runs
Cheater ships 6 artifacts (cherry-picked from 12 runs)

Artifacts written to /tmp/scratch_integrity/cherry_work/artifacts
Files in output dir: 4
  task_A__baseline__claude-sonnet-4-6.copeca.zip
  task_A__my_tool__claude-sonnet-4-6.copeca.zip
  task_B__baseline__claude-sonnet-4-6.copeca.zip
  task_B__my_tool__claude-sonnet-4-6.copeca.zip

--- verify_batch WITHOUT scenario ---
authentic=4, tampered=[], missing=0
=> missing=0 means NO cherry-pick detection at all without scenario

--- verify_batch WITH scenario ---
authentic=4, tampered=[], missing=8
=> 'missing' only tells us COUNT (12 expected - 4 actual = 8)
=> It does NOT say WHICH (task, mode, rep) combinations are absent
=> It does NOT identify which specific runs were cherry-picked vs. omitted
```

Note: the cheater submitted 6 selected runs, but due to filename collision only 4 files were written. Both the cheater's cherry-pick AND the filename collision produce the same `missing=8` outcome — the verifier cannot distinguish between "12 reps run, 4 favorable shipped" and "4 reps run total."

**Minimal fix (effort L):**  
1. Add a repetition index to the artifact filename: `{task}__{mode}__{model}__rep{N}.copeca.zip`.  
2. Change `verify_batch` to track which (task, mode, model, rep) tuples are expected vs. present and report by identity, not just count.  
3. Update the README claim: remove "proves nothing was cherry-picked"; replace with an accurate description of what the count check can and cannot establish.

---

### F3 — `copeca verify --batch --scenario` Does Not Exist
**Severity:** HIGH  
**Claim violated:** copeca-artifact-integrity.tend.html:2567 (smoke cmd); no-verifiable-results.tend.html:2553; docs/tend/overview.html:3070

**Evidence (file:line):**  
`cli.py:275-291` — the `verify` command accepts exactly one positional argument (`artifact: Path`). No `--batch` or `--scenario` options exist.

```
$ /tmp/copeca_venv/bin/copeca verify --help
 Usage: copeca verify [OPTIONS] ARTIFACT
 Arguments:
   * artifact  PATH  Path to a .copeca artifact to verify [required]
 Options:
   --help  Show this message and exit.
```

The tend smoke command (`copeca verify --batch results/ --scenario scenarios/smoke_test.yaml`) and every doc reference to `copeca verify --batch --scenario` describe a CLI surface that is not implemented. Calling the documented command will exit with a typer error.

The underlying Python function (`verify_batch` in `verification.py:105-165`) does exist and accepts a `scenario` parameter, but is not wired to any CLI command.

**Minimal fix (effort S):**  
Either: (a) add `--batch` and `--scenario` flags to the `verify` CLI command and wire them to `verify_batch`, or (b) remove all doc/tend references to the `--batch --scenario` invocation until it is implemented.

---

### F4 — No Decompressed-Size Limit (Zip-Bomb)
**Severity:** MEDIUM  
**Claim violated:** No explicit claim, but the absence of a limit is a security gap when processing untrusted `.copeca` zips.

**Evidence (file:line):**  
`verification.py:66` — `data = zf.read(name)` — reads the entire decompressed content of each member into memory with no size check.  
No `max_size` parameter, no header pre-check, no streaming read.

**Argument:**  
Python's `zipfile.ZipFile.read()` decompresses the full member before returning. A malicious zip with a member that compresses to a few KB but decompresses to several GB (the classic zip-bomb ratio) will cause OOM or a very long stall before Python raises `MemoryError`. Since `verify_artifact` is called on user-supplied paths (`cli.py:282`), any untrusted `.copeca` zip can trigger this.

**No standalone repro required** (the argument is tight: `zf.read(name)` with no limit is universally acknowledged as the zip-bomb attack surface).

**Minimal fix (effort S):**  
Before `zf.read(name)`, check `zf.getinfo(name).file_size` against a reasonable limit (e.g., 50 MB per member, 200 MB total). Raise a descriptive error if exceeded.

---

### F5 — `.venv` Symlink Escapes `.gitignore` Pattern
**Severity:** LOW  
**Claim violated:** No explicit claim, but bears on packaging integrity (accidental venv commit).

**Evidence:**  
`.gitignore:4` contains `.venv/` (directory pattern). The installed `.venv` entry is a symlink:
```
lrwxr-xr-x  .venv -> /tmp/copeca_venv
```
Git's directory-glob pattern `.venv/` does NOT match symlinks. `git status` shows:
```
?? .venv
```
(untracked, not ignored). A `git add .` or `git add -A` would stage the symlink target's contents. On macOS/Linux, git follows the symlink and would try to add the entire venv tree, potentially including credentials cached in the venv.

**Minimal fix (effort S):**  
Add `.venv` (without trailing slash) to `.gitignore` alongside `.venv/` — or replace `.venv/` with `.venv` which matches both symlinks and directories.

---

## 3. Genuinely Good Confirmations

**Per-file hash coverage is complete.** `artifact.py:64-69` hashes every file before adding it to the zip. `verification.py:60-69` recomputes hashes for every non-manifest member. There are no skipped or optional files. The per-file coverage within a single artifact is correct and well-tested.

**Tamper detection works for naive tampering.** Modifying bytes in result.json without updating the manifest IS detected (as the existing test suite confirms). The weakness is only that a knowledgeable attacker who also updates the manifest passes verification — not a naive bit-flip.

**Zip-slip is not currently exploitable.** `verification.py:66` and `artifact.py:92-93` use only `ZipFile.read()` and `ZipFile.writestr()`. No `extractall()` or `extract()` call exists anywhere in the codebase. A crafted zip with path-traversal member names will have its bytes read into memory but nothing written to disk. This is confirmed by repro (see REPRO script — `ZIPSLIP_PWN` marker was NOT created).

**Algorithm transparency.** The `content_hash` formula (`SHA-256(concat(sorted per-file hashes))`) is documented in the tend spec and is trivially reproducible by any third party. The verification logic in `verification.py:74-78` is a faithful implementation of the documented algorithm.

**Test suite covers the intended contract.** `tests/results/test_artifact.py`, `tests/results/test_verify_single.py`, `tests/cli/test_artifact_smoke.py` and `tests/results/test_verify_batch.py` comprehensively test: authentic verification, naive tampering detection, corrupted manifest detection, missing/phantom file detection, and batch count discrepancies. All tests are green.

**Cost is computed from tokens, not trusted from vendor.** The runner architecture explicitly separates computed `total_cost_usd` from vendor-reported `vendor_cost_usd`. This is the right design.

---

## 4. Matching Tend Spec Per Code Issue

| Finding | Tend file | Tend field | Status field in tend |
|---|---|---|---|
| F1 (self-hash marketed as chain) | `docs/tend/features/copeca-artifact-integrity.tend.html` | `what`, `how` | `"status": "verified"` — overstated |
| F2 (cherry-pick count-only) | `docs/tend/features/copeca-artifact-integrity.tend.html` | `what`, `impact` | `"status": "verified"` — overstated; the impact says "185/200 artifacts means 15 runs were dropped" which implies identity-level tracking that does not exist |
| F3 (--batch --scenario phantom) | `docs/tend/features/copeca-artifact-integrity.tend.html:2567` | `smoke.cmd` | Smoke command is broken — `"progress": {"implementation": 100}` is incorrect |
| F3 also | `docs/tend/features/no-verifiable-results.tend.html` | narrative | References `copeca verify --batch --scenario` as working; `"progress": {"implementation": 0}` — this file at least is honest about status |
| F4 (zip-bomb) | (no tend feature covers this) | — | Not modeled |
| F5 (.venv symlink) | (no tend feature) | — | Not modeled |

---

## Appendix: Repro Scripts

All repro scripts are at `/tmp/scratch_integrity/`:
- `forge_repro.py` — REPRO 1: build, tamper result.json, recompute manifest, pass verify
- `cherry_pick_repro.py` — REPRO 2: demonstrate count-only detection, filename collision
- `zipslip_repro.py` — REPRO 3: craft traversal zip, show no disk write via verify_artifact
