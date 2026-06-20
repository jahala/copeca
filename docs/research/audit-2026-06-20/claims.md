# Copeca Audit Report — Claims Ledger & Findings

Audit date: 2026-06-20. Auditor: claude-sonnet-4-6 (tilth agent).
Scope: doc↔code parity, neutrality, corpus/governance, test quality, packaging.

---

## 1. THE CLAIMS LEDGER

### 1.1 README.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| R1 | "A neutral, reproducible, verifiable benchmark for CLI-based coding agents" | README.md:3 | — | OVERCLAIMED (partial) | "Neutral" is undermined by shipping mode YAMLs named after specific products (rtk.yaml, gateway.yaml, headroom.yaml). Reproducible and verifiable are genuine. |
| R2 | `cost_per_correct = total_spend / correct_count` | README.md:9-10 | analysis/stats.py:63-82 | HOLDS | `cost_per_correct()` divides total cost by correct count; returns 0.0 on zero correct. |
| R3 | "A tool that saves 90% of tokens but makes 20% more mistakes has worse cost-per-correct" | README.md:13-15 | analysis/stats.py:63-82 | HOLDS | Numerically follows from the formula. |
| R4 | "copeca holds the agent and model fixed and varies one tool" | README.md:20 | orchestration/run.py:247-350 | HOLDS | `run_matrix` builds cartesian product over same tasks/models, varying mode. |
| R5 | "parallel git-worktree-isolated workers" | README.md:95 | orchestration/run.py:319 | HOLDS | ThreadPoolExecutor at run.py:319; StubRepoManager test confirms per-thread worktrees. |
| R6 | "The baseline is provably clean — it never inherits the host's ambient hooks" | README.md:108-109 | orchestration/state.py:provision_arm | HOLDS | baseline mode returns empty env {}, config_dir None, wrapper None (verified by test_mode_isolation.py:34-44). |
| R7 | "Cost — computed, never trusted from vendor self-reported numbers" | README.md:63 | orchestration/run.py:119-139 | HOLDS | `compute_cost(tokens, pricing)` overwrites vendor cost; vendor cost stored as `vendor_cost_usd` cross-check only. |
| R8 | "Correctness — string matching (comprehension tasks) or test-command exit codes (edit tasks)" | README.md:64 | tasks/validator.py:36-112 | HOLDS | Both branches implemented and tested. |
| R9 | "Completeness — all_of field verifies agent listed everything" | README.md:65 | tasks/validator.py:70-77 | HOLDS | `_check_strings(result_text, ground_truth.all_of)` implemented. |
| R10 | "Futility — adversarial flags: token snowball, talkative failure, tool storm, budget exhaustion, timeout" | README.md:66 | orchestration/run.py:204-230 | OVERCLAIMED | `talkative_failure` is always None (run.py:228); `tool_storm` is always None (run.py:229). Only token_snowball, budget_exhausted, timeout, error are computed. |
| R11 | "Integrity — .copeca artifact zips with SHA-256 hash chains; copeca verify --batch proves nothing was cherry-picked" | README.md:67 | results/artifact.py, results/verification.py | OVERCLAIMED | `verify_batch()` function exists (verification.py:105-164) but `copeca verify --batch` CLI flag does NOT exist — `copeca verify` only accepts a single artifact path. `--batch` is not wired. |
| R12 | "Current corpus size: 16 tasks" | README.md:52 | tasks/ directory | HOLDS | Confirmed: 16 YAML files under tasks/. |
| R13 | "Roadmap targets ~85 tasks across 6 independent source families" | README.md:53 | — | STALE-UNDERCLAIM (aspirational, mislabeled) | README correctly labels this as roadmap. Acceptable as framing. |
| R14 | "Built-in parsers: stream_json (Claude Code), codex_json (Codex), generic (configurable JSONPath mappings)" | README.md:144 | runners/parsers/ | OVERCLAIMED | Only `stream_json.py` and `base.py` exist. `codex_json` and `generic` parsers do NOT exist in the codebase. |
| R15 | "5 additional source families planned (SCBench, Long Code Arena, CrossCodeEval, SWE-bench-Live, Terminal-Bench 2.0)" | README.md:118-119 | — | HOLDS (plan statement) | Correctly stated as planned, not present. |
| R16 | "Contamination self-check: before a task enters the corpus, copeca probes the model with the task ID alone" | README.md:124-126 | — | UNVERIFIABLE | No code implements this check. No `contamination_check` function exists in src/. Stated as a governance rule without implementation. |
| R17 | "Task types deprecated by their own creators (SWE-bench Verified, Feb 2026) are explicitly blocked" | README.md:127-128 | tasks/test_first_10.py:28-33 | HOLDS | `BLOCKED_SOURCE_PREFIXES = ("SWE-bench Verified", ...)` enforced in test_first_10.py. |
| R18 | "pip install copeca; copeca init; copeca run; copeca analyze" | README.md:28-32 | cli.py:25-401 | HOLDS | All subcommands verified. |

---

### 1.2 docs/methodology.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| M1 | "The headline metric is always the delta between two modes" | methodology.md:11-14 | analysis/report.py:216-256 | HOLDS | Report leads with delta and CI. |
| M2 | "The task corpus draws from six independent source families" (present tense) | methodology.md:40-54 | tasks/ directory | OVERCLAIMED | Present-tense statement. Corpus is 16 tasks from 1 family (SWE-QA only). The 6-family table reads as current fact, not plan. |
| M3 | "No source family dominates. If one source's tasks systematically favor a particular tool, the other five dilute the effect." | methodology.md:53-54 | tasks/ directory | OVERCLAIMED | There are no "other five" families yet — 16/16 tasks are SWE-QA. |
| M4 | "Mode isolation: each mode runs with its own config dir, env, git worktree" | methodology.md:74-81 | orchestration/state.py | HOLDS | provision_arm() wires all three. |
| M5 | "Edit tasks — test-command exit codes. copeca check-task pre-verifies" | methodology.md:93-95 | orchestration/check.py | HOLDS | `verify_mutation_validity()` fully implemented. |
| M6 | "No embedded Python. No eval. No LLM judge." | methodology.md:97-98 | tasks/validator.py | HOLDS | Correctness is pure string/subprocess; no eval. |
| M7 | "Bootstrap CI assumes i.i.d." (limitation) | methodology.md:106-110 | analysis/stats.py:146-186 | HOLDS | Documented limitation accurately describes the implementation. |
| M8 | "Adversarial flags are heuristics" (limitation) | methodology.md:112-115 | orchestration/run.py:204-230 | HOLDS | Documented. Flags that need missing data return None. |
| M9 | "Pricing data goes stale — warns at >30 days but does not block" | methodology.md:117-120 | orchestration/validation.py:check_pricing_staleness | HOLDS | Warning logic verified in test_staleness.py. |
| M10 | "Single-provider per scenario" (limitation) | methodology.md:128-131 | cli.py:run() | HOLDS | One runner per run; scenario uses same runner for all modes. |
| M11 | "~85 tasks cannot represent every coding domain" (limitation) | methodology.md:133-134 | — | STALE-UNDERCLAIM (OK) | Refers to planned corpus; current is 16. Limitation is understated but not false. |

---

### 1.3 docs/known-limitations.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| KL1 | "check-task subcommand that pre-verifies edit task mutations is not yet implemented as a CLI command" | known-limitations.md:42-46 | cli.py:245-271, orchestration/check.py | STALE-UNDERCLAIM | `check-task` IS fully implemented as a CLI command (`copeca check-task --help` works). `verify_mutation_validity()` at check.py:24 is complete. This limitation is false/stale. |
| KL2 | "Matrix runner is sequential — max_workers acknowledged but deferred" | known-limitations.md:49-53 | orchestration/run.py:319 | STALE-UNDERCLAIM | `run_matrix()` uses `ThreadPoolExecutor(max_workers=max_workers)` at run.py:319. Parallelism IS implemented. The limitation is false/stale. |
| KL3 | "test_command_passed always None in orchestrator" | known-limitations.md:55-62 | orchestration/run.py:75-113 | STALE-UNDERCLAIM | `test_command_passed` IS computed via real `subprocess.run()` at run.py:80-109. The limitation is false/stale. |
| KL4 | "Layer 3 repo validation requires --repos flag" | known-limitations.md:64-70 | cli.py:36-40 | PARTIALLY STALE | CLI now auto-discovers repos.yaml in cwd (cli.py:37-40). Still requires explicit flag if repos.yaml is not in cwd. Limitation is partially but not fully stale. |
| KL5 | "Bootstrap CI assumes task independence" | known-limitations.md:9-15 | analysis/stats.py:146-186 | HOLDS | Accurately describes implementation. |
| KL6 | "Seed corpus is 16 tasks from 1 source family" | known-limitations.md:32-38 | tasks/ directory | HOLDS | Correct at time of audit. |

---

### 1.4 docs/metrics.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| ME1 | "cost_per_correct = total_cost_usd / correct_count" | metrics.md:12-13 | analysis/stats.py:63-82 | HOLDS | Implementation matches exactly. |
| ME2 | "Bootstrap CI: pool (cost, correct) pairs, resample N with replacement 10,000 times, 2.5th/97.5th percentiles" | metrics.md:46-50 | analysis/stats.py:146-186 | PARTIALLY OVERCLAIMED | bootstrap_ci() at stats.py:146 bootstraps values of one type (floats), not paired (cost, correct) pairs. The delta CI in report.py:245-248 bootstraps per-task delta percentages — not the paired cost/correctness approach described. Functionally reasonable but description doesn't match implementation. |
| ME3 | "The same resamples produce a CI on the delta between modes. Overlapping CIs do not mean delta is non-significant — the delta CI is computed directly from the paired bootstrap." | metrics.md:52-54 | analysis/report.py:245-248 | OVERCLAIMED | Delta CI is computed from per-task delta percentages (not "same resamples" as mode CIs). The phrase "paired bootstrap" and "same resamples" is inaccurate — two separate bootstrap calls are used. |
| ME4 | "talkative_failure — output_tokens > threshold AND correct == false" | metrics.md:112 | orchestration/run.py:228 | OVERCLAIMED | Flag is always None (run.py:228: `"talkative_failure": None`). Not implemented. |
| ME5 | "tool_storm — num_tool_calls > threshold" | metrics.md:113 | orchestration/run.py:229 | OVERCLAIMED | Flag is always None (run.py:229). Not implemented. |
| ME6 | "All thresholds are configurable in the scenario YAML." | metrics.md:117 | config/models.py | UNVERIFIABLE | Scenario model does not appear to expose `talkative_failure_threshold` or `tool_storm_threshold` fields. Since neither flag is implemented, the claim is moot but still overclaims. |
| ME7 | "Token breakdown: four categories, each with its own price" | metrics.md:79-95 | runners/cost.py, run.py:119-139 | HOLDS | All four token categories computed and costed. |

---

### 1.5 docs/architecture.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| A1 | "runners/parsers/codex_json.py — Codex output parser" | architecture.md:96 | (file missing) | OVERCLAIMED | File does not exist. Only stream_json.py and base.py exist under runners/parsers/. |
| A2 | "runners/parsers/generic.py — JSONPath-configurable parser" | architecture.md:97 | (file missing) | OVERCLAIMED | File does not exist. |
| A3 | "Every edit task proves its mutation bites. check-task verifies..." | architecture.md:318-320 | orchestration/check.py | HOLDS | Fully implemented. |
| A4 | "The domain layer has no I/O" | architecture.md:330-332 | config/, tasks/, analysis/ | HOLDS | No I/O imports found in domain layer directories. |
| A5 | "Workers are repo-affine (assigned to one repo for lifetime)" | architecture.md:232-233 | orchestration/run.py:319-349 | OVERCLAIMED | Workers in ThreadPoolExecutor are NOT repo-affine. Work items are submitted to any available thread; there is no affinity routing. |

---

### 1.6 docs/runner-configuration.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| RC1 | "CodexJsonParser (codex_json) — Parses Codex output format" | runner-configuration.md:83 | (file missing) | OVERCLAIMED | No codex_json.py in src/copeca/runners/parsers/. |
| RC2 | "GenericParser (generic) — Configurable JSONPath mappings" | runner-configuration.md:84 | (file missing) | OVERCLAIMED | No generic.py in src/copeca/runners/parsers/. |
| RC3 | "Process-group isolation — preexec_fn=os.setsid" | runner-configuration.md:64 | runners/subprocess.py | HOLDS | Verified in subprocess.py. |
| RC4 | "CLAUDECODE env var stripped before subprocess launch" | runner-configuration.md:67-69 | runners/subprocess.py | HOLDS | test_subprocess.py:27-40 confirms filtering. |

---

### 1.7 docs/engineering.md

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| E1 | "No mocking our own logic. Mock only at true external boundaries: subprocess call, network (git clone)." | engineering.md:124-127 | tests/ | HOLDS (mostly) | Only StubRepoManager (matrix shape tests) and _freeze_date() (date mock) found. Both mock at genuine external boundaries. See Test Quality section. |
| E2 | "Test output must be pristine" | engineering.md:122-123 | (pytest run) | HOLDS | Suite reported GREEN at baseline. |
| E3 | "Domain layer imports rule enforced" | engineering.md:84-86 | architecture.md | UNVERIFIABLE | No import-linter or CI grep is present in the codebase to mechanically enforce it. Stated as "enforceable via architecture tests" but no such test exists. |

---

### 1.8 Pyproject.toml / Packaging

| # | Claim | Source file:line | Implementing code file:line | Status | Evidence |
|---|-------|------------------|-----------------------------|--------|----------|
| P1 | `requires-python = ">=3.11"` | pyproject.toml:10 | — | HOLDS | Declared. |
| P2 | `copeca = "copeca.cli:app"` entry point | pyproject.toml:37 | cli.py:18 | HOLDS | `app = typer.Typer(...)` at cli.py:18. All subcommands verified. |
| P3 | `package-data: copeca = ["schemas/*.json", "tasks/**/*.yaml"]` | pyproject.toml:43 | src/copeca/ | OVERCLAIMED | `src/copeca/schemas/` does NOT exist. Schemas live at `/tmp/copeca_audit/schemas/` (project root), NOT inside the package. The package-data glob references a path that doesn't exist in the installed package. **This means wheels will not include schemas or tasks data.** The `tasks/**/*.yaml` path has the same problem — tasks live at project root, not inside `src/copeca/`. |
| P4 | Subcommands: init, run, analyze, verify, validate, list, check-task, compare | pyproject.toml / cli.py | cli.py:25-401 | HOLDS | All 8 subcommands present and functional. |

---

## 2. FINDINGS BY SEVERITY

---

### F1 — CRITICAL: known-limitations.md is triple-stale (three claimed limitations are false)

**Severity:** CRITICAL
**Claims:** known-limitations.md:42-62 (check-task, sequential matrix, test_command_passed always None)
**Evidence:**
- `check-task` CLI: implemented at cli.py:245-271, orchestration/check.py:24-125.
- ThreadPoolExecutor: orchestration/run.py:319 — parallelism wired, default max_workers=1 but configurable.
- test_command_passed: run.py:75-113 runs real subprocess, computes bool.
**Argument:** All three limitations in known-limitations.md:40-62 are false. Users reading this document will believe features do not exist that do exist, undermining trust.
**Fix:** Remove or strike-through all three sections. Add brief note that they were resolved.
**Effort:** Low — documentation only.

---

### F2 — HIGH: Missing parsers (codex_json, generic) claimed in README, architecture.md, runner-configuration.md

**Severity:** HIGH
**Claims:** README.md:144, architecture.md:96-97, runner-configuration.md:83-84
**Evidence:** `ls /tmp/copeca_audit/src/copeca/runners/parsers/` → only `base.py`, `stream_json.py`, `__init__.py`. No `codex_json.py` or `generic.py`.
**Argument:** Three separate documentation sources claim these parsers exist and are "built-in." They are not. Any user relying on these parsers will find them missing at runtime.
**Fix:** (a) Implement the parsers, or (b) change docs to "planned" / "not yet implemented." Add to known-limitations.md.
**Effort:** Medium (implement) or Low (document accurately).

---

### F3 — HIGH: Package-data references non-existent paths inside the package

**Severity:** HIGH
**Claims:** pyproject.toml:43 — `copeca = ["schemas/*.json", "tasks/**/*.yaml"]`
**Evidence:** `ls /tmp/copeca_audit/src/copeca/schemas` → "No such file or directory". Schemas are at `/tmp/copeca_audit/schemas/`. Tasks are at `/tmp/copeca_audit/tasks/`. Neither is inside `src/copeca/`.
**Argument:** When a wheel is built, `package-data` only packages files inside the package directory (`src/copeca/`). The globs reference paths that don't exist there. The installed `copeca` package will not include schemas or seed task corpus. `copeca init` copies from the project root at dev time but will fail from an installed wheel.
**Fix:** Either move schemas and tasks into `src/copeca/schemas/` and `src/copeca/tasks/`, or use `data_files` / `package.include` to reference them correctly. Verify `copeca init` works from a wheel installation.
**Effort:** Medium.

---

### F4 — HIGH: Methodology.md governance table presented as current, not planned

**Severity:** HIGH
**Claims:** methodology.md:40-54
**Evidence:** Present-tense "The task corpus draws from six independent source families" with a full table listing all six. All 16 tasks are SWE-QA (known-limitations.md:34 and task file audit confirm this).
**Argument:** The table reads as an active description of the corpus. Someone evaluating copeca as a measurement instrument will assume all six families are active. The single-family domination is a significant statistical limitation (methodology.md itself acknowledges it at lines 53-54, which then immediately contradicts itself by claiming the other five dilute bias).
**Fix:** Add explicit "Planned (0 tasks currently)" column to the governance table. Change narrative from present tense to "will draw from" for non-SWE-QA families.
**Effort:** Low.

---

### F5 — HIGH: `copeca verify --batch` referenced in README but not implemented in CLI

**Severity:** HIGH
**Claims:** README.md:67 — "`copeca verify --batch` proves nothing was cherry-picked"
**Evidence:** `copeca verify --help` shows no `--batch` flag. `verify_batch()` function exists at results/verification.py:105 but is not wired to any CLI command.
**Argument:** The README markets `--batch` as a key integrity feature for skeptical evaluators. The function exists but the CLI flag does not. Users cannot access the batch verification from the CLI.
**Fix:** Wire `verify_batch()` to `copeca verify --batch <results-dir>` in cli.py.
**Effort:** Low.

---

### F6 — MEDIUM: talkative_failure and tool_storm flags documented but always None

**Severity:** MEDIUM
**Claims:** README.md:66, metrics.md:112-113, architecture.md §4 flags table
**Evidence:** orchestration/run.py:228-229: `"talkative_failure": None, # requires correctness context across reps` and `"tool_storm": None, # requires threshold config from scenario`
**Argument:** Both flags are named in the README's "What copeca measures" table without qualification. metrics.md describes them with formulas. The flags are always None in practice — not "null when data is absent" but unconditionally null because the computation is not written. This is a capability claim without implementation.
**Fix:** Either implement both flags or add them to known-limitations.md and qualify the README/metrics table with "(not yet implemented)".
**Effort:** Medium (implement) or Low (document).

---

### F7 — MEDIUM: Bootstrap CI description does not match implementation

**Severity:** MEDIUM
**Claims:** metrics.md:46-54 — "Pool all (cost, correct) pairs from N runs... The same resamples produce a CI on the delta... computed directly from the paired bootstrap."
**Evidence:** `bootstrap_ci()` at analysis/stats.py:146 takes a flat `list[float]` and bootstraps means. The delta CI in report.py:245-248 bootstraps per-task delta percentages, not paired (cost, correct) pairs. Two separate bootstrap calls are used (not "the same resamples").
**Argument:** The description implies a single paired resampling procedure that jointly produces mode CIs and delta CI from the same draws. The actual implementation is simpler and separate. The description overclaims statistical rigor without changing the practical output materially, but a statistician reading the docs would find the implementation does not match.
**Fix:** Rewrite metrics.md:46-54 to accurately describe what `bootstrap_ci()` does: independently bootstraps per-task delta percentages for the delta CI, and per-run costs for per-mode CIs.
**Effort:** Low.

---

### F8 — MEDIUM: Architecture doc claims "workers are repo-affine"

**Severity:** MEDIUM
**Claims:** architecture.md:232-233 — "workers are repo-affine (assigned to one repo for lifetime)"
**Evidence:** orchestration/run.py:319-349 — `ThreadPoolExecutor` with work items submitted to any available thread. No routing or affinity based on repo key.
**Argument:** Repo-affine workers matter for performance (avoids bare-clone re-fetch races between threads) and for the documentation promise about resource sharing. The actual implementation does not enforce affinity.
**Fix:** Either implement repo-affine dispatch or remove the affinity claim from architecture.md.
**Effort:** Medium (implement) or Low (document accurately).

---

### F9 — MEDIUM: Contamination self-check claimed with no code implementation

**Severity:** MEDIUM
**Claims:** README.md:124-126 — "before a task enters the corpus, copeca probes the model with the task ID alone — if it reproduces the gold solution from memory, the task is excluded"
**Evidence:** No `contamination_check` or equivalent function exists anywhere in `src/copeca/`. No test covers it. No CLI subcommand for it.
**Argument:** This is a strong governance claim cited as a reason to trust the corpus. It is stated as a present-tense process, not a roadmap item. Without implementation it is vapor governance.
**Fix:** Add to known-limitations.md as "not yet implemented." Change README phrasing to future tense or remove until implemented.
**Effort:** Low (document) or High (implement — requires running a model).

---

### F10 — LOW: Hardcoded version string in run.py and artifact.py

**Severity:** LOW
**Claims:** orchestration/run.py:184, results/artifact.py:84 — `"copeca_version": "0.1.0"` hardcoded
**Evidence:** Both files contain a literal `"0.1.0"` string. pyproject.toml:7 also has `version = "0.1.0"`.
**Argument:** Version will fall out of sync when the version is bumped. Should read from `importlib.metadata` or `copeca.__version__`.
**Fix:** Use `importlib.metadata.version("copeca")` in both locations.
**Effort:** Low.

---

### F11 — LOW: Domain-layer isolation rule not machine-enforced

**Severity:** LOW
**Claims:** engineering.md:84-86, architecture.md:85-86 — "This is mechanically enforceable via architecture tests (import-linter or a simple grep in CI)."
**Evidence:** No import-linter config or architecture-guard test found in tests/ or pyproject.toml.
**Argument:** The claim that the rule is "mechanically enforceable" implies it IS enforced. It is not. A future PR could introduce a domain/runner import and CI would not catch it.
**Fix:** Add an architecture test (grep or import-linter) or remove "mechanically enforceable" from docs.
**Effort:** Low.

---

### F12 — LOW: `source: "tilth-benchmark"` approved family without public provenance

**Severity:** LOW
**Claims:** tests/tasks/test_first_10.py:25 — `"tilth-benchmark"` in APPROVED_SOURCE_PREFIXES
**Evidence:** test_first_10.py:25 adds "tilth-benchmark" as an approved source family. No such source family is described in methodology.md or README.md.
**Argument:** The governance table in methodology.md lists six families; none is "tilth-benchmark." Adding an unlisted, self-referential source family without documenting its license, provenance, and task selection process undermines the provenance invariant.
**Fix:** Either document "tilth-benchmark" in methodology.md with license and provenance, or remove it from APPROVED_SOURCE_PREFIXES if no tasks use it.
**Effort:** Low.

---

## 3. GENUINELY GOOD

1. **test_command grading for edit tasks is real.** run.py:75-113 runs the actual test command as a subprocess, handles timeout and missing binary gracefully, and records stdout/stderr. The test suite at tests/orchestration/test_single_run.py:237-392 validates all four paths (pass, fail, timeout, binary-not-found) with real subprocess calls. No mocking of the grading path.

2. **Cost computation is pure and well-tested.** `compute_cost()` in runners/cost.py is a pure function. test_cost_computation.py contains hand-calculated expected values independently verified against the formula. The pipeline test in test_cost_in_pipeline.py confirms `total_cost_usd != vendor_cost_usd` when pricing is provided.

3. **Vendor cost divergence warning is wired and tested.** 5% divergence threshold is implemented at run.py:133-138 and tested at test_cost_in_pipeline.py:331-440. Divergence is recorded in metadata, not just logged.

4. **Mode isolation is clean and tested.** provision_arm() correctly returns empty env, None config_dir, None wrapper for baseline. The environment copy-not-reference property is tested in test_mode_isolation.py:71-84. Config dir isolation between arms is tested at lines 221-240.

5. **SHA-256 hash chain is real.** artifact.py and verification.py implement a genuine two-layer hash chain: per-file SHA-256 in `files` dict + `content_hash` as SHA-256 of sorted per-file hashes. verify_artifact() cross-checks both layers. The implementation is solid.

6. **Known-limitations.md acknowledges stale pricing and string-matching brittleness accurately.** These are real limitations, not swept under the rug.

7. **Test quality is high in the integration layer.** test_single_run.py and test_cost_in_pipeline.py use real local git repos (tmp_path + subprocess git init) and real subprocess runners. Mock use is confined to (a) StubRepoManager for matrix shape/cardinality tests (not testing correctness logic), and (b) `_freeze_date` which mocks `date.today()` at a genuine boundary — not the business logic under test.

8. **Pricing staleness warning correctly reads the `updated` field per model.** Each model in the pricing dict has its own `updated` date, and staleness is checked per-model (test_staleness.py:64-76).

---

## 4. NEUTRALITY INVENTORY

Every instance where a specific external/third-party product name appears in shipped files:

| File | Line(s) | Product named | Context | Concern |
|------|---------|--------------|---------|---------|
| README.md | 102 | tilth, sigmap | "MCP server" example column in modes table | tilth is the author's own product. sigmap is a third-party MCP tool. |
| README.md | 103 | Context Gateway, Entroly | "API proxy" example column | Third-party commercial products shipped as examples in the published README. |
| README.md | 104 | RTK | "Config-dir hook" example column | Third-party product named as example. |
| README.md | 105 | headroom | "Process wrapper" example column | Third-party product named. |
| README.md | 106 | claude-context, GrepAI | "Pre-run index" example column | Third-party products named. |
| README.md | 78 | Codex, OpenCode, Gemini CLI | "Platform builders" persona description | Three competitor agent products named in the target-audience section. |
| README.md | 144 | Claude Code, Codex | "Built-in parsers" list (stream_json for Claude Code, codex_json for Codex) | Codex parser is also missing (see F2). |
| README.md | 156 | Claude Code, Codex | "See docs/runner-configuration.md for setting up runners (Claude Code, Codex, etc.)" | — |
| README.md | 183-185 | tilth, petals, tend | "Related" section — links to author's sibling projects | Author self-attribution fine for a Related section, but creates appearance of tool-family affiliation. |
| defaults/modes/rtk.yaml | 1-2 | RTK | Filename AND description: "RTK PreToolUse hook integration" | A mode YAML file named after a specific third-party product is shipped as a default. Users loading defaults get a file that implies RTK is a normal/endorsed integration path. |
| defaults/modes/gateway.yaml | 1-2 | Context Gateway (implied) | Filename "gateway" + description "Context Gateway API proxy" | "Context Gateway" is a specific product name in the description. |
| defaults/modes/headroom.yaml | 1-2, 11 | headroom | Filename + description "Headroom process wrapper" + binary name "headroom" in wrapper list | Shipped default YAML invokes the `headroom` binary. Users running this mode without headroom installed get a runtime error for a third-party tool. |
| docs/runner-configuration.md | 83 | Codex, CodexJsonParser | Parser description references Codex output format by name | — |
| docs/architecture.md | 96 | Codex | "codex_json.py — Codex output parser" | Also: file doesn't exist (F2). |
| docs/copeca-build-workflow.md | 188 | tilth | "ADAPT parser dataclasses from tilth's benchmark/parse.py... COPY from tilth" | Internal build docs reveal copeca source code was adapted/copied from tilth. This is attribution to a sister project but raises questions about clean-room independence. |
| src/copeca/tasks/validator.py | 3 | tilth | "ADAPTED from tilth benchmark/tasks/base.py" | Source-level attribution. |
| src/copeca/tasks/mutations.py | 3 | tilth | "ADAPTED from tilth benchmark/tasks/base.py" | Source-level attribution. |
| src/copeca/runners/parsers/base.py | 3 | tilth | "ADAPTED from tilth benchmark/parse.py" | Source-level attribution. |
| src/copeca/runners/parsers/stream_json.py | 3 | tilth | "ADAPTED from tilth benchmark/parse.py" | Source-level attribution. |

**Neutrality assessment:** Copeca is not neutral in the sense the README claims. The tool ships named-competitor mode YAMLs as defaults, names specific commercial products in its examples table, and its parser code is adapted from a sister product (tilth) by the same author. The "neutral" claim in the README tagline is the claim most in tension with the evidence. The shipped defaults (rtk.yaml, headroom.yaml) hardcode binaries that users must independently install, creating a latent runtime failure for default modes that reference third-party tools.

**Remediation (using generic names only):** Rename defaults/modes/rtk.yaml → `hook-agent-config-example.yaml`, defaults/modes/headroom.yaml → `process-wrapper-example.yaml`, defaults/modes/gateway.yaml → `api-proxy-example.yaml`. Replace the example-column product names in the README modes table with generic labels (`"an MCP tool"`, `"an API proxy"`, `"a hook tool"`, `"a wrapper tool"`, `"an indexer"`). Remove specific third-party binary names from shipped YAML values (replace `headroom` in headroom.yaml with `your-wrapper-binary`).

---

*End of report.*
