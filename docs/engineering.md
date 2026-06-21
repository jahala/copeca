# Engineering handbook

How we build copeca. `agent-bench-plan.md` says what we're building and why; this
says how we write, test, review, and ship. Rules that can be machine-enforced are
config, not prose — this document tells you which config enforces each rule.
Everything else here is the team agreement.

## 1. Code philosophy

Copeca follows S.U.P.E.R. — the same discipline encoded in the plan's design
decisions (§10):

1. **Side effects at the edges.** I/O (subprocess, git, filesystem, network) lives
   in `runners/`, `repos/`, and `results/`. Config, tasks, analysis, and
   orchestration compute on data. A function that needs repo state takes a `Path`,
   not a clone.
2. **Uncoupled logic.** Dependencies are parameters, never globals or singletons.
   A function's signature is its complete contract.
3. **Pure & total functions.** Deterministic, handle every input. No hidden throws.
   If something can fail, the return type says so.
4. **Explicit data flow.** Linear pipelines over mutation chains. You can trace
   data from input to output by reading the code top to bottom.
5. **Replaceable by value.** Any function call can be swapped with its return
   value without changing behaviour.

Additional constraints specific to copeca:

6. **Data-only, not code.** Tasks are YAML, not Python classes. If correctness
   can't be expressed as strings + test commands, the task may not be objectively
   gradeable (design decision #15).
7. **One execution path.** No `if docker:`, no `if sandbox:`. The environment is
   declared and verified — provisioning is the operator's choice (design decision
   #17).
8. **Smallest reasonable change.** Match the style of surrounding code. No
   drive-by refactors inside feature PRs.

## 2. Python rules

Enforced by `pyproject.toml` (ruff, mypy, pytest) — the configs are the source of
truth; highlights:

- **Python ≥ 3.11** (3.10 EOL Oct 2026). Test on 3.11, 3.12, and 3.13 in CI.
- **`ruff`** for linting + formatting. No separate flake8/isort/black — ruff owns
  all three. `ruff format` is the one formatter; nobody argues about it in review.
- **`mypy --strict`** for type checking. No `Any` without a comment justifying it.
  Prefer `Protocol` and structural subtyping over ABCs for the runner/parser
  abstractions.
- **`pydantic` v2** for config models (`src/copeca/config/models.py`).
  `jsonschema` for user-facing YAML validation. The split is deliberate: Pydantic
  gives internal type safety; JSON Schema gives human-readable user errors (design
  decision #4).
- **`typer`** for CLI. Subcommands are one file per command family
  (`run`, `analyze`, `validate`, `verify`). Shared argument parsing lives in
  `cli.py`.
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes,
  `SCREAMING_SNAKE` for module-level constants. Files: `snake_case.py`.
- **No `print`** outside CLI output. Logging through the standard `logging`
  module. Verbose output behind `--verbose`.

## 3. CLI design rules

Copeca's CLI IS its API. There is no separate HTTP surface.

- **Subcommands are verbs:** `run`, `analyze`, `compare`, `verify`, `validate`,
  `check-task`, `inspect`, `init`, `list`. Each maps to a typer command group.
- **`--output-format`** where machine-readable output exists (`json`, `jsonl`,
  `markdown`). Default is human-readable terminal output.
- **Exit codes are semantic:** 0 = success/clean, 1 = validation failure, 2 =
  runtime error, 3 = timeout. Documented in `--help` for every command.
- **`--verbose`** adds progress lines and timing to stderr. Never to stdout (stdout
  is for the JSONL pipeline).
- **`--help`** on every command. Examples in the help text match the README's
  quick-start.

## 4. MCP & subprocess rules

Copeca spawns CLI agents as subprocesses. This is the runner abstraction:

- **Every runner gets process-group isolation.** Timeout = SIGKILL to the entire
  process group, not just the parent. No orphaned children.
- **Environment is explicit per arm.** `env` in the mode YAML is the full override
  — copeca never inherits the host's ambient `ANTHROPIC_BASE_URL` or similar. The
  baseline arm gets a clean env.
- **Config-dir isolation.** Each arm gets its own agent config directory (for hooks,
  `settings.json` overlays). The baseline arm gets an empty directory.
- **MCP tools are loaded from `mcp_config` in the mode YAML.** Copeca does not
  depend on any MCP server being installed — the runner handles missing-tool
  failures gracefully.
- **No copeca MCP server.** Copeca is a CLI benchmark, not an MCP tool itself.
  The `mcp__tend__*` tools used during planning are for the tend feature-mapping
  workflow, not part of copeca's own surface.

## 5. Benchmark correctness rules

These are the invariants that make copeca numbers trustworthy:

- **Every edit task must pass `check-task` before entering the corpus.**
  The test must pass on clean code and fail on mutated code. A task that passes
  on mutated code has a weak test and is excluded (SWE-bench's #1 failure mode,
  which copeca was designed to prevent).
- **Contamination provenance check before corpus publication.** `copeca validate`
  checks every task's `source:` field against a blocklist of known-contaminated
  source benchmarks (SWE-bench Verified, RepoBench, ClassEval, DevEval, CoderEval).
  A task from any blocked source is rejected. This is a static check — no model
  calls, no network. A planned authoring-time option will additionally probe a live
  model with the task ID and exclude if it reproduces the gold solution; that
  feature requires an API key and is not yet shipped.
- **Cost: the bill is the headline, the model is the yardstick.** `total_cost_usd`
  is the vendor's billed cost when the runner reports it (`cost_source = "vendor"`) —
  it captures cache TTL, tier, and discounts that token counts cannot. The computed
  cost (`computed_cost_usd = Σ tokens × pricing`) is always recorded as the
  reproducible, provider-neutral cross-check; a >5% divergence flags possible
  misreporting. When no vendor cost is reported, computed is the fallback
  (`cost_source = "modeled"`).
- **Reproducibility over convenience.** Every run records the repo commit SHA,
  verified toolchain versions, runner config with pricing, and task definition.
  A `.copeca` zip (opt-in via `--artifacts`) carries all of this with an
  integrity manifest (a SHA-256 hash of every file). The manifest detects
  accidental corruption but is not tamper-proof on its own; for real
  tamper-evidence, `--sign-key` writes a detached Ed25519 signature over the
  content hash that `verify --pubkey` checks (a tampered, manifest-recomputed
  artifact fails). External transparency-log anchoring is planned.
- **No network during measurement.** The agent may use the network (it's a real
  coding agent), but copeca itself does not. Repos are pre-cloned. Pricing tables
  are local YAML. Schemas are local JSON.

## 6. Testing conventions

- **Failing test first.** For features and for bug fixes. No exceptions without
  an explicit note in the PR.
- **Pytest** is the test runner. Naming: `test_{module}_{scenario}.py`.
  Arrange-Act-Assert with blank-line separation.
- **Test output must be pristine.** Zero warnings, zero console noise, no skipped
  tests without a linked issue.
- **No mocking our own logic.** Mock only at true external boundaries: the
  subprocess call (mock the CLI agent's stdout), the network (mock git clone).
  The parser, validator, cost model, and orchestrator are tested with real
  fixtures.
- **Fixture files** live in `tests/fixtures/`: sample stream-json output,
  valid/invalid task YAML, sample JSONL records. Every fixture is synthetic and
  documented with one line saying what behaviour it pins.
- **Integration tests** for the full single-run pipeline (`test_orchestrator.py`)
  use a real pinned repo at a known commit. These are slower — run them in CI,
  not on every local save.
- **No coverage-percentage gate.** Reviewers judge whether the behaviour is
  pinned, not whether a line was hit.

## 7. Git workflow

- **Trunk-based:** short-lived feature branches off `main`, merged via PR. `main`
  is always in a state where `copeca validate tasks/` passes.
- **Branch names:** `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:`, `test:`,
  `refactor:`). Imperative mood, body explains *why*.
- **PRs are small.** One logical change per PR. The migration script, task YAML
  files, and generated artifacts are reviewed but not hand-authored.
- **Rebase before merge.** Squash-merge with a clean conventional title. Never
  force-push `main`.

## 8. Review checklist

Reviewer checks (CI enforces where possible):

1. **Tests exist, failed first, and pin behaviour.** Not implementation details.
2. **Boundaries respected.** I/O stays in `runners/`, `repos/`, `results/`. Config
   and analysis compute on data.
3. **Correctness invariants hold.** Edit tasks pass `check-task`. Cost is computed,
   not trusted. The integrity manifest covers every artifact file.
4. **No task corpus contamination.** New tasks carry a `source:` field with license
   and commit. Tasks from blocked sources (SWE-bench Verified, RepoBench, ClassEval,
   DevEval, CoderEval) are rejected before review.
5. **Schema validation.** `copeca validate tasks/` passes. New fields are in
   `src/copeca/data/schemas/task.schema.json` before they appear in any task YAML.
6. **Documentation.** `--help` text is updated. The README's quick-start still works
   from a clean `copeca init`. Any new CLI flag appears in the docs.
7. **tend updated.** If a feature's spec-of-truth changed (slots, checks, steps),
   the feature polyglot in `docs/tend/features/` is updated.

## 9. Dependency policy

- **Prefer the standard library.** A new dependency needs a one-paragraph
  justification: what it replaces, license, maintenance signal.
- **Licenses:** MIT, Apache-2.0, BSD, ISC are fine. No copyleft (GPL/AGPL).
- **Core dependencies** (typer, pyyaml, jsonschema, pydantic, cryptography, ruff,
  mypy, pytest) are pinned in `pyproject.toml`. Minor/patch updates via Dependabot.
- **`cryptography`** provides the Ed25519 detached signatures behind artifact
  tamper-evidence (`results/signing.py`). It replaces hand-rolling asymmetric
  crypto — which we will not do. Apache-2.0 / BSD dual-licensed, the de facto
  standard Python crypto library (PyCA), actively maintained. It ships a small
  compiled component (via `cffi`); this is the one non-`git` binary dependency
  and is justified because correct signing must not be home-grown.
- **No heavy ML dependencies.** Copeca is a CLI benchmark, not an inference
  engine. The system binary dependency is `git`; `cryptography` is the only
  compiled Python dependency.
- **SBOM** generation via `pip-audit` + `cyclonedx-bom` in CI — deferred until
  there's a release artifact to scan against.

## 10. Secrets & config

- **No secrets in the repo, ever.** API keys for benchmark runs come from
  environment variables, never from committed config.
- **`repos.yaml`** is the canonical repo registry. It contains public repo URLs
  and commit hashes — no credentials.
- **Runner pricing YAML** is public data. The `updated` field tracks freshness.
  Staleness warnings fire at >30 days.

## 11. tend feedback loop

Copeca's own features are tracked in tend. The workflow:

1. Features are brainstormed as tend polyglots with slots + checks anchored to
   persona jobs.
2. `tend plan` breaks features into test-first implementation steps.
3. `tend update_feature` records step status as work progresses.
4. `tend audit` verifies checks against real evidence before `status: verified`.
5. The garden at `docs/tend/overview.html` carries the project bet and narrative.

Tend is not a gate on shipping — it's the map of what's been built and what's
been verified. A PR that implements a step should update the step's status.

## 12. Where everything is documented

| Agreement | Lives in | Enforced by |
|---|---|---|
| What we're building + why | `README.md` + `docs/methodology.md` | Review |
| How we build (this handbook) | `docs/engineering.md` | Review |
| Task schema | `src/copeca/data/schemas/task.schema.json` | `copeca validate` |
| Runner config | `src/copeca/data/defaults/runners/*.yaml` | validated by `RunnerConfig` (Pydantic) at load via `load_runner` |
| Repo registry | `repos.yaml` | `copeca validate` (cross-document) |
| Cost model | `src/copeca/data/defaults/runners/*.yaml` | Staleness warnings |
| Lint/format/types | `pyproject.toml` (ruff, mypy) | CI |
| Test policy | §6 here | CI + review |
| Decisions + rationale | `docs/methodology.md`, `docs/known-limitations.md` | Review |
| Agent briefing | `.claude/CLAUDE.md` | Read at session start |
| Tend feature map | `docs/tend/` | `tend validate` |
| License | `LICENSE` (MIT) | CI (license-check) |
