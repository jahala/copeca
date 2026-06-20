# copeca Orchestration Audit — Scope: Adversarial Flags, Budget Threading, Token Snowball, Concurrency/TOCTOU, Baseline Cleanliness

**Audited:** 2026-06-20  
**Branch:** integration/bench-146-151  
**Auditor scope:** orchestration/run.py, orchestration/state.py, repos/manager.py, config/models.py, runners/subprocess.py, docs/metrics.md, docs/known-limitations.md, docs/architecture.md, docs/methodology.md, README.md

---

## 1. Claims Ledger

| # | Claim | Source | Verdict |
|---|-------|--------|---------|
| C1 | "adversarial flags: token snowball, talkative failure, tool storm, budget exhaustion, timeout" — 5 flags, implied all active | README.md:66, docs/metrics.md:103-118 | **FALSE** — 3 of 5 flags are structurally dead (always None) |
| C2 | "budget_usd: 1.00 — enforced per run" | README.md quick-start example; docs/metrics.md:114 "budget_exhausted — cost >= budget" | **FALSE** — budget_usd field exists but is never wired to _compute_adversarial_flags |
| C3 | "talkative_failure — output_tokens > threshold AND correct == false" | docs/metrics.md:112; docs/architecture.md:205 | **FALSE** — hardcoded None with comment "requires correctness context across reps" |
| C4 | "tool_storm — num_tool_calls > threshold" | docs/metrics.md:113; docs/architecture.md:206 | **FALSE** — hardcoded None with comment "requires threshold config from scenario" |
| C5 | "All thresholds are configurable in the scenario YAML" | docs/metrics.md:117 | **FALSE** — no adversarial_thresholds field in Scenario model; _check_token_snowball hardcodes 3x |
| C6 | "token_snowball — max per-turn tokens > num_turns × avg(first 3 turns) × factor" | docs/metrics.md:111; docs/architecture.md:204 | **WRONG** — code uses `avg_first * 3` only, no num_turns term, no configurable factor |
| C7 | "the baseline is provably clean — it never inherits the host's ambient hooks" | README.md:109; docs/methodology.md:79; docs/architecture.md:21 | **FALSE** — subprocess inherits full os.environ minus only CLAUDECODE |
| C8 | "Copeca provisions each arm with its own config directory and environment" | README.md:108 | **PARTIALLY FALSE** — provision_arm is never called from run_single or _run_one_work_item |
| C9 | "matrix runner is sequential — max_workers is acknowledged but deferred" | docs/known-limitations.md:48-53 | **STALE** — run_matrix uses ThreadPoolExecutor; concurrency is live and creates TOCTOU |
| C10 | "workers are repo-affine (assigned to one repo for lifetime)" | docs/architecture.md:232 | **FALSE** — workers receive items from a shared as_completed() pool; any thread handles any repo |
| C11 | "Two workers never share a worktree" | docs/architecture.md:244 | **CONDITIONALLY FALSE** — worktree path is keyed only by repo_key; two concurrent runs on same repo share a path |

---

## 2. Findings by Severity

---

### FINDING 1 — CRITICAL: Baseline Not Provably Clean — Ambient Env Leaks

**Severity:** CRITICAL  
**Claim:** README.md:109 — "the baseline is provably clean — it never inherits the host's ambient hooks"  
**Evidence file:line:** `src/copeca/runners/subprocess.py:33`

```python
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
```

The subprocess runner builds the child environment by copying the **full** `os.environ`, removing only `CLAUDECODE`. Every ambient variable on the host — agent hook env vars, proxy URLs, API keys, or any tool-specific config — passes through to the "clean" baseline subprocess unchanged.

**Compounding issue — provision_arm never called:** `orchestration/state.py:provision_arm` is designed to build an isolated `ArmHarness` with per-arm env overrides and config directories. It is imported nowhere in `orchestration/run.py` (verified: `provision_arm` absent from run.py source). The `ArmHarness.env` overrides are never applied to the subprocess call. Even for experimental modes, the mode-declared env overrides never reach the child process.

**Repro (pasted output):**
```
=== Env construction analysis ===
Line 33: env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

This inherits the FULL ambient os.environ, only removing CLAUDECODE.
Any ambient env var reaches the child process:
  ANTHROPIC_API_KEY present in child: True
  CLAUDE_CODE_CUSTOM_HOOK present in child: True
  MCP_SERVER_URL present in child: True
  CLAUDECODE removed: True

Result: ALL ambient env vars except CLAUDECODE are inherited.

=== run_single mentions of provision_arm ===
  provision_arm is NOT called from run_single

provision_arm is NOT referenced anywhere in orchestration/run.py

SubprocessRunner.run does NOT reference ArmHarness/harness env
-> The mode-specific env overrides in ArmHarness are never applied to the subprocess
```

**Why CRITICAL:** The headline claim of "provably clean baseline" is the core trust primitive that makes copeca's A/B delta meaningful. If the host has any ambient agent configuration (common on developer machines running benchmark tooling), baseline and experimental arms both inherit it. The delta between baseline and experimental could reflect ambient contamination, not the tool under test. Any result published with this code is unverifiable.

**Fix:** Construct a minimal allowlist env in `SubprocessRunner.run` (e.g. `PATH`, `HOME`, `TMPDIR`, `LANG`, `ANTHROPIC_API_KEY`) rather than inheriting all of `os.environ`. Wire `provision_arm` into `run_single` and merge `ArmHarness.env` into the child env after the scrub.  
**Effort:** Medium (env scrub is ~5 lines; provision_arm wiring requires threading Mode through run_single's signature).

---

### FINDING 2 — HIGH: budget_exhausted Always None — budget_usd Never Enforced

**Severity:** HIGH  
**Claim:** docs/metrics.md:114 — "`budget_exhausted` — The agent hit the cost budget before producing a result | cost >= budget AND result is missing or empty"; README quick-start shows `budget_usd: 1.00` as active config  
**Evidence file:line:** `src/copeca/orchestration/run.py:147` and `run.py:221-225`

The call site at run.py:144-149:
```python
flags = _compute_adversarial_flags(
    parsed=parsed,
    total_cost_usd=total_cost_usd,
    budget_usd=None,  # budget from scenario, passed later
    timeout_seconds=timeout_seconds,
)
```

The comment "passed later" is aspirational — there is no later. `_run_one_work_item` (run.py:353-387) calls `run_single` with no budget_usd argument. `run_single` has no `budget_usd` parameter in its signature. `scenario.budget_usd` is accessed by neither `_run_one_work_item` nor the CLI's single-task path.

In `_compute_adversarial_flags` (run.py:221-225):
```python
"budget_exhausted": (
    total_cost_usd >= budget_usd
    if budget_usd is not None
    else None
),
```

Since `budget_usd` is always `None`, `budget_exhausted` is always `None`.

**Repro (pasted output):**
```
=== Flags with budget_usd=None (as run_single always calls it) ===
  timeout: False
  budget_exhausted: None  (DEAD — always None)
  error: False
  token_snowball: True
  talkative_failure: None  (DEAD — always None)
  tool_storm: None  (DEAD — always None)

=== run_single parameters ===
  task: default=<class 'inspect._empty'>
  mode_name: default=<class 'inspect._empty'>
  model: default=<class 'inspect._empty'>
  ...
  (no budget_usd parameter)
```

`Scenario.budget_usd` (config/models.py:184) is a real Pydantic field with `default=1.0`, but it is only touched by `validate_scenario` (orchestration/validation.py:163-166) for a pre-flight check that `budget_usd > 0`. It is never read during a run.

**Fix:** Thread `scenario.budget_usd` through `_run_one_work_item` → `run_single` parameter → `_compute_adversarial_flags`. Consider also enforcing it mid-run (kill the subprocess if cost exceeds budget) rather than just flagging post-hoc.  
**Effort:** Low-Medium (signature threading + one conditional).

---

### FINDING 3 — HIGH: talkative_failure and tool_storm Always None

**Severity:** HIGH  
**Claim:** docs/metrics.md:112-113; docs/architecture.md:205-206 — both flags described as computed from parsed RunResult data  
**Evidence file:line:** `src/copeca/orchestration/run.py:228-229`

```python
"talkative_failure": None,  # requires correctness context across reps
"tool_storm": None,         # requires threshold config from scenario
```

Both are unconditional `None` assignments. The comment for `talkative_failure` contradicts the docs: the docs say it is computed from `output_tokens > threshold AND correct == false` — correctness *is* available at this point (it is computed on run.py:110-114 before flags are computed on line 144). The comment that it "requires correctness context across reps" implies a cross-run aggregation that is neither documented nor in the code path. `tool_storm` is similarly straightforward from `parsed.num_tool_calls` (available on run.py:168) and a threshold — but `adversarial_thresholds` does not exist as a field in `Scenario` (confirmed by search: zero matches in src/copeca).

**Repro (pasted output):**
```
  talkative_failure: None  (DEAD — always None)
  tool_storm: None  (DEAD — always None)
```

Both flags appear in the `_ADVERSARIAL_FLAG_NAMES` list in `analysis/report.py:16-22`, so they are surfaced in reports as permanently null entries, creating the illusion of untripped flags rather than unimplemented features.

**Fix:** Implement `talkative_failure` from `(total_output_tokens > threshold) and not correct` where threshold defaults to e.g. 2000 tokens. Implement `tool_storm` from `num_tool_calls > threshold` where threshold defaults to e.g. 30. Add `adversarial_thresholds` optional field to `Scenario` model. Remove misleading code comments.  
**Effort:** Low (the data is present; the logic is trivial).

---

### FINDING 4 — MEDIUM: token_snowball Formula and Configurability Mismatch

**Severity:** MEDIUM  
**Claim:** docs/metrics.md:111 — "`token_snowball` — max per-turn output > **num_turns × avg(first 3 turns) × factor**"; docs/metrics.md:117 — "All thresholds are configurable in the scenario YAML"; docs/architecture.md:204 — same formula  
**Evidence file:line:** `src/copeca/orchestration/run.py:242`

```python
if turn.output_tokens > avg_first * 3:  # 3x growth is suspicious
```

**Two mismatches:**

1. **Formula:** The documented formula includes `num_turns` as a scaling term, making the threshold grow with conversation length. The implementation uses only `avg_first * 3` — a flat threshold that fires much more easily in long conversations (the repro shows a 350-token turn in a 10-turn conversation fires by code but would not fire by the documented formula at factor=1).

2. **Configurability:** `adversarial_thresholds` is mentioned in docs/ideas/agent-bench-plan.md:522-525 as a planned scenario field with `token_snowball_factor`, `talkative_failure_tokens`, and `tool_storm_count`. The `Scenario` model (config/models.py) has no such field, and `_check_token_snowball` accepts no configuration parameter. The "3" multiplier is hardcoded.

**Repro (pasted output):**
```
10 turns, avg_first3=100, turn10=350:
  Code fires: True
  Doc formula with factor=1: 350 > 10*100*1 = False (DOES NOT FIRE)
  Code formula: 350 > 100*3 = True (FIRES)

Searching for any config/parameter controlling the 3x threshold...
  NOT FOUND — the 3x multiplier is hardcoded, not configurable from scenario YAML
```

**Fix:** Either (a) align the code to the documented formula by adding the `num_turns` term and a configurable factor, or (b) update the docs to match the simpler flat threshold. Add `adversarial_thresholds` to `Scenario` and thread it through.  
**Effort:** Low.

---

### FINDING 5 — HIGH: Concurrency TOCTOU — Shared Worktree Paths, No Lock

**Severity:** HIGH  
**Claim:** docs/architecture.md:244 — "Two workers never share a worktree"; docs/architecture.md:232 — "workers are repo-affine"  
**Evidence file:line:** `src/copeca/repos/manager.py:87`; `src/copeca/orchestration/run.py:319`

**Worktree path collision:** `create_worktree` constructs the worktree path as:
```python
worktree_path = self._worktree_pool / f"{repo_key}-worktree"
```
The path is keyed only by `repo_key` (the repository name). Any two concurrent work items targeting the same repo (e.g. `task_A mode=baseline rep=0` and `task_A mode=experimental rep=0`, or `task_A rep=0` and `task_A rep=1`) produce the exact same path: `_worktrees/fastapi-worktree`.

`run_matrix` dispatches all work items to a `ThreadPoolExecutor` (run.py:319) whose workers call `create_worktree` on a **shared `repo_mgr` instance** (run.py:321-323). `GitWorktreeManager` has no lock anywhere (confirmed: zero uses of `lock`, `Lock`, `threading` in manager.py source).

**Race condition sequence:**
```
Thread 1: create_worktree('fastapi') → worktree_path.exists() → False → _add_worktree(...)
Thread 2: create_worktree('fastapi') → worktree_path.exists() → False → _add_worktree(...)
          [if Thread 1 hasn't completed yet]
→ git worktree add on an already-registered path → git error or silent corruption
```

Even if thread 2 sees `worktree_path.exists() == True`, it calls `_prune_worktree` which calls `_prune_bare` — pruning bare-clone worktree metadata while Thread 1's active worktree depends on it.

**"Repo-affine" claim is false:** `run_matrix` submits all work items to a flat `executor.submit` pool (run.py:320-324). The `future_to_item` mapping has no repo-to-worker binding. Any worker thread can receive any work item for any repo. The architecture.md §5 description of repo-affine workers is unimplemented design prose, not code.

**Known-limitations.md is stale:** known-limitations.md:49-53 says "The `max_workers` field in scenario YAML is acknowledged but deferred" and "Parallel workers would reduce wall-clock time... but are not yet wired." In fact, `ThreadPoolExecutor` is wired and active. The stale limitation entry means users who read it believe concurrency is off — they will set `max_workers > 1` expecting safe parallel runs, and encounter the unprotected collision.

**Minimal repro argument (no real repos required):**
```python
from concurrent.futures import ThreadPoolExecutor
# Both threads call repo_mgr.create_worktree('fastapi', commit='abc123')
# Both see: self._worktree_pool / 'fastapi-worktree'
# No lock; git worktree add will fail or corrupt the second caller
```

**Fix:** Key worktree paths by `f"{repo_key}-{mode_name}-{task_name}-{rep}"` or by a UUID, so concurrent runs on the same repo each get a unique path. Add a per-repo lock (or per-bare-path lock) to guard `_prune_worktree` + `_add_worktree` as a unit. Update known-limitations.md to reflect that concurrency is live.  
**Effort:** Medium.

---

## 3. Genuinely Good

1. **Cost computation is clean.** `runners/cost.py` computes cost from token counts × pricing table. Vendor self-reported cost is stored separately as `vendor_cost_usd` with a divergence warning at >5%. This is exactly the right separation and is correctly implemented.

2. **Pydantic model validation.** Task, Scenario, Mode, and Repo models are well-specified with appropriate field constraints. Two-layer validation (jsonschema structural + Pydantic semantic) for tasks is solid. The `at_least_one_path_or_tool_change` validator on Mode prevents silent no-op modes.

3. **Worktree lifecycle.** The `create_worktree` + `reset` pattern (bare clone → ephemeral worktree → `git reset --hard HEAD && git clean -fd`) is correct for state isolation per run. The `-fd` vs `-fdx` choice (preserving ignored dirs like `node_modules/`) is a thoughtful call-out in the docstring.

4. **`timeout` flag is live and correct.** `_compute_adversarial_flags` correctly computes `duration_ms >= timeout_seconds * 1000` with proper None-guarding. This one flag works as documented.

5. **`error` flag is live.** `parsed.error is not None` is a concrete boolean — it genuinely fires on parse errors.

6. **`.copeca` artifact integrity chain.** The SHA-256 hash chain design (SHA per file, content_hash over all hashes, stored in manifest.json) is architecturally sound for the stated goal of proving nothing was cherry-picked.

7. **Process-group isolation.** `preexec_fn=os.setsid` + `os.killpg` on timeout correctly kills the entire subprocess tree, preventing zombie child processes from surviving a timeout.

8. **Domain/adapter separation.** The ports-and-adapters structure (pure domain in `config/`, `tasks/`, `analysis/`; I/O at the boundary) is clean and correctly enforced by the import-direction rule. `config/models.py` has zero runtime I/O.

---

## 4. Tend .html Cross-Reference

| Finding | Code issue | Matching tend feature |
|---------|-----------|----------------------|
| F1 (Baseline not clean) | `subprocess.py:33` inherits ambient env; `provision_arm` never called | `docs/tend/features/copeca-mode-mechanism.tend.html` — describes per-arm env isolation as "provably clean"; slot `what` line 2528 |
| F2 (budget_exhausted dead) | `run.py:147` `budget_usd=None` always | `docs/tend/features/copeca-scenario-matrix.tend.html` — step i001 description includes `budget_usd` as validated field; feature implies enforcement |
| F3 (talkative_failure/tool_storm dead) | `run.py:228-229` unconditional None | `docs/tend/features/copeca-single-run.tend.html` — single-run feature covers adversarial flag computation |
| F4 (token_snowball mismatch) | `run.py:242` hardcoded `avg_first * 3`; no `adversarial_thresholds` field | `docs/tend/features/copeca-scenario-matrix.tend.html` — step i001 mentions `adversarial_thresholds` as optional scenario field (unimplemented) |
| F5 (TOCTOU/concurrency) | `manager.py:87` single path per repo_key; no lock; `run.py:319` ThreadPoolExecutor live | `docs/tend/features/copeca-scenario-matrix.tend.html` — worker pool described; `known-limitations.md:48-53` describes concurrency as deferred (stale) |

---

## Appendix: Full Repro Outputs

### Repro 1 — Dead flags (budget_usd=None always)

```
=== Flags with budget_usd=None (as run_single always calls it) ===
  timeout: False
  budget_exhausted: None  (DEAD — always None)
  error: False
  token_snowball: True
  talkative_failure: None  (DEAD — always None)
  tool_storm: None  (DEAD — always None)
```

### Repro 2 — run_single has no budget_usd parameter; _run_one_work_item does not pass scenario.budget_usd

`run_single` parameters: task, mode_name, model, runner, repo_mgr, repo_uri, repo_commit, pricing, artifacts, timeout_seconds — no `budget_usd`.

`_run_one_work_item` calls `run_single(..., timeout_seconds=scenario.timeout_seconds)` — reads only `timeout_seconds` from scenario, never `budget_usd`.

### Repro 3 — token_snowball formula divergence

```
10 turns, avg_first3=100, turn10=350:
  Code fires: True
  Doc formula with factor=1: 350 > 10*100*1 = False (DOES NOT FIRE)
  Code formula: 350 > 100*3 = True (FIRES)

Searching for any config/parameter controlling the 3x threshold...
  NOT FOUND — the 3x multiplier is hardcoded, not configurable from scenario YAML
```

### Repro 4 — Baseline env passthrough

```
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

  ANTHROPIC_API_KEY present in child: True
  CLAUDE_CODE_CUSTOM_HOOK present in child: True
  MCP_SERVER_URL present in child: True
  CLAUDECODE removed: True
```

`provision_arm` not in run_single source. `provision_arm` not in orchestration/run.py at all.

### Repro 5 — Worktree path collision

```
worktree_path = self._worktree_pool / f"{repo_key}-worktree"   # manager.py:87

task_A worktree path: /repos/_worktrees/fastapi-worktree
task_B worktree path: /repos/_worktrees/fastapi-worktree
Paths are identical: True

NO LOCK anywhere in GitWorktreeManager

known-limitations.md says: concurrency deferred, not yet wired
run_matrix: ThreadPoolExecutor IS wired (confirmed)
architecture.md §5: 'workers are repo-affine' — NOT implemented
```
