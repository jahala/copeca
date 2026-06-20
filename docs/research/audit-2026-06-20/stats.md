# copeca Statistics/CI & Cost Model Audit Report

**Scope:** `src/copeca/analysis/stats.py`, `compare.py`, `report.py`, `runners/cost.py`,
`orchestration/run.py` (cost path), `orchestration/validation.py`;
docs: `metrics.md`, `known-limitations.md`, `README.md`,
`docs/tend/features/copeca-cost-model.tend.html`,
`docs/tend/features/copeca-analysis-reporting.tend.html`,
`docs/tend/features/pricing-drift-unchecked.tend.html`

**Test suite baseline:** 41 tests in `tests/analysis/` — all GREEN.

---

## 1. Claims Ledger

| # | Source | Claim | Verdict |
|---|--------|-------|---------|
| C1 | `README.md:63`, `metrics.md:16` | Cost is "computed, never trusted from vendor self-reported numbers" | OVERCLAIMED — tokens ARE self-reported by vendor CLI; only the *USD aggregation step* is avoided |
| C2 | `metrics.md:46-48` | Bootstrap "resamples N (cost, correct) pairs, computes cost_per_correct for the resample" | STALE — actual code bootstraps per-task deltas (floats), computes their mean |
| C3 | `metrics.md:52-54` | "delta CI is computed directly from the paired bootstrap" | HOLDS at task level — per-task delta IS implicitly paired; but internal inconsistency with C2's per-run description |
| C4 | `metrics.md:117` | "All thresholds are configurable in the scenario YAML" | OVERCLAIMED — `token_snowball` threshold hardcoded at 3× (run.py:242); `talkative_failure` and `tool_storm` always `None`; no threshold fields in `Scenario` model |
| C5 | `copeca-cost-model.tend.html:2531` | ">5% divergence triggers a staleness warning" | OVERCLAIMED — divergence is stored in `record["metadata"]` only; never printed or surfaced to the user in any CLI path or report |
| C6 | `pricing-drift-unchecked.tend.html:2553` | Narrative shows "Pricing cross-check: 3 runs diverged >5%" as user-visible output | OVERCLAIMED — no such output exists anywhere in `cli.py`, `run.py`, `report.py`, or `compare.py` |
| C7 | `metrics.md:98-99`, `known-limitations.md:98-101` | "Staleness warnings fire if the pricing table is older than 30 days" | OVERCLAIMED — `check_pricing_staleness()` exists in `validation.py:18` but is **never called** anywhere in `src/copeca/` |
| C8 | `known-limitations.md:48-53` | "Matrix runner is sequential — max_workers is deferred" | STALE — `run_matrix()` uses `ThreadPoolExecutor(max_workers=max_workers)` (run.py:319); parallel execution IS wired |
| C9 | `known-limitations.md:55-62` | "`test_command_passed` always `None` in orchestrator" | STALE — run.py:78-113 implements the full test_command subprocess path |
| C10 | `stats.py:63-82`, `report.py:25-54` | Bootstrap zero-denominator guarded | HOLDS — `cost_per_correct` returns `0.0` on zero correct; `_compute_per_task_deltas` skips tasks where baseline CPC is zero |
| C11 | `cost.py:7-31` | Pure function for cost computation | HOLDS — no I/O, no imports from side-effectful modules, deterministic |

---

## 2. Findings by Severity

---

### F1 · HIGH · Bootstrap CI Description Does Not Match the Code

**Claim:** `metrics.md:46-48`
> "Pool all (cost, correct) pairs from the N runs in a mode. Resample N pairs with replacement, compute cost_per_correct for the resample, and repeat 10,000 times."

**Code path (evidence):**
- `report.py:246`: `per_task_deltas = _compute_per_task_deltas(records, modes)`
- `report.py:248`: `ci_lo, ci_hi, _, _ = bootstrap_ci(per_task_deltas)`
- `stats.py:173-176`: `bootstrap_ci` resamples a list of `float` values and computes their **mean** per resample

**What `_compute_per_task_deltas` actually does** (`report.py:25-54`):
1. Groups records by task.
2. For each task, computes `cpc0 = cost_per_correct(mode0_recs)` and `cpc1 = cost_per_correct(mode1_recs)` from **all repetitions pooled**.
3. Returns `(cpc1 - cpc0) / cpc0 * 100` — a per-task percentage delta.

**What is actually bootstrapped:** the list of per-task delta percentages (N = number of tasks, not number of runs). The statistic per resample is the **mean of the delta percentages** — not `cost_per_correct` of a resampled run set.

**Two distinct differences from the claim:**
1. The unit of resampling is a **task** (not an individual run).
2. The per-resample statistic is the **mean of deltas** (not `total_spend / correct_count`).

**Is this independent or paired?** Paired at the task level — each delta already encodes both modes for a given task. The CI from this procedure is on the *mean per-task delta*, not on the per-mode CPC ratio described in metrics.md steps 1-3.

**Statistical assessment:** The actual procedure (bootstrap of per-task deltas) is arguably more appropriate for N=16 tasks than the per-run ratio bootstrap described. But the documentation describes the wrong procedure, making the CI unverifiable from the docs.

**Repro:**
```python
# /tmp/copeca_venv/bin/python
import sys; sys.path.insert(0, '/tmp/copeca_audit/src')
from copeca.analysis.report import _compute_per_task_deltas
from copeca.analysis.stats import bootstrap_ci

# Build records: 16 tasks, 3 reps, tool has 0 correct
records = []
for t in range(16):
    for rep in range(3):
        records.append({'task': f't{t}', 'mode': 'baseline', 'total_cost_usd': 0.10, 'correct': rep==0})
        records.append({'task': f't{t}', 'mode': 'tool', 'total_cost_usd': 0.10, 'correct': False})

deltas = _compute_per_task_deltas(records, ['baseline', 'tool'])
# deltas = [-100.0, -100.0, ...] — 16 task deltas, NOT per-run (cost,correct) pairs
print(f'N deltas: {len(deltas)}')  # 16 (tasks), not 96 (runs)
ci = bootstrap_ci(deltas, n_resamples=10000)
print(f'CI: {ci}')  # (-100.0, -100.0, -100.0, -100.0) — bootstrapping floats, not ratio
```
Output:
```
N deltas: 16
CI: (-100.0, -100.0, -100.0, -100.0)
```

**Fix:** Rewrite `metrics.md` §Bootstrap section to accurately describe: "For the delta CI, copeca computes the CPC delta for each task (mode1_cpc − mode0_cpc) / mode0_cpc × 100%, then bootstraps the mean of those per-task deltas with 10,000 resamples. The 2.5th and 97.5th percentiles of the bootstrap mean distribution form the 95% CI." Effort: documentation only.

**Affected tend file:** `copeca-analysis-reporting.tend.html` narrative at line 2606 ("CI is bootstrapped from the per-task cost-per-correct differences") — this part is accurate; the inconsistency is in `metrics.md` only.

---

### F2 · HIGH · Divergence Warning Is Silently Buried — Never Shown to User

**Claim:** `copeca-cost-model.tend.html:2531`
> ">5% divergence triggers a staleness warning."

**Claim:** `pricing-drift-unchecked.tend.html:2553` (narrative, fictional interaction)
> "Pricing cross-check: 3 runs diverged >5%. Model: claude-opus-5. Divergence: +7.2%, +6.8%, +8.1%."

**Code path (evidence):**
- `run.py:132-139`: divergence is computed when `vendor_cost_usd` is available.
- `run.py:192-194`: if divergence > 5%, the value and warning string go into `record["metadata"]["vendor_cost_divergence"]` and `record["metadata"]["vendor_cost_divergence_warning"]`.
- `cli.py:238-241` verbose mode: prints `correct`, `cost`, `duration` — **no divergence**.
- `cli.py:192-195` scenario mode: prints counts — **no divergence**.
- `report.py:181-414` (`generate_report`): no section reads `metadata.vendor_cost_divergence`.
- `compare.py:12-116` (`compare_runs`): same.

**Exhaustive search result:**
```bash
grep -rn "vendor_cost_divergence" /tmp/copeca_audit/src/copeca/
# /tmp/copeca_audit/src/copeca/orchestration/run.py:193  (set only)
# /tmp/copeca_audit/src/copeca/orchestration/run.py:194  (set only)
```
No other code reads this field. The warning exists as JSONL metadata but is never displayed.

**Fix:** In `cli.py`, after each `run_single` call (single-task mode) and in the matrix loop, check `record.get("metadata", {}).get("vendor_cost_divergence_warning")` and emit a `typer.echo(..., err=True)`. Alternatively, surface it in `generate_report()`. Additionally, call `check_pricing_staleness()` from `cli.py:run()` before executing the scenario. Effort: ~15 lines across `cli.py` and optionally `report.py`.

**Affected tend files:** `copeca-cost-model.tend.html`, `pricing-drift-unchecked.tend.html`.

---

### F3 · HIGH · Staleness Warning Function Is Dead Code — Never Called

**Claim:** `metrics.md:98-99`
> "Staleness warnings fire if the pricing table is older than 30 days."

**Claim:** `copeca-cost-model.tend.html:2536`
> "The `updated` field on each runner's pricing table is compared against the current date at scenario validation time. If it's older than 30 days, copeca emits a staleness warning."

**Code path (evidence):**
- `validation.py:18-64`: `check_pricing_staleness(pricing)` is implemented and correct.
- Search for all callers:
```bash
grep -rn "check_pricing_staleness" /tmp/copeca_audit/src/copeca/
# Only: validation.py:18 (the definition itself)
```
Zero call sites. The function is never invoked from `cli.py`, `run.py`, or anywhere else. No staleness warning ever fires at runtime.

**Fix:** Call `check_pricing_staleness(pricing)` in `cli.py:run()` before the matrix/single run, and emit warnings with `typer.echo(w, err=True)`. One line to add at `cli.py` after pricing is loaded (~line 127). Effort: trivial.

**Affected tend files:** `copeca-cost-model.tend.html`, `pricing-drift-unchecked.tend.html`.

---

### F4 · MEDIUM · "All Thresholds Configurable" — Two of Three Flags Always Null; One Hardcoded

**Claim:** `metrics.md:117`
> "All thresholds are configurable in the scenario YAML."

**Evidence:**
1. `Scenario` model (`models.py:171-187`) has no threshold fields: `name`, `description`, `tasks`, `modes`, `models`, `repetitions`, `budget_usd`, `timeout_seconds`, `max_workers`, `output_dir` only.
2. `run.py:228`: `"talkative_failure": None,  # requires correctness context across reps` — always null.
3. `run.py:229`: `"tool_storm": None,  # requires threshold config from scenario` — always null despite comment saying "requires threshold config from scenario".
4. `run.py:242`: `if turn.output_tokens > avg_first * 3:  # 3x growth is suspicious` — `token_snowball` threshold hardcoded at 3×, not read from scenario.

**Fix:** Either (a) add threshold fields to `Scenario` (`token_snowball_factor`, `talkative_failure_token_threshold`, `tool_storm_call_threshold`) and wire them through `_compute_adversarial_flags`, or (b) correct `metrics.md` to say "timeout is configurable via `timeout_seconds`; other flag thresholds are hardcoded defaults; `talkative_failure` and `tool_storm` are not yet computed." Effort: medium (Scenario model + run.py) or documentation-only.

**Affected tend files:** None directly, but `metrics.md:103-118` adversarial flag table.

---

### F5 · MEDIUM · Self-Reported Token Counts Undisclosed — "Never Trusted" Claim Overstated

**Claim:** `README.md:63`
> `Cost — computed, never trusted from vendor self-reported numbers`

**Claim:** `metrics.md:15-16`
> "`total_cost_usd` is ... computed from token counts and the pricing table — never from vendor self-reported cost."

**Reality:** The distinction being made is that the **USD total** from the vendor (`total_cost_usd` in the vendor CLI output) is not trusted. Instead, copeca computes USD from `tokens × pricing_table`. This is accurate.

**BUT:** The token counts themselves — `parsed.total_input_tokens`, `parsed.total_output_tokens`, `parsed.total_cache_creation_tokens`, `parsed.total_cache_read_tokens` — all come from the vendor CLI's own output (`run.py:122-128`). These ARE vendor self-reports. If the vendor CLI misreports token counts, copeca's computed cost is wrong.

**Disclosure search:**
```bash
grep -n "self.report" /tmp/copeca_audit/docs/known-limitations.md  # (none)
grep -n "token" /tmp/copeca_audit/docs/known-limitations.md  # only threshold mentions
```
No known-limitation entry discloses that token counts are still vendor self-reports.

**Assessment:** The "never trusted" framing is misleading — trust has been moved from the vendor's USD number to the vendor's token counts. The actual independence from vendor numbers is partial, not total.

**Fix:** Add to `known-limitations.md`: "Token counts are vendor self-reported — copeca parses `input_tokens`, `output_tokens`, `cache_creation_tokens`, and `cache_read_tokens` from the runner CLI's own output. The cost formula `Σ tokens × pricing_rate` avoids the vendor's pre-computed USD total, but is still dependent on the vendor reporting accurate token counts." Effort: documentation only.

**Affected tend files:** `copeca-cost-model.tend.html` narrative should add this caveat.

---

### F6 · LOW · `known-limitations.md` Has Two Stale "Deferred" Entries That Are Now Implemented

**Finding A — Matrix runner is sequential (known-limitations.md:48-53):**
Claims "`run_matrix()` iterates tasks × modes × reps sequentially in nested loops." Reality: `run.py:277-350` uses `ThreadPoolExecutor(max_workers=max_workers)` — parallel execution is fully wired.

**Finding B — test_command_passed always None (known-limitations.md:55-62):**
Claims "`check_correctness` passes `test_command_passed=None`" and "edit tasks are currently graded only by `required_strings`." Reality: `run.py:78-113` is a full `subprocess.run` implementation for edit task test commands, passing the actual exit code to `check_correctness`.

**Fix:** Remove or update both limitation sections from `known-limitations.md` to reflect current state. Effort: trivial documentation edit.

---

## 3. Genuinely Good

**Zero-denominator guard in `cost_per_correct`** (`stats.py:79-80`): When correct_count is 0, the function returns `0.0` — no NaN, no division-by-zero, no silent propagation. The guard is tested in `test_stats.py:101-108`. The `_compute_per_task_deltas` function (`report.py:51`) adds a second layer: if `cpc0 > 0` gates the delta computation, so tasks where baseline is all-wrong are skipped entirely. No NaN/inf is possible in the bootstrap CI output.

Repro confirming guard:
```python
# /tmp/copeca_venv/bin/python
import sys; sys.path.insert(0, '/tmp/copeca_audit/src')
from copeca.analysis.stats import cost_per_correct, bootstrap_ci
import math

print(cost_per_correct([{'total_cost_usd': 0.1, 'correct': False}]))
# Output: 0.0

ci = bootstrap_ci([-100.0]*16, n_resamples=10000)
print(any(math.isnan(x) or math.isinf(x) for x in ci))
# Output: False
```

**`cost.py` purity** (`cost.py:7-31`): `compute_cost` is a clean, total, deterministic function. No I/O, no imports from side-effectful layers, no hidden throws for valid numeric inputs. The formula is exactly as documented. The only raise path is `KeyError` on missing dict keys — explicitly documented in the docstring. Credit: architecture/S.U.P.E.R. compliance.

**Task-level pairing in the CI** (`report.py:25-54`): Although `metrics.md` describes the wrong procedure, what the code *does* is actually statistically sound. By computing `delta[task] = (cpc1 - cpc0)/cpc0` per task before bootstrapping, the paired structure across modes is preserved — cross-mode variance is eliminated at the task level. This is more appropriate than an independent per-mode bootstrap for N=16 tasks.

**`validate_scenario` low-repetition advisory** (`validation.py:169-173`): Warns when `repetitions < 5`, which is accurate statistical advice for a ratio metric with small N.

---

## 4. Tend .html Files Affected by Code Issues

| Tend file | Issue |
|-----------|-------|
| `copeca-cost-model.tend.html` | F2 (divergence "triggers a staleness warning" — never shown), F3 (staleness check described as fired at scenario validation time — never called), F5 (self-reported tokens not disclosed) |
| `pricing-drift-unchecked.tend.html` | F2 (narrative shows user-visible divergence output that doesn't exist), F3 (staleness warning described but not implemented as callable) |
| `copeca-analysis-reporting.tend.html` | F1 (narrative at line 2606 is accurate; the inconsistency is in metrics.md, not this file) |
