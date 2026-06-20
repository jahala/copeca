# copeca remediation plan — verified findings → tasks

**Status:** findings independently re-verified 2026-06-20 against this workspace
(`jahala/deepseek-toggle`, source byte-identical to audited clone `37075dc`).
**Env:** `.venv/bin/python` (3.11, editable install of this workspace). Baseline: **387 tests pass.**
**Verification:** 5 parallel agents re-checked every cited `file:line` and re-ran every repro here.
Source audit + sub-reports: `docs/research/audit-2026-06-20/`.

**Engagement rule (carried from the audit brief):** minimal patches; **failing test first**
(copeca's own engineering.md rule); confirm before modifying repo files; keep the tend garden
1:1 with code (refresh the listed `*.tend.html` when its behavior changes).

---

## What changed vs the original audit (verification deltas)

| Item | Original audit | Verified verdict |
|------|----------------|------------------|
| F-C1 / F-C2 / F-C3 | CRITICAL | **CONFIRMED** — all three repro'd here |
| L3 `.venv` not gitignored | LOW | **Partly REFUTED** — `.gitignore:4 .venv/` works. Real gaps: `playwright-mcp/` typo (`.gitignore:16`, should be `.playwright-mcp/`) + orphan `.gitignore.new` |
| F-M6 edit-task strings "silently ignored" | MEDIUM bug | **NUANCED → doc gap** — behavior is documented in code (`config/models.py:58`, `validator.py:39`); missing only from README/methodology |
| Stale known-limitations | 3 (F-H5) | **4** — also "repo validation requires `--repos`" (auto-discovery exists, `cli.py:37-40`) |
| tend drift | not flagged | pricing-staleness feature marked "Implemented" in garden but `check_pricing_staleness` (`validation.py:18`) has **0 callers** |
| Zip-slip / unsafe YAML | flagged to check | **CLEAN** — no `extractall`; all `yaml.safe_load`. Do not "fix." |
| Genuinely good | cost.py pure, paired CI, no-NaN | **CONFIRMED** — do not touch the working stats code (L1 is doc-only) |

---

## Verified findings ledger

Effort: S ≈ <1h · M ≈ a few hours · L ≈ design + multi-file. ✓ = repro run in this workspace.

| ID | Sev | Title | Fix site(s) | Failing test | tend feature |
|----|-----|-------|-------------|--------------|--------------|
| **F-C1** ✓ | CRIT | cost-per-correct inverts: 0-correct → `$0.0000` / −100% | `analysis/stats.py:79-80`; `analysis/report.py:49-53,219-227,233-258`; `analysis/compare.py:62` | `tests/analysis/test_stats.py:101-108` (flip assert) + new report integration test | `copeca-analysis-reporting`, `accuracy-blind-claims` |
| **F-C2** ✓ | CRIT | "tamper-proof hash chain" is a self-hash; forgeable | text: `README.md:67`, `index.html`, integrity `*.tend.html`. mechanics: `results/artifact.py:48,71-94`; `results/verification.py:74-78,155-163` | `tests/results/test_verify_single.py::test_forged_artifact_is_rejected` (new) | `copeca-artifact-integrity`, `no-verifiable-results` |
| **F-C3** ✓ | CRIT | "provably clean" baseline inherits full env; `provision_arm` dead (0 callers) | `runners/subprocess.py:33`; wire `orchestration/state.py:27-81` into `orchestration/run.py` (`run_single` 23-34, `_run_one_work_item` 353-387, call ~147) | `tests/runners/test_subprocess_env_isolation.py` (new) | `copeca-cost-model`, `copeca-single-run`, `copeca-mode-mechanism` |
| **F-H1** ✓ | HIGH | 3 of 6 adversarial flags always `None`; `budget_usd` never enforced | `orchestration/run.py:147,221-229`; `config/models.py:184` | `tests/orchestration/test_adversarial_flags.py` (budget_exhausted True over budget) | `copeca-scenario-matrix` |
| **F-H2** ✓ | HIGH | string grading keyword-stuffable / paraphrase-brittle (substring) | `tasks/validator.py:25-28` (mitigate) + disclose | `tests/tasks/test_validator.py` (wrong-but-keyworded fails; underscore paraphrase passes) | `copeca-single-run` (validate-tasks) |
| **F-H3** ✓ | HIGH | `forbidden_strings` AND-bug: partial refusal passes (10/16 tasks) | `tasks/validator.py:62` (one line: `all`→`any`) | `tests/tasks/test_validator.py::test_partial_refusal_should_fail` | `copeca-single-run` |
| **F-H4** ✓ | HIGH | contamination defense is theater (static blocklist, 0 model calls, unwired, 0/16 match) | `scripts/contamination_check.py`; `README.md:124-127` | `tests/tasks/test_contamination_check.py` (assert a probe is made) — or relabel claim | `contamination-erodes-trust` |
| **F-H5** ✓ | HIGH | known-limitations.md stale ×4 (under-claims implemented features) | `docs/known-limitations.md:40-46,48-53,55-62` + repo `--repos` section | n/a (doc) — verified against `cli.py:245-271`, `check.py:24-125`, `run.py:75-114,277-324` | `copeca-single-run`, `copeca-scenario-matrix` |
| **F-H6** ✓ | HIGH | phantom surface: `verify --batch`, `codex_json`/`generic` parsers, packaging globs | `cli.py:274-291`; `runners/parsers/`; `pyproject.toml:43`; `README.md:67,144`, `architecture.md:96-97`, `runner-configuration.md:83` | wheel-install smoke test (new) | (packaging/CLI) |
| **F-H7** ✓ | HIGH | six-source-family governance in present tense (real: 16 tasks/1 family) | `docs/methodology.md:40-54` (reconcile w/ `known-limitations.md:32-38`) | n/a (doc) — `copeca validate tasks/` → 16; `tasks/` = 4 dirs, 1 family | (methodology) |
| **F-M1** ✓ | MED | token_snowball formula ≠ docs, not configurable (hardcoded 3×) | `orchestration/run.py:233-244`; `config/models.py:171-187`; `metrics.md:111,117` | `tests/orchestration/test_adversarial_flags.py` (config'd factor) | `copeca-scenario-matrix` |
| **F-M2** ✓ | MED | only real cost safeguard is invisible; `check_pricing_staleness` dead (0 callers) | surface in `cli.py`; call `validation.py:18`; `run.py:131-139,192-194` | `tests/cli/test_run_cli.py` (stderr shows >5% divergence) | `copeca-cost-model`, `pricing-drift-unchecked` (FIX TEND DRIFT) |
| **F-M3** ✓ | MED | concurrency TOCTOU on shared worktree path (`max_workers>1`) | `repos/manager.py:87,90-93`; `orchestration/run.py:319` | `tests/repos/test_manager_concurrency.py` (new) | (repo/worktree) |
| **F-M4** ✓ | MED | `mode.setup` runs `shell=True` on scenario strings | `orchestration/state.py:99-108` | `tests/orchestration/test_state.py` (injection string no-ops) | `copeca-mode-mechanism` |
| **F-M5** ✓ | MED | "computed not trusted" still trusts self-reported token counts | disclose; `parsers/stream_json.py:59-64`→`run.py:122-128` | n/a (doc) | `copeca-cost-model` |
| **F-M6** ✓ | MED→LOW | edit-task req/forbidden diagnostic-only — **doc gap** (already in code) | `README.md`, `docs/methodology.md` (1 sentence) | n/a (doc) — behavior correct by design | `copeca-single-run` |
| **F-M7** ✓ | MED | neutrality: 3 mode YAMLs + ~14 README lines + 4 source comments name external products | `defaults/modes/{rtk,gateway,headroom}.yaml`; `README.md:78,102-106,144,156` | n/a — rename + move examples | (modes/neutrality) |
| **L1** ✓ | LOW | metrics.md bootstrap *description* wrong (code is sound — DOC ONLY) | `docs/metrics.md:42-54` | none — DO NOT change `report.py`/`stats.py` | `copeca-analysis-reporting` |
| **L2** ✓ | LOW | hardcoded `copeca_version="0.1.0"` ×2 | `orchestration/run.py:184`, `results/artifact.py:84` | `tests/test_version_sync.py` (new) | (metadata) |
| **L3** ✓ | LOW | gitignore: `.playwright-mcp/` typo + orphan `.gitignore.new` | `.gitignore:16`; resolve `.gitignore.new` | n/a | n/a |
| **L4** ✓ | LOW | no zip-bomb size cap on `copeca verify` | `results/verification.py:66` | `tests/results/test_verify_single.py::test_zip_bomb_rejected` (new) | `copeca-artifact-integrity` |

**Confirmed-good (do NOT touch):** `runners/cost.py:25-31` (pure), paired delta CI (`report.py:25-54,246-248`),
`test_command` safe argv (`run.py:80-86`), `all_of` requires-all (`validator.py:72`), zip read in-memory (no slip), `yaml.safe_load` throughout.

---

## Design decisions to lock before coding (Phase 0/1 criticals)

1. **F-C1 sentinel.** 0-correct cost-per-correct → render `n/a (0 correct)`; exclude 0-correct cells
   from the headline delta AND the bootstrap; never emit a negative delta from a zero denominator;
   add **accuracy as a co-headline** so cost is never read without correctness. (Use `None`/`inf`
   sentinel internally; the existing no-NaN guards stay.)
2. **F-C3 env policy.** Strict **allowlist** in `SubprocessRunner.run` (PATH, HOME, the agent's API-key
   var, + keys a mode explicitly declares) rather than denylist; wire `provision_arm` so `ArmHarness.env`
   + `config_dir` reach the child. Test must prove (a) a real run still works, (b) an ambient hook var is absent.
3. **F-C2 claim now, anchor later.** Phase 0 = stop calling it tamper-proof ("integrity manifest:
   detects accidental corruption, not adversarial tampering"). Phase 2 = detached signature over
   `content_hash` + external append-only anchor + cross-artifact chain.
4. **F-H6 `verify --batch`.** It's implemented (`verification.py:105-165`) but count-based (can't catch
   "re-ran until favorable"). Phase 0 = **soften the README cherry-pick claim** (don't ship a half-true
   surface). Phase 1 = wire the CLI flag *and* make detection identity-based + per-rep filenames.

---

## Phased task list

### Phase 0 — truth-fixes (stop active misrepresentation; test-first; hours)
- **P0-1** F-H3 forbidden `all`→`any` (one line) — failing test first. *warm-up, highest run-frequency honesty win.*
- **P0-2** F-C1 metric-inversion guard + co-headline accuracy — failing test first (decision #1).
- **P0-3** F-C2 **text**: rename the integrity claim everywhere (README/index.html/tend) (decision #3).
- **P0-4** F-H5 delete/correct the **4** stale known-limitations.
- **P0-5** F-H6 docs: soften `verify --batch` cherry-pick claim (decision #4); remove or `planned`-mark `codex_json`/`generic` parser claims.
- **P0-6** F-H7 methodology six-family → roadmap tense; reconcile with known-limitations.
- **P0-7** Disclosures: F-H2 (string-match gameable), F-M5 (self-reported tokens), F-M6 (edit-task diagnostic-only), L1 (fix metrics.md bootstrap prose).
- **P0-CHECKPOINT** re-read all P0 diffs; full suite + `scripts/smoke_test.sh` green; reconcile touched `*.tend.html`.

### Phase 1 — isolation & visibility (test-first; ~1–2 days)
- **P1-1** F-C3 allowlist child env + wire `provision_arm` (decision #2) — failing env-isolation test.
- **P1-2** F-M2 surface >5% divergence (stderr + report row) + call `check_pricing_staleness`; **fix tend drift**.
- **P1-3** F-C2 mechanics: per-rep artifact filename index + identity-based `verify_batch`; then wire `verify --batch` CLI (decision #4).
- **P1-4** F-H6 packaging: move `schemas/`+`tasks/` under package (or `MANIFEST.in`/`include_package_data`) + **wheel-install smoke test**.
- **P1-5** L3 gitignore: fix `.playwright-mcp/`; resolve `.gitignore.new`.
- **P1-CHECKPOINT** full suite + wheel smoke; reconcile tend.

### Phase 2 — design-level
- **P2-1** F-H1/F-M1 thread + enforce `budget_usd`; implement-or-defer talkative/tool_storm; fix token_snowball formula + make threshold a Scenario field.
- **P2-2** F-C2 real tamper-evidence: signed + externally anchored artifacts + cross-artifact chain.
- **P2-3** F-H4 implement contamination probe wired into `validate` — or formally defer in known-limitations.
- **P2-4** F-M3 per-work-item worktree keying + lock (or process pool w/ per-worker bare clones).
- **P2-5** F-M4 / L2 / L4 hardening: `mode.setup` argv (drop `shell=True`); `importlib.metadata` version; zip-bomb size cap.
- **P2-6** F-M7 neutrality rename: generic mode names; move named examples to user docs; keep `ADAPTED from` lineage comments.
- **FINAL PR-REVIEW** whole-diff review: code quality/SUPER, type-check, build wheel, full tests, smoke, tend garden 1:1, no aspirational present tense left.

---

## tend reconciliation (keep garden 1:1)
Touched features to refresh narrative + audit badge after each behavior change:
`copeca-analysis-reporting`, `accuracy-blind-claims`, `copeca-artifact-integrity`, `no-verifiable-results`,
`copeca-cost-model`, `pricing-drift-unchecked` (drift), `copeca-single-run`, `copeca-mode-mechanism`,
`copeca-scenario-matrix`, `contamination-erodes-trust`.
