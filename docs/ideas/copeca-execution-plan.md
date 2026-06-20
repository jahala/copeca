# Copeca — Execution Plan & tilth Provenance Map

> Companion to `agent-bench-plan.md`. Maps every copeca component to its tilth
> origin (copy / adapt / build / drop) and sequences the build.

Source of reuse: `github.com/jahala/tilth/benchmark/` — `run.py`, `config.py`,
`parse.py`, `analyze.py`, `analyze_exploration.py`, `compare_versions.py`,
`tasks/`, `fixtures/`.

Legend:
- **COPY** — lift near-verbatim (rename only)
- **ADAPT** — substantial reuse, modify for generalization
- **BUILD** — new, no tilth equivalent
- **DROP** — not needed in copeca

---

## 1. Provenance Map

### Parsers & result model — *the biggest copy win*

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `runners/parsers/` `Turn`, `ToolCall`, `RunResult` | `parse.py` dataclasses | **COPY** | Clean, reusable as-is. Add fields copeca needs (adversarial inputs). |
| `runners/parsers/stream_json.py` | `parse.py: parse_stream_json` | **ADAPT** ~85% | Keep token/turn/tool extraction. Remove dependence on vendor `total_cost_usd` (copeca computes cost). |
| `runners/parsers/codex_json.py` | `parse.py: parse_codex_json` | **ADAPT** ~85% | Already computes cost from tokens × a pricing table — *exactly* copeca's model. Move the pricing table into runner YAML. |
| `runners/parsers/generic.py` | — | **BUILD** | JSONPath-configurable parser. No tilth equivalent. |
| `runners/base.py` (parser ABC) | parsers are bare functions in tilth | **BUILD** (thin) | Abstract `BaseParser.parse()`. |
| cost computation (tokens × pricing) | `analyze.py: PRICING` + `compute_cost_breakdown`; `parse_codex_json` | **ADAPT** | Formula exists verbatim (`tokens × rate / 1e6`). Generalize to read `runner.pricing[model]`. |
| `runners/base.py` invoke resolution | `run.py: run_single` (claude/codex `if` branches) | **ADAPT** | tilth hardcodes two branches; copeca makes it `arg_map`/`invoke_template`-driven. |
| `runners/subprocess.py` | `run.py: run_single` subprocess block | **ADAPT** | Copy the subprocess shell + the `env` minus `CLAUDECODE` trick. Rebuild command construction as generic. Add process-group SIGKILL (**BUILD**). |

### Repo management

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `repos/manager.py` clone/pin | `fixtures/setup_repos.py: setup_repo` | **ADAPT** | Clone `--no-checkout`, checkout pinned SHA, re-clone if wrong — reusable. |
| `repos/manager.py` reset | `fixtures/reset.py: ensure_repo_clean` | **ADAPT** | `git status --porcelain` → `checkout --force` + `clean -fd`. Maps directly to copeca reset semantics. |
| worktree lifecycle | — (tilth uses one clone) | **BUILD** | Bare clone + per-repo worktree pool. |
| toolchain verification | — | **BUILD** | `rustc --version` vs declared; abort on mismatch. |
| `setup_command` execution | — (tilth relies on system toolchain) | **BUILD** (small) | Run once per worktree. |

### Mutations & correctness

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `tasks/mutations.py` find/replace + commit | `tasks/base.py: apply_mutations` | **ADAPT** | Core find/replace + git commit is reusable. |
| `tasks/mutations.py` delete/insert_after/create/occurrence | — | **BUILD** | New action types + occurrence indexing + unmatched-find abort. |
| `tasks/validator.py` strings + test_command + git diff | `tasks/base.py: check_correctness` | **ADAPT** ~70% | required/forbidden matching, `test_command` run, diff inspection — reusable. |
| `tasks/validator.py` `all_of` + `correct` derivation | — | **BUILD** | New completeness field + the per-type `correct` rule. |
| mutation-validity deep check (`check-task`) | — | **BUILD** | pass-on-clean / fail-on-mutated. tilth never verified its mutations bite. |
| `Mutation`, `GroundTruth` dataclasses | `tasks/base.py` | **ADAPT** | Add `action`, `occurrence`, `content`, `all_of`. |

### Config, schema, task data

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `config/models.py` (pydantic) | `config.py` dataclasses (RepoConfig, ModeConfig) | **BUILD** | Structure informs; pydantic+YAML is new. |
| `config/loader.py` (YAML + jsonschema) | — (tilth imports Python) | **BUILD** | |
| `schemas/*.json` | — | **BUILD** | |
| `tasks/loader.py` (YAML discovery) | `tasks/__init__.py: TASKS` dict | **BUILD** | |
| `tasks/**/*.yaml` (~85 tasks) | `tasks/*.py` task classes + independent sources | **MIGRATE + AUTHOR** | ~35 from tilth (migration); ~50 authored fresh from SWE-QA, RepoQA/SCBench, Long Code Arena source families. The tilth migration script handles the first batch; the rest are original YAML. |
| `repos.yaml` | `config.py: REPOS` | **COPY data** + **BUILD** | URLs + commits copy verbatim; `toolchain` + `setup_command` are new per-repo fields. |
| `defaults/runners/{claude,codex}.yaml` | `config.py` RUNNERS + run_single args | **ADAPT** | Translate hardcoded CLI args into declarative YAML. |
| `defaults/modes/*.yaml` | `config.py: MODES` + `fixtures/tilth_mcp.json` | **ADAPT** | baseline/tilth/tilth_forced → mode YAMLs. MCP config structure reusable. |
| default `system_prompt` | `config.py: SYSTEM_PROMPT` | **COPY data** | |

### Orchestration

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `orchestration/run.py` single-run | `run.py: run_single` | **ADAPT** | The run-one-combination logic. |
| `orchestration/run.py` matrix loop | `run.py: main` (tasks×modes×models×reps) | **ADAPT** | Sequential loop structure reuses; reset-between-runs logic reuses. |
| worker pool (concurrency) | — (tilth is sequential) | **BUILD** | |
| `orchestration/state.py` | `fixtures/reset.py` (reset only) | **BUILD** | Worktree state machine; reset logic adapted. |
| `orchestration/validation.py` (compat warnings) | — | **BUILD** | task↔runner, mode↔runner checks. |

### Results & integrity

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `results/writer.py` (JSONL) | `run.py` inline `f.write(json.dumps(...))` | **ADAPT** | Extract the record shape into a module; enrich fields. |
| `results/reader.py` | `analyze.py: load_results` | **ADAPT** | |
| `results/artifact.py` (.copeca zip) | — | **BUILD** | Hashing, manifest, post_mutation.diff. |
| `results/verification.py` (verify + batch) | — | **BUILD** | SHA-256 chain + scenario completeness. |

### Analysis & reporting — *the other big copy win*

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `analysis/stats.py` | `analyze.py: compute_stats, ascii_sparkline, format_delta, find_median_run, merge_tool_calls, group_by` | **ADAPT** | Large direct reuse. |
| bootstrap 95% CI | — (tilth has median/mean/stdev) | **BUILD** | |
| `analysis/report.py` | `analyze.py: generate_report, compute_cost_breakdown, format_*` | **ADAPT** ~75% | Per-task tables, cost breakdown, sparklines, cost-per-correct math all present. Add delta-headline + adversarial summary. |
| `analysis/compare.py` | `compare_versions.py` | **ADAPT** | |
| adversarial flags | `analyze_exploration.py` (tool ratios) + `parse.py: tool_call_counts` | **BUILD** + reuse inputs | Flag *definitions* are new; tool-counting/per-turn inputs reuse. |

### CLI & migration

| copeca | tilth source | Class | Notes |
|--------|-------------|-------|-------|
| `cli.py` (Typer subcommands) | per-script `argparse` `main()` | **BUILD** | `parse_comma_list` ADAPT from `run.py`. |
| `scripts/migrate_from_tilth.py` | — | **BUILD** (keystone) | Imports tilth's `TASKS` + `REPOS`, emits task YAMLs + repos.yaml. |

### Dropped

| tilth | Why dropped |
|-------|-------------|
| `fixtures/setup.py` (synthetic repo generator) | No synthetic tasks (resolved decision #5). |
| 5 synthetic tasks: `find_definition`, `read_large_file`, `edit_task`, `codebase_navigation`, `markdown_section` | Target the synthetic repo. **Correction: ~35 real-repo tasks migrate, not 40.** |

---

## 2. The Three Levers

**Where tilth gives you the most for free:**
1. **Parsers + result model** (`parse.py`) — ~85% reusable. Token extraction, turn structure, tool counting, and the codex cost-from-tokens formula are already exactly copeca's model.
2. **Analysis/reporting** (`analyze.py`) — ~75% reusable. The cost-per-correct math, per-task comparison tables, cost breakdown, and sparklines are done.
3. **Repo clone/reset** (`fixtures/`) — the git plumbing transfers directly.

**Where the genuinely new work is (BUILD-heavy):**
1. **Config layer** — YAML + JSON Schema + pydantic. tilth had none (Python classes).
2. **Concurrency + worktrees** — tilth is single-clone sequential.
3. **Integrity** — artifacts, hashing, verification, batch completeness. Entirely new.
4. **Toolchain verification** + generic parser + scenario compat warnings.
5. **Mutation-validity `check-task`** — the correctness guard tilth lacks.

**The keystone:** `migrate_from_tilth.py`. It unlocks the tilth task *data* (~35 tasks of prompts, ground truth, mutations, test commands) without retyping. Build it early in Phase 1a so the task format is validated against real tasks immediately. The remaining ~50 tasks are authored fresh from independent source families (SWE-QA, RepoQA/SCBench, Long Code Arena) — see plan §3 Corpus Design.

---

## 3. Execution Sequence

### Phase 1a — Config + Tasks + Migration
1. Scaffold `pyproject.toml`, package skeleton, Typer entry point.
2. **BUILD** `config/models.py` (pydantic) + `schemas/task.schema.json`.
3. **BUILD** `config/loader.py` (YAML + jsonschema).
4. **BUILD** `scripts/migrate_from_tilth.py` — vendor or check out tilth's `benchmark/tasks/` + `config.py`; import `TASKS`/`REPOS`; emit task YAMLs + `repos.yaml`.
5. Run migration → ~35 task YAMLs. Hand-add `toolchain` + `setup_command` to `repos.yaml` (the only new repo data).
6. **BUILD** `tasks/loader.py`; wire `copeca validate` + `copeca list`.
7. Tests: `test_config_loader.py`.

**Gate:** `copeca validate tasks/` passes on all migrated tasks.

### Phase 1b — Single Run End-to-End
8. **COPY/ADAPT** `parse.py` dataclasses + `parse_stream_json` (strip vendor cost).
9. **BUILD** `runners/base.py` (parser ABC, invoke resolution, **ADAPT** cost-from-tokens).
10. **ADAPT** `runners/subprocess.py` from `run_single`.
11. **ADAPT** `repos/manager.py` from `setup_repos.py` + `reset.py`; **BUILD** worktree + toolchain verify + setup.
12. **ADAPT** `tasks/mutations.py` from `apply_mutations`; **BUILD** new actions.
13. **ADAPT** `tasks/validator.py` from `check_correctness`; **BUILD** `all_of` + `correct` rule + mutation-validity.
14. **ADAPT** `orchestration/run.py` (single combination) + `results/writer.py`.
15. **BUILD** `results/artifact.py` + `verification.py`.
16. Wire `copeca run --task`, `copeca check-task`, `copeca verify`.
17. Tests: validator, parsers (+ cost-from-tokens + vendor cross-check), artifact tamper.

**Gate:** one real task runs end-to-end, JSONL has computed cost, `check-task` proves an edit mutation bites, toolchain mismatch aborts.

### Phase 2 — Matrix + Concurrency
18. **ADAPT** matrix loop from `run.py: main`; **BUILD** worker pool.
19. **BUILD** `orchestration/state.py` (worktree lifecycle).
20. **BUILD** `orchestration/validation.py` (compat warnings).
21. Mode + scenario loading; `runner.schema.json`, `scenario.schema.json`.
22. **BUILD** batch completeness in `verification.py`; add `codex`/`opencode` runner YAMLs (**ADAPT**).

**Gate:** `copeca run scenarios/my.yaml` runs the full matrix in parallel; batch verify detects missing runs.

### Phase 3 — Analysis
23. **ADAPT** `analysis/stats.py` from `analyze.py`; **BUILD** bootstrap CI.
24. **ADAPT** `analysis/report.py` from `generate_report` (delta-headline + adversarial summary new).
25. **ADAPT** `analysis/compare.py` from `compare_versions.py`.
26. **BUILD** adversarial flag computation (reuse `tool_call_counts`).

**Gate:** report matches tilth's quality, headline is the delta + CI.

### Phase 4 — Full Migration, Docs, Polish
27. Migrate remaining tasks; run `check-task` over **all** edit tasks (catches any migration that lost meaning).
28. Docs (`task-authoring`, `runner-configuration`, `metrics`, `methodology`, `known-limitations`); `copeca init`; integration tests.

**Gate:** all ~85 tasks validate; edit tasks pass `check-task`; `copeca init` bootstraps a working suite.

---

## 4. Practical Notes

- **tilth code lives in another repo.** The migration script needs tilth's `benchmark/tasks/` + `config.py` importable — either `git clone` tilth alongside, or vendor a snapshot into `scripts/_tilth_snapshot/`. Pin the tilth commit you migrate from and record it in the migration output header (provenance).
- **Migrate a slice first (5–10 tasks), then the rest.** Phase 1a uses the slice to shake out the YAML schema before committing all 35; Phase 4 does the bulk once the format is frozen.
- **Pricing tables** in the runner YAMLs are the one piece of *data* that must be re-verified at build time (model IDs + rates drift) — the example values carried from tilth's `config.py`/`analyze.py` are illustrative.
