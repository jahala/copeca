# Adversarial audit of copeca — consolidated findings & way forward

**Auditor:** Claude (Opus 4.8), 5 parallel sub-audits + first-party verification of every CRITICAL/HIGH proof.
**Repo:** `/tmp/copeca_audit` @ `37075dc` (branch `master`). **Env:** built CPython 3.11 venv at `/tmp/copeca_venv`, `pip install -e .` → CLI + full test suite run for real.
**Verdict in one line:** copeca's instrument is well-architected and mostly honest, but **three load-bearing claims are false in ways that let a *worse* tool look *better*** — the headline cost-per-correct number inverts under failure, the "tamper-proof" artifact is forgeable in seconds, and the "provably clean" baseline inherits the full ambient environment. These are existential for a project whose entire pitch is verifiable neutrality, and all three are proven with runnable repros below.

Baseline I established first (so nothing here is an environment artifact): the test suite is **genuinely green** (387 pass) once a 3.11 venv exists; the 37 "failures" on first run were purely PATH/venv-location. The 16-task corpus validates. `cost.py` is a clean pure function. The delta CI is actually *paired* (sounder than the docs describe). I confirmed the good parts before reporting the bad ones.

---

## 1. Claims ledger (consolidated, deduplicated)

Status: **HOLDS** / **OVERCLAIMED** / **STALE** (doc lags code, usually under-claiming) / **UNVERIFIABLE**. Citations are `file:line` in `/tmp/copeca_audit`.

| # | Claim | Source | Implementing code | Status | Evidence |
|---|-------|--------|-------------------|--------|----------|
| 1 | `cost_per_correct = total_spend / correct_count` | README | `analysis/stats.py:63-82` | **HOLDS** (formula) / see F-C1 | correct as written, but 0-correct → 0.0 inverts the metric |
| 2 | "SHA-256 hash chain… proves nothing was cherry-picked" | README:67, index.html, `copeca-artifact-integrity.tend.html` | `results/artifact.py:71-94`, `results/verification.py:74-102` | **OVERCLAIMED** | self-hash inside the same zip; forgeable (F-C2 repro) |
| 3 | "provably clean baseline", "each arm provisioned with its own env" | README:108-109, methodology.md:79, architecture.md:21 | `runners/subprocess.py:33`; `orchestration/state.py:27` | **OVERCLAIMED** | child gets full `os.environ` minus 1 key; `provision_arm` never called (F-C3) |
| 4 | "5 adversarial flags" (timeout, error, token_snowball, talkative_failure, tool_storm, budget_exhausted) | README:66, metrics.md:103-117 | `orchestration/run.py:215-230` | **OVERCLAIMED** | 3 of them (`budget_exhausted`, `talkative_failure`, `tool_storm`) are structurally always `None` (F-H1) |
| 5 | "All thresholds configurable in scenario YAML" | metrics.md:117 | `config/models.py` Scenario | **OVERCLAIMED** | no threshold fields exist on the Scenario model |
| 6 | `token_snowball` = `num_turns × avg(first 3) × factor` | metrics.md:111 | `run.py:233-244` | **OVERCLAIMED** | code is `output > avg_first * 3`; no `num_turns`, hardcoded 3× (F-M1) |
| 7 | Cost "computed, never trusted from vendor self-reported numbers" | README:63, metrics.md:15 | `run.py:120-139`, `runners/cost.py` | **OVERCLAIMED** | USD aggregation is recomputed (good) but token *counts* are vendor stdout; no re-tokenization, undisclosed (F-M5) |
| 8 | ">5% vendor divergence triggers a staleness warning" | `copeca-cost-model.tend.html`, `pricing-drift-unchecked.tend.html` | `run.py:131-139` | **OVERCLAIMED** | computed then stored only; no CLI/report ever prints it (F-M2) |
| 9 | Pricing staleness warns at 30 days | metrics.md:98 | `orchestration/validation.py:18` (`check_pricing_staleness`) | **OVERCLAIMED** | function is **never called** anywhere in `src/` |
| 10 | Delta CI from a **paired** bootstrap | metrics.md:52 | `analysis/report.py:25-54,246-248`, `stats.py:146-187` | **HOLDS** | per-task deltas embed both modes → genuinely paired; *better* than docs |
| 11 | Bootstrap "resamples (cost,correct) pairs per mode" | metrics.md:46-48 | `report.py:246-248` | **STALE/wrong description** | code resamples per-task delta %, not per-run pairs (L1 — doc-only) |
| 12 | Correctness = required strings / `all_of` / forbidden / test-exit | README:64, `copeca-validate-tasks.tend.html` | `tasks/validator.py:25-112` | **HOLDS w/ HIGH caveats** | substring match is gameable (F-H2); forbidden logic bug (F-H3) |
| 13 | `all_of` requires ALL strings | README | `validator.py:72,80` | **HOLDS** | confirmed by repro |
| 14 | Contamination: "probe the model with the task ID, exclude if it reproduces gold" | README:124-127, `contamination-erodes-trust.tend.html` | `scripts/contamination_check.py` | **OVERCLAIMED / aspirational** | static 3-prefix blocklist, no model probe, not wired into any pipeline, 0/16 tasks match (F-H4) |
| 15 | `copeca verify --batch --scenario` proves no cherry-picking | README:67, `…integrity.tend.html`, `tend/overview.html` | `cli.py` verify cmd | **OVERCLAIMED/phantom** | `copeca verify --help` shows only `ARTIFACT`; `verify_batch()` exists but is unwired (F-H6) |
| 16 | Built-in parsers: stream_json, codex_json, generic | README:144, architecture.md:96-97, runner-configuration.md:83 | `runners/parsers/` | **OVERCLAIMED** | only `stream_json.py` exists (F-H6) |
| 17 | `package-data = schemas/*.json, tasks/**/*.yaml` | pyproject.toml:43 | `src/copeca/` layout | **OVERCLAIMED** | `src/copeca/schemas` absent; `src/copeca/tasks` has no yaml — wheel ships neither (F-H6) |
| 18 | Corpus "draws from six independent source families" (present tense, with table) | methodology.md:40-54 | `tasks/` | **OVERCLAIMED** | 16/16 tasks one family; table reads as current, not planned (F-H7) |
| 19 | "check-task CLI not yet implemented" | known-limitations.md | `cli.py:245`, `orchestration/check.py` | **STALE** | fully implemented (F-H5) |
| 20 | "matrix runner is sequential" | known-limitations.md:49 | `run.py:319` | **STALE** | `ThreadPoolExecutor` is live (F-H5) |
| 21 | "`test_command_passed` always None" | known-limitations.md | `run.py:75-114` | **STALE** | real subprocess grading wired (F-H5) |
| 22 | "workers are repo-affine", "two workers never share a worktree" | architecture.md:232,244 | `repos/manager.py`, `run.py:319` | **OVERCLAIMED** | worktree path keyed by repo only; flat pool; TOCTOU (F-M3) |
| 23 | `mode.setup` runs setup commands | (mode mechanism) | `orchestration/state.py:99-108` | **HOLDS but unsafe** | `shell=True` on scenario-authored strings (F-M4) |
| 24 | i.i.d. / small-N bootstrap caveat | known-limitations.md | — | **HOLDS** | honest disclosure |
| 25 | All 7 CLI subcommands (init/run/analyze/verify/validate/list/check-task) | README | `cli.py` | **HOLDS** | all exist; `--help` verified |

---

## 2. Findings, ranked by severity

Effort: **S** = a few lines/<1h · **M** = a module/a few hours · **L** = design + multi-file. ✓ = proven by a runnable repro I executed.

### CRITICAL

**F-C1 — The headline cost-per-correct number inverts under failure. ✓**
A mode that answers *everything wrong* renders as `$0.0000` — the cheapest possible — and produces a **−100% "improvement"** with a tight CI.
- Claim violated: the entire premise that cost-per-correct ranks tools fairly.
- Evidence: `stats.py:79-80` (`if correct_count == 0: return 0.0`); `report.py:225-227` (CPC table), `report.py:237-258` (headline delta), `report.py:49-52` (per-task deltas: 0-correct tasks contribute −100%).
- Repro output (mine): experimental mode 0/2 correct, spent 5× → report prints `experimental | $0.0000` and `**Delta:** experimental is -100.0% lower than baseline [95% CI: -100.0%, -100.0%]`. The only place the failure shows is a separate "Corrections Summary" (0.0%) the headline reader skips.
- Why it matters: this is the exact failure mode copeca exists to prevent — a tool that makes an agent *dumber but cheaper-looking* would be reported as a win. The seeded "NaN" hypothesis was a red herring; the truth is worse, because there's no NaN to alert anyone.
- Minimal fix (**M**): define cost-per-correct as **undefined/∞** when `correct_count == 0`; render `n/a (0 correct)` in tables; exclude 0-correct cells from the delta and the bootstrap; never emit a negative delta sourced from a zero denominator. Add accuracy as a co-headline so cost can never be read without correctness.
- tend to reconcile: `copeca-analysis-reporting.tend.html`, `accuracy-blind-claims.tend.html`.

**F-C2 — The "tamper-proof hash chain" is a self-hash; forging a passing artifact takes seconds. ✓**
- Claim violated: README:67 / index.html / `copeca-artifact-integrity.tend.html` — "SHA-256 hash chains" that "prove nothing was cherry-picked."
- Evidence: `artifact.py:71-94` computes `content_hash = sha256(concat(sorted per-file sha256s))` and stores it **inside the same zip**; `verification.py:74-102` recomputes the identical value from the zip's own bytes and compares. No signature, no external anchor, no actual chain linking artifacts.
- Repro output (mine, re-running the sub-agent's script): build authentic artifact → `verify valid=True`; edit `result.json` (`correct False→True`, `cost 0.031→0.001`), recompute hashes, rewrite `manifest.json`, rezip → **`FORGED verify: valid=True, 'Artifact valid: content_hash matches all files'`**.
- Secondary: `verify_batch` (`verification.py:155-163`) detects omission only as `max(expected − actual_count, 0)` — a **count**, requiring you to possess the scenario, and blind to "re-ran until favorable, shipped the good one." Compounding: filenames are `{task}__{mode}__{model}.copeca.zip` (`artifact.py:48`) with **no repetition index**, so reps silently overwrite — 12 expected runs can only ever produce 4 files.
- Minimal fix: (S) rename the claim to "integrity manifest" (detects accidental corruption, not adversarial tampering). (L) for real tamper-evidence: detached signature over `content_hash`, and/or publish hashes to an external append-only log; add a per-rep filename index and make `verify_batch` compare expected-vs-actual by identity tuple, not a count.
- tend: `copeca-artifact-integrity.tend.html`, `no-verifiable-results.tend.html`.

**F-C3 — The "provably clean" baseline inherits the full ambient environment; the isolation code is dead. ✓**
- Claim violated: README:108-109 / methodology.md:79 / architecture.md:21 — "provably clean baseline", "each arm provisioned with its own env."
- Evidence: `runners/subprocess.py:33` — `env = {k:v for k,v in os.environ.items() if k != "CLAUDECODE"}` is the *only* env handed to `Popen`. `orchestration/state.py:27-81` `provision_arm` (which would build per-arm env/config-dir/wrapper) has **zero callers in `src/copeca/`** (grep confirms). So any globally-configured agent hook, MCP server, proxy, or `CLAUDE_*`/config-dir var leaks into the baseline, *and* an experimental mode's declared `mode.env` never reaches the subprocess either.
- Repro (sub-agent, code-confirmed by me): child shows `ANTHROPIC_API_KEY`, a planted `CLAUDE_CODE_CUSTOM_HOOK`, and `MCP_SERVER_URL` all present; `provision_arm` not referenced in `run.py`.
- Note: this is also where Agent E was wrong (it claimed the baseline HOLDS by reasoning about what `provision_arm` *returns* without checking it's never called — the precise "dead feature sold as working" trap).
- Minimal fix (**M**): construct an allowlist env in `SubprocessRunner.run` (PATH/HOME/API-key only, plus mode-declared keys); wire `provision_arm` into `run_single`/`_run_one_work_item`; apply `ArmHarness.env` + `config_dir` to the child.
- tend: `copeca-mode-mechanism.tend.html`, `copeca-single-run.tend.html`.

### HIGH

**F-H1 — Three of the advertised adversarial flags can never fire. ✓** `run.py:147` calls `_compute_adversarial_flags(..., budget_usd=None, ...)` with comment "passed later" — there is no later; `run_single` has no budget param and `_run_one_work_item`/`run_matrix` never pass one, so `budget_exhausted` (`run.py:221-225`) is always `None`. `talkative_failure` and `tool_storm` are hardcoded `None` (`run.py:228-229`). `Scenario.budget_usd` exists but is **never enforced anywhere**. Report shows them as permanent 0.0%. Fix (**M**): thread+enforce `budget_usd`; implement the other two from available data or move them to known-limitations. tend: `copeca-scenario-matrix.tend.html`.

**F-H2 — String grading is keyword-stuffable and paraphrase-brittle. ✓** `validator.py:25-28` is `all(s.lower() in text.lower())` — case-insensitive substring, no word boundary, no semantics. Repro: a *factually wrong* answer that name-drops the required tokens scores **correct**; a *correct* answer using `regex_matcher` instead of `RegexMatcher` scores **wrong** (underscore breaks the substring). Fix (**S** disclose / **M** mitigate): document the limitation prominently; consider normalized/word-boundary matching and a contradiction guard. tend: `copeca-validate-tasks.tend.html`, `accuracy-blind-claims.tend.html`.

**F-H3 — `forbidden_strings` uses AND, so a partial refusal passes. ✓** `validator.py:62` = `not _check_strings(text, forbidden)` and `_check_strings` is `all(...)` (line 28), so the guard only trips when **every** forbidden phrase is present. Repro: `forbidden=["I cannot","unable to"]`, answer = "I cannot be certain, but the Matcher type is the answer" → **correct=True, "All checks passed."** 10 of 16 shipped tasks use 2-phrase forbidden lists. Fix (**S**, one line): `forbidden_passed = not any(s.lower() in text.lower() for s in forbidden)`. tend: `copeca-validate-tasks.tend.html`.

**F-H4 — Contamination defense is theater. ✓** README sells "probe the model with the task ID, exclude if it reproduces the gold solution." `scripts/contamination_check.py` makes **zero** model/network/subprocess calls — it's a static 3-prefix name blocklist (`swe-bench-verified`, `humaneval_`, `mbpp_`), none of which match any of the 16 tasks, and it is **not invoked** by `validate`/`run`/CI (only by its own unit test). Fix: implement the probe and wire it into `validate`, or relabel the README claim as "planned" in known-limitations. tend: `contamination-erodes-trust.tend.html`.

**F-H5 — `known-limitations.md` is stale in the under-claiming direction (3 false limitations). ✓** It says check-task is unimplemented (`cli.py:245` implements it), the matrix is sequential (`run.py:319` `ThreadPoolExecutor`), and `test_command_passed` is always None (`run.py:75-114` runs it). For a project whose credibility rests on honesty, its own honesty doc being wrong is its own finding. Fix (**S**): rewrite/remove the three sections.

**F-H6 — Declared-but-absent features (phantom surface).** `copeca verify --batch --scenario` (README/tend) — the CLI exposes only `verify ARTIFACT`. `codex_json`/`generic` parsers (README/architecture/runner-configuration) — only `stream_json.py` exists. `pyproject.toml:43` `package-data` globs at `src/copeca/schemas` (absent) and `src/copeca/tasks` (no yaml) — a built wheel ships neither schemas nor tasks, so `copeca validate` on a pip-installed copy likely can't find its schema. Fix (**S–M**): implement or delete each claim; fix packaging (move `schemas/`+`tasks/` under the package or use `MANIFEST.in`/`include_package_data`); add a wheel-install smoke test.

**F-H7 — Six-source-family governance presented as current.** `methodology.md:40-54` shows a multi-family governance table in present tense; reality is 16 tasks from one family (`copeca validate tasks/` → 16). Fix (**S**): mark planned / change tense.

### MEDIUM

**F-M1 — `token_snowball` formula ≠ docs and is not configurable. ✓** `run.py:242` hardcodes `> avg_first * 3`; metrics.md:111 documents `num_turns × avg × factor` and metrics.md:117 says "all thresholds configurable" (no Scenario field exists). Fix (S–M): align code↔doc; add `Scenario.adversarial_thresholds` if "configurable" is to be true.

**F-M2 — The one real cost safeguard is invisible.** The >5% vendor-divergence check (`run.py:131-139`) is genuinely sound but only stored in the record — no `typer.echo`, no report row. A safeguard nobody sees can't build trust. Fix (S): echo to stderr + add a report line. tend: `pricing-drift-unchecked.tend.html`.

**F-M3 — Concurrency TOCTOU under `max_workers>1`.** `repos/manager.py` builds the worktree path from `repo_key` only (not mode×task×rep); `run.py:319` runs a shared pool with no lock around check→prune→add. Two workers on the same repo collide; `reset` can clobber a sibling. Contradicts architecture.md's "repo-affine"/"never share a worktree." Fix (M): key worktrees per work-item (or UUID) + lock the prune+add.

**F-M4 — `mode.setup` shell injection.** `state.py:102-108` runs each scenario-authored setup string via `subprocess.run(cmd, shell=True)`. Contributor-authored, so trust-by-merge, but the safe argv pattern is already used for `test_command` (`run.py:80`) — setup should match. Fix (S): argv lists, drop `shell=True`.

**F-M5 — "Computed, not trusted" still trusts self-reported token counts.** Cost is recomputed from `parsed.total_*_tokens` (`run.py:122-128`) — vendor stdout, no transcript re-tokenization. The independence is overstated and the limitation is undisclosed. Fix (S): disclose in known-limitations (real fix = re-tokenize transcripts, an Improvement).

**F-M6 — Edit-task required/forbidden strings are silently ignored.** `validator.py:95-112` computes them into the detail but only `test_command_passed` decides `correct`. Undocumented. Fix (S): document, or also enforce forbidden on edit tasks.

**F-M7 — Neutrality.** A benchmark positioned as "neutral" ships five mode YAMLs named after specific third-party products and names external products in the README modes table and several docs; four in-source comments attribute the code's origin to a sister project. (I am deliberately not transcribing the product names here, per the engagement's no-new-attribution rule — the file:line inventory is in `claims.md`.) Angle: neutrality optics, possible trademark/attribution exposure, and a contamination vector (shipping a competitor's config). Fix (M): rename shipped modes generically (e.g. `indexed-search`, `gateway`), move named examples to user-facing docs, strip origin comments.

### LOW

- **L1** metrics.md's bootstrap *description* is wrong even though the code is sound/paired — fix the prose (S). Important framing: this is a doc bug, **not** a statistics bug; do not "fix" the working code.
- **L2** Hardcoded `copeca_version = "0.1.0"` in `run.py:184` and `artifact.py:84` will drift on bump → use `importlib.metadata` (S).
- **L3** `.venv` not gitignored (pattern vs symlink) → `git add .` would stage it (S).
- **L4** No decompressed-size cap in `verification.py:66` (`zf.read`) → zip-bomb OOM on `copeca verify` of an untrusted artifact (S).

---

## 3. What is genuinely good (verified, not manufactured)

- **`runners/cost.py:7-31` is an exemplary pure function** — deterministic, no I/O, formula matches the docs exactly. SUPER-compliant.
- **No NaN/inf can propagate** — guards at `stats.py:79`, `report.py:51`, `compare.py:56`. (But the chosen `0.0` sentinel is the *source* of F-C1 — the absence of NaN is what makes the inversion silent.)
- **The delta CI is genuinely paired** at the task level (`report.py:25-54,246-248`) — each resampled unit is a per-task delta embedding both modes. This is *sounder* than the per-run procedure metrics.md describes; only the documentation needs fixing.
- **The edit-task / check-task pipeline is real** (`orchestration/check.py`) — "passes on clean code, fails after mutation" with worktree isolation and cleanup; the mutation engine handles all action types with error-before-apply semantics.
- **`test_command` grading uses safe argv** (`run.py:80`, list, `shell=False`) — contrast the unsafe `mode.setup`.
- **`all_of` correctly requires ALL** strings.
- **Mode isolation is sound in *intent*** (separate config dir + env + worktree) — the design is right; it's just not wired (F-C3).

---

## 4. Top 5 credibility-restoring fixes

1. **Stop the metric from inverting (F-C1).** Until 0-correct → undefined (not `$0.0000`/−100%), every headline can be gamed by a tool that trades accuracy for cost. This is #1 because it's the project's reason to exist.
2. **Stop calling the artifact tamper-proof (F-C2).** Minimum: rename to "integrity manifest." Real: sign + externally anchor the `content_hash`, add per-rep filenames, identity-based `verify_batch`.
3. **Make the baseline actually clean (F-C3).** Allowlist the child env and wire `provision_arm`, or drop the word "provably."
4. **Repair grading honesty (F-H2/H3/H5).** One-line `forbidden` fix, an explicit "string-match is gameable" disclosure, and delete the three stale known-limitations.
5. **Reconcile every sold-but-dead feature (F-H1/H4/H6/H7).** For each of: 3 dead flags, contamination probe, `verify --batch`, the two phantom parsers, the six-family table — either implement it or move it to known-limitations. A benchmark may not ship aspirational present tense.

---

## 5. Improvements (beyond removing theater)

- **Signed + externally anchored artifacts**, and a real cross-artifact Merkle chain so a *batch* is verifiable as a set (delivers what "hash chain… nothing cherry-picked" promised).
- **Transcript re-tokenization** to retire the self-reported-token assumption (closes F-M5 at the root).
- **Thread and enforce `budget_usd`** — abort/penalize on exceed (revives `budget_exhausted` and a sold safety rail).
- **Document the paired bootstrap correctly**; consider BCa intervals for N=16.
- **Per-work-item worktree isolation + locks** (or a process pool with per-worker bare clones) to make concurrency safe, not just present.
- **Wheel-install CI smoke**: build the wheel, install into a clean venv, run `init/validate/list/verify` — would have caught F-H6 packaging drift immediately.
- **A "tend 1:1" reconciliation pass**: every code finding above lists its feature's `*.tend.html`; refresh narrative + audit badges so green prose doesn't certify stale behavior.

---

## 6. Recommended way forward (sequenced)

**Phase 0 — truth-fixes (hours, no design needed).** The cheap edits that stop active misrepresentation: `forbidden` one-liner (F-H3); metric-inversion guard + co-headline accuracy (F-C1); delete/relabel the three stale known-limitations (F-H5), the phantom `verify --batch`/parser/governance claims (F-H6/H7), and rename the integrity claim (F-C2 text). Per copeca's own engineering.md rule, each lands as a **failing test first**.

**Phase 1 — isolation & visibility (1–2 days).** Wire `provision_arm` + allowlist env (F-C3); surface the divergence warning (F-M2); per-rep artifact filenames + identity `verify_batch` (F-C2 mechanics); fix packaging + wheel smoke (F-H6).

**Phase 2 — design-level.** Signed/anchored artifacts; thread+enforce budget (F-H1); implement-or-formally-defer talkative/tool_storm/contamination (F-H1/H4); concurrency isolation (F-M3); neutrality rename (F-M7).

I can produce the Phase 0 failing tests + minimal patches on request — I have not modified anything in the repo beyond throwaway repros under `/tmp/scratch_*`, and I restored `git status` to clean. Per the engagement constraints I'll confirm before touching repo files.

*Sub-reports with full per-dimension detail: `/tmp/copeca_audit_reports/{integrity,stats,orchestration,grading,claims}.md`.*
