# Copeca — Architecture

How copeca is structured, why, and what must hold true regardless of implementation.
`engineering.md` says how we write code; `agent-bench-plan.md` says what we're
building. This document says how the pieces fit together, what depends on what,
where extension happens, and which invariants survive every change.

---

## 1. Copeca is a measurement instrument

Every architectural decision traces to this: copeca measures things. A measurement
instrument must be reproducible, verifiable, isolated, comparable, and extensible.
These five properties are the architectural invariants — if a change breaks any of
them, it's architecturally wrong regardless of implementation quality.

| Property | What it means | What enforces it |
|---|---|---|
| **Reproducible** | Same inputs → same outputs within stochastic bounds | Pinned commits, declared toolchains, per-arm isolation, `check-task` mutation validity |
| **Verifiable** | Outputs carry their own proof of integrity | `.copeca` zips carry a SHA-256 integrity manifest; `copeca verify` checks single-artifact integrity and `copeca verify --batch --scenario` checks completeness (all expected runs present); cryptographic signing and external anchoring are planned |
| **Isolated** | The instrument doesn't contaminate the measurement, and doesn't touch the host | Per-item independent clones; a private throwaway HOME per run (zero host-config footprint); strict-MCP + ambient-instruction neutralization; allow-listed child environment; a post-hoc trace gate that proves the baseline used no tool-under-test (§13) |
| **Comparable** | Numbers from different runs use the same methodology | Cost computed from tokens × one pricing source, same tasks/baseline/metric |
| **Extensible** | New runners, parsers, modes, tasks without changing the core | YAML-driven config, ABC-based port/adapter boundaries, invoke_template escape hatch |

These five constrain every design decision. When two values conflict (e.g.
isolation vs. simplicity — Docker is more isolated, git worktrees are simpler),
the one that better serves the invariants wins.

---

## 2. Layer architecture

Copeca follows a ports-and-adapters pattern. The dependency direction is strictly
inward: domain ← orchestration ← adapters. The CLI wires adapters to ports at
startup.

```
┌──────────────────────────────────────────────────────────────────┐
│ CLI (typer)                                                      │
│   cli.py — wires adapters to ports, dispatches subcommands      │
└──────────────────────┬───────────────────────────────────────────┘
                       │ depends on everything below
┌──────────────────────▼───────────────────────────────────────────┐
│ ORCHESTRATION (coordinates; holds no I/O of its own)             │
│   orchestration/run.py     — matrix loop + worker pool           │
│   orchestration/state.py   — per-arm harness provisioning (ArmHarness, provision_arm) │
│   orchestration/validation.py — compat warnings                 │
└──────┬──────────────────────────────────┬───────────────────────┘
       │ depends on domain + port interfaces
       │
┌──────▼──────────┐  ┌─────────────────────┐
│ DOMAIN (pure)   │  │ PORTS (ABCs /       │
│   config/       │  │   Protocols)         │
│   tasks/        │  │   runners/base.py    │
│   analysis/     │  │   runners/parsers/   │
│                 │  │     base.py          │
│ No imports from │  │   repos/manager.py   │
│ runners/,       │  │     (interface)      │
│ repos/, or      │  └─────────────────────┘
│ results/        │           ▲
└─────────────────┘           │ implements
                    ┌─────────┴─────────────┐
                    │ ADAPTERS (I/O)        │
                    │   runners/subprocess  │
                    │   runners/parsers/    │
                    │   repos/manager (git) │
                    │   results/writer      │
                    │   results/artifact    │
                    └───────────────────────┘
```

**Domain layer (pure computation, deterministic given inputs):**
- `config/models.py` — Pydantic dataclasses for Task, Runner, Mode, Scenario, Repo
- `config/loader.py` — YAML/JSON deserialization + jsonschema validation
- `tasks/validator.py` — correctness checking: takes (task, repo_path, agent_output),
  returns (correct, reason). Pure function — no subprocess, no git, no network.
- `tasks/mutations.py` — find/replace/delete/insert operations on file content.
  Pure string/file operations.
- `analysis/stats.py` — median, mean, stdev, bootstrapped CI on already-loaded
  JSONL data. Pure math.
- `analysis/report.py` — takes stats objects, produces markdown string. Pure text
  generation.

**Domain-layer rule:** No file in `config/`, `tasks/`, or `analysis/` may import
from `runners/`, `repos/`, `results/`, or `orchestration/`. This is enforceable
via architecture tests (import-linter or a simple grep in CI).

**Ports (abstract interfaces):**
- `runners/base.py:BaseRunner` — `run(command_spec) -> RunResult`
- `runners/parsers/base.py:BaseParser` — `parse(stdout: str) -> RunResult`
- `repos/manager.py:RepoManager` — `create_worktree(repo_key, commit, uri, worktree_id) -> Path`,
  `remove_worktree(clone_path) -> None`, `reset(worktree) -> None`, `setup(worktree, setup_command)`,
  `build_mutation_history(worktree, steps)`, `verify_toolchain(repo_key)`

**Adapters (concrete implementations):**
- `runners/subprocess.py:SubprocessRunner` — spawns CLI agent as subprocess
- `runners/parsers/stream_json.py` — built-in parser (Claude Code stream-json output)
- `repos/manager.py:GitWorktreeManager` — bare-cache + per-item independent clone lifecycle:
  `create_worktree` clones the bare cache with `--no-hardlinks` (independent object store,
  lockless concurrency); `remove_worktree` deletes the clone via `shutil.rmtree`

Additional parsers (for other CLI agents) are planned; the extension point is
`runners/parsers/base.py:BaseParser`.

The orchestration layer imports ports (ABCs), never adapters directly. The CLI
instantiates adapters based on runner config and injects them.

---

## 3. Domain model

The core entities and their cardinality:

```
Scenario 1──* Task       (one scenario references many tasks)
Scenario 1──* Mode        (one scenario references many modes)
Scenario 1──* Model       (one scenario references many models)
Model    *──1 Runner      (model_runner_map: each model maps to one runner)

Run = (Task, Mode, Model, Runner, repetition_index)
  → produces one Result (JSONL record)
  → optionally produces one Artifact (.copeca zip)

Report = aggregate of Results grouped by (Mode, Model) within a Scenario
```

**Key invariants in the domain model:**

- A Task is data, not code. Correctness is always strings + test_command —
  nothing else. If something needs custom code to grade, it isn't a copeca task.
- A Runner declares what it supports (`supported_events`). The orchestrator
  validates task↔runner compatibility before any agent runs — comprehension
  tasks require `assistant_message` events; tool-storm detection requires
  `tool_call` events.
- A Mode expresses *one variable* — the integration path that changes between
  baseline and experimental. Modes are declarative YAML, not code. The five
  integration paths (MCP, env, agent_config, wrapper, setup) cover every real
  tool found in the landscape survey.
- Cost is derived, never trusted. There is no `cost` field on Run — there are
  token counts and a pricing table. The cost computation is a pure function:
  `tokens × pricing → usd`.

---

## 4. Data flow — single run

```
CLI parses args
  │
  ▼
Loader reads YAML: task, runner, mode, repos
  │
  ▼
Orchestrator validates: task↔runner compat, mode↔runner compat, toolchain present
  │
  ▼
Repo manager: create worktree at pinned commit, run setup_command
  │
  ▼
Mode: provision arm harness
  │  ├── mcp_config    → write MCP config JSON to <worktree>/.copeca-arms/<arm>/mcp.json; path passed to the runner as its configured MCP arg
  │  ├── env           → set env vars for subprocess
  │  ├── agent_config   → overlay settings.json into arm's config dir
  │  ├── wrapper       → prefix runner command
  │  └── setup          → run per-worktree pre-step
  │
  ▼
Mutations (edit tasks only): apply find/replace/delete/insert,
    git commit, verify no unmatched finds. Abort on failure.
  │
  ▼
Runner: construct CLI command from arg_map or invoke_template,
    spawn subprocess with process-group isolation
  │
  ▼
Parser: parse agent stdout → RunResult(turns[], tool_calls[], tokens, result_text)
  │
  ▼
Validator: check correctness
  │  ├── required_strings → all present? (case-insensitive, substring)
  │  ├── all_of          → every canonical entry present?
  │  ├── forbidden_strings → none present?
  │  └── test_command     → exit 0? (edit tasks only)
  │
  ▼
Cost model: vendor_cost_usd = parsed billed cost (authoritative when reported)
    computed_cost_usd = Σ(tokens × pricing[model])   (reproducible cross-check)
    total_cost_usd = vendor when reported, else computed   (cost_source records which)
  │
  ▼
Writer: append JSONL record
  │
  ▼
Artifact builder (--artifacts flag): create .copeca zip
  │  ├── result.json (always)
  │  ├── manifest.json (SHA-256 hashes + content_hash + repo commit) (always)
  │  ├── task.yaml (if present in worktree)
  │  ├── stdout.txt / stderr.txt (if present in worktree)
  │  ├── session.json, post_mutation.diff, runner.yaml, repos.yaml — planned, not yet collected
  │  └── compute content_hash, record in manifest
  │
  ▼
State machine: reset worktree (git reset --hard HEAD, git clean -fd)
    → ready for next run
```

**Adversarial flags** are computed during the run from the parsed RunResult:

| Flag | Computed from | Formula |
|---|---|---|
| token_snowball | per_turn_context_tokens | max(per_turn) > num_turns × avg(first_3) × factor |
| talkative_failure | output_tokens, correct | output_tokens > threshold AND correct == false |
| tool_storm | num_tool_calls | num_tool_calls > threshold |
| budget_exhausted | total_cost_usd, result_text | cost >= budget AND result_text is null/empty |
| timeout | duration_ms | duration >= timeout_seconds × 1000 |

Flags that depend on data the runner doesn't provide are `null` (not `false`).

---

## 5. Data flow — scenario (matrix)

```
CLI: copeca run scenarios/my.yaml
  │
  ▼
Loader: parse scenario YAML → resolve task globs → compute run matrix
  │  tasks: [t1, t2, ..., tN]
  │  modes: [baseline, experimental]
  │  models: [claude-sonnet-4-6]
  │  reps: 5
  │  total_runs = N × 2 × 1 × 5
  │
  ▼
Validate: schema validation, compat warnings, toolchain check (once per repo)
  │
  ▼
Worker pool: distribute runs across max_workers
  │  workers are repo-affine (assigned to one repo for lifetime)
  │  each worker runs the single-run pipeline (section 4)
  │  results accumulate in one JSONL file (atomic appends)
  │
  ▼
On timeout/crash: SIGKILL process group → git worktree remove --force
    → fresh worktree → re-setup. Affected run records error, not retried.
  │
  ▼
All runs complete → Analysis → Report
```

**Concurrency invariant:** Two workers never share a worktree. Mutations in one
worker are invisible to all others. The bare clone provides a shared object
database; each worktree has an independent working directory.

---

## 6. Extension points

These are the deliberately-designed seams where new things slot in without
touching the core.

### New runner CLI

Add a YAML file to `defaults/runners/`. If the output format matches the built-in
parser (`stream_json`), no code change is needed. If custom:

1. Implement `BaseParser.parse(stdout: str, supported_events: list[str]) -> RunResult`
   in `runners/parsers/`
2. Set `parser: <name>` in the runner YAML
3. Register the parser in the runner factory

The `invoke_template` field handles non-standard CLI argument conventions without
code: `"{cli} exec --json -m {model} -- {prompt}"`.

### New mode (integration path)

Add a YAML file. No code change unless it uses a new integration path beyond the
five covered (MCP, env, agent_config, wrapper, setup). The five paths were chosen
because the landscape survey found every real tool falls into one of them — a
sixth path is possible but unlikely.

### New task

Add a YAML file. Comprehension tasks (string-checked) and edit tasks
(test-command-validated) cover everything. If a task seems to need custom
correctness logic, treat it as a signal the task may not be objectively gradeable
(design decision #15).

### New report format

Add a renderer in `analysis/` that consumes the same `ReportData` object as the
markdown report. The JSON export already exists (`--format json`). Future
formats: HTML, PDF, CI annotations (GitHub Actions summary).

### New adversarial flag

Add a computation function in `orchestration/` that takes a `RunResult` and
returns `bool | null`. Register it in the flag registry. Thresholds are
currently hardcoded; making them per-scenario configurable is planned.

---

## 7. Invariants that survive every change

These are the non-negotiable architectural rules. They are not "best practices"
or "guidelines" — they are the definition of what copeca IS.

1. **Tasks are data, never code.** No embedded Python. No eval. Correctness is
   always strings + test commands. This protects supply-chain safety (a shared
   task set must be safe to load) and objectivity (if you need code to grade it,
   it probably isn't objective).

2. **Cost: the bill is the headline, the model is the yardstick.** `total_cost_usd`
   is the vendor's billed cost when the runner reports it (`cost_source = "vendor"`) —
   it captures cache TTL, tier, and discounts that token counts cannot, and it is
   frozen into the `.copeca` artifact at run time. `computed_cost_usd = Σ tokens ×
   pricing` is always recorded as the reproducible, provider-neutral number — the
   basis for cross-provider and cross-time comparison — and as a cross-check on the
   vendor's self-report (a large divergence flags possible misreporting). When no
   vendor cost is reported, computed is the fallback (`cost_source = "modeled"`).

3. **The baseline must be clean — and proven clean.** Every run executes in a
   clean room (§13): a private throwaway HOME so no host CLI config
   (`~/.claude.json`, `~/.codex/`, `~/.gemini/`) is read, written, or left
   behind; only copeca's declared MCP servers (baseline: none) via the CLI's
   strict-MCP mechanism; ambient instruction files (`CLAUDE.md`/`AGENTS.md`/
   `GEMINI.md`) neutralized; session and telemetry off; the child environment
   built from an explicit allowlist (everything else — `CLAUDECODE`, `CLAUDE_*`,
   `MCP_*`, ambient hooks — excluded); experimental mode env merged on top via
   `provision_arm` so only declared vars reach the experimental child.
   Prevention is backed by detection: a post-hoc symmetric trace gate fails any
   baseline that used the tool-under-test, so a contaminated A/B can never be
   silently reported.

4. **One execution path.** There is no `if docker:` branch. If Docker execution
   is added later, it replaces the subprocess execution path — it doesn't sit
   alongside it. "Which path did this result come from?" must never be a question.

5. **Every edit task proves its mutation bites.** `check-task` verifies the test
   passes on clean code and fails on mutated code. A task that passes on mutated
   code has a weak test and must not enter the corpus.

6. **The repository is pinned.** Every run records the repo commit SHA in the
   manifest. Toolchain versions are declared and verified. A result without
   provenance is not a copeca result.

7. **Task corpus provenance is mandatory.** Every task carries a `source:` field
   with license and commit. Tasks from blocked sources (NC/ND/no-license,
   confirmed-contaminated) are rejected.

8. **The domain layer has no I/O.** Files in `config/`, `tasks/`, and `analysis/`
   never import from `runners/`, `repos/`, `results/`, or `orchestration/`. This
   is mechanically enforceable.

---

## 8. What we explicitly chose NOT to build

These decisions are architectural, not scope-deferred. They define what copeca
is not.

| Non-feature | Why not |
|---|---|
| **Code execution sandbox (Docker)** | One execution path. Config isolation is solved without it: a private per-run HOME (§13) gives zero host-config footprint, and the post-hoc trace gate proves no tool leaked — a stronger "no tool leaked" check than a container, which only isolates the filesystem. Docker would also force the tool-under-test into an image (you'd measure the in-image build, not the local one you're iterating on), add a mode flag, and create two result types. Its real value (hermetic toolchains, untrusted-code blast radius) is a separate, future concern; if added, it replaces subprocess — it doesn't join it. |
| **Multi-episode / stateful tasks** | Cross-session state breaks the isolation model. Memory tools (mem0, Letta, Graphiti) need persistent stores across sessions — external databases, file systems, services. Adding them would require docker-compose fixtures, state snapshot/restore, and a fundamentally different correctness model. The memory space already has dedicated benchmarks (LoCoMo, LongMemEval). Explicitly out of scope. |
| **LLM judge for correctness** | Non-deterministic (breaks reproducibility), self-preferring (a Claude judge favors Claude outputs), rewards verbosity (the exact pattern `talkative_failure` exists to catch). Allowed only for post-hoc failure analysis and authoring-time audits — never in the scoring path. |
| **Web dashboard** | Not architecture — deployment. The artifact model and JSONL format already support it. A web layer that ingests .copeca zips and renders leaderboards is a deployment concern, not a core architecture change. |
| **Real-time / streaming results** | Copeca is a batch benchmark. The JSONL file is append-only during a run; tailing it gives live progress. A streaming API would add complexity (WebSocket, partial aggregates) without changing what the instrument measures. |
| **Pre-call prompt compression mode field** | The five integration paths cover it via `env` (proxy). Adding a dedicated field for it would be overfitting to a specific tool category that the proxy path already serves. |

---

## 9. Scaling model

Copeca scales by adding workers, not by changing architecture.

| Dimension | At launch (~85 tasks) | At scale (~500 tasks) | Limiting factor |
|---|---|---|---|
| Runs per scenario | ~200 | ~2,000 | API cost (~$150 at scale), not architecture |
| Sequential wall time | ~3 hours | ~30 hours | Unacceptable at scale |
| With 4 workers | ~45 minutes | ~8 hours | Worktree I/O becomes the bottleneck |
| Disk (repos) | ~800MB | ~2GB | Acceptable |
| Disk (artifacts) | ~10MB per scenario | ~100MB per scenario | Acceptable |
| Memory | ~200MB per worker | Same | Per-worker overhead is constant |

**What scales:** worker count (up to CPU cores), task count (JSONL is append-only),
repo count (bare clones share disk).

**What doesn't scale:** per-run cost (it's the measurement), per-repo setup time
(one-time cost amortized over all runs targeting that repo).

**The deliberate bottleneck:** we don't cache agent runs. The point is to measure
them, and caching would measure the cache, not the agent. Fresh worktrees, fresh
subprocess, every time.

---

## 10. Dependency graph (what can import what)

```
┌─────────────────────────────────────────────────────────────┐
│ cli.py                                                      │
│   may import: everything                                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌───────────────────┐ ┌───────────────┐ ┌───────────────────┐
│ orchestration/    │ │ adapters      │ │ domain            │
│   may import:     │ │ may import:   │ │ may import:       │
│   domain, ports   │ │ ports, domain │ │ standard library  │
│   never: nothing  │ │               │ │ pydantic, yaml    │
│   above it        │ │               │ │ never: runners,   │
└───────────────────┘ └───────────────┘ │   repos, results,  │
                                        │   orchestration    │
                                        └───────────────────┘
```

This is enforceable in CI:

```bash
# Domain layer must not import I/O
! grep -r "from copeca.runners" src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
! grep -r "from copeca.repos"   src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
! grep -r "from copeca.results" src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
```

---

## 11. Configuration layering

Copeca's configuration resolves in this order (later overrides earlier):

1. **Built-in defaults** — `defaults/runners/*.yaml`, `defaults/modes/*.yaml`
2. **Project config** — `repos.yaml`, `tasks/**/*.yaml`
3. **Scenario file** — specifies which tasks/modes/models/reps
4. **CLI flags** — `--tasks`, `--modes`, `--models`, `--reps`, `--max-workers`,
   `--budget`, `--timeout`, `--artifacts`

There is no user-level config file (no `~/.copeca.yaml`). This is deliberate:
a benchmark must be reproducible, and ambient user config breaks reproducibility.
If two users run the same scenario, they should get comparable results regardless
of their personal copeca settings.

---

## 12. Technology choices (with rationale)

| Choice | Rationale |
|---|---|
| **Python 3.11+** | 3.10 EOL Oct 2026. 3.11 supported until Oct 2027. Widely deployed. |
| **Typer** | Type-hinted CLI with auto-generated help. Active (0.26.x, fastapi org, vendored Click). |
| **Pydantic v2** | Fast, well-maintained data validation for internal models. |
| **jsonschema** | Standard, language-agnostic validation for user-facing YAML. |
| **PyYAML** | Stable, universal YAML parser. |
| **Git (system)** | The only binary dependency. Worktrees provide isolation without Docker. |
| **No async** | Copeca is I/O-bound on subprocesses, not on concurrent connections. The worker pool uses `concurrent.futures.ThreadPoolExecutor`; each thread spawns its own subprocess, so process-level isolation comes from the subprocesses, not the threading model. Async adds complexity without benefit. |
| **No database** | JSONL is the canonical data store. It's append-only, human-readable, `jq`-queryable, and trivially version-controlled. A database would add a schema migration problem for a write-once-read-many workload. |
| **No web framework** | Copeca's API is its CLI. A web layer (leaderboard, dashboard) consumes JSONL + .copeca zips; it doesn't need to be in the same process or even the same repository. |

---

## 13. Cross-CLI isolation: the clean room

copeca benchmarks multiple agent CLIs (Claude Code, Codex, Gemini CLI; more as
data-only descriptors later). The A/B is valid only if **every run receives
exactly the tools/MCP/instructions copeca declares — and nothing from the host.**
That holds across vendors via one contract, two enforcement locks, and one data
descriptor per CLI. Research backing this section:
`docs/research/cross-cli-isolation/findings.md`.

### 13.1 The isolation contract (nine dimensions)

Every run, every CLI, controls these. Vendor-neutral; §13.4 is how each CLI
satisfies them.

| Dimension | What must hold |
|---|---|
| Config root | CLI reads settings/auth/MCP/sessions from a fresh empty dir, not the host |
| MCP servers | exactly copeca's declared set; baseline = none |
| Ambient instructions | no `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` reaches the agent |
| Tool allowlist | only the declared built-in tools |
| Session / state | no carryover between runs |
| Working dir | fresh checkout at the pinned commit |
| Model | pinned via flag every invocation |
| Environment | scrubbed allowlist; no ambient keys/hooks |
| Telemetry / auto-update | no side-channel noise; no mid-run binary change |

### 13.2 Lock 1 — Prevention: isolation profiles

copeca selects one of two isolation profiles per run, based on whether the
runner's `api_key_env` variable is present in the host environment.

#### API-KEY profile (opt-in, for metered/CI use)

Activated when `api_key_env` is set in the runner descriptor **and** the named
env var (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`) is present
in the host environment.

**copeca never reads, writes, copies, or mutates any host CLI config.** The run
gets a private, throwaway `HOME` (and the CLI's config-home env var) pointed into
a per-run temp dir copeca owns and tears down with the worktree. The CLI resolves
every `~/`-relative config path into that dir, so the real `~/.claude.json`,
`~/.codex/`, `~/.gemini/` are never touched — nothing leaks in, nothing is left
behind. Auth comes from the API key, which passes through to the child env.

#### SUBSCRIPTION profile (default, for local/developer use)

Activated when `api_key_env` is absent in the runner descriptor OR the named env
var is not present in the host environment.

The host `HOME` is **not** redirected — the CLI's existing subscription login is
used as-is. Only the flag/env neutralizers are applied (see below). Critically,
**all provider key env vars are dropped from the child env** (`ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`) so
a stale or expired key cannot shadow the subscription login and cause billing
errors or silent auth failures.

Lock 2 (§13.3, the post-hoc symmetric trace gate) guarantees A/B validity in
subscription mode: because both baseline and tool arm run with identical host
settings, any ambient influence is symmetric and cancels in the delta.

#### Neutralizers applied in both profiles

**Strict-MCP** (baseline none; tool arm exactly the declared set),
**ambient-instruction neutralization**, **session-off**, **telemetry-off**,
and the **tool allowlist**.

### 13.3 Lock 2 — Detection: prove it after the fact

Prevention can have per-CLI gaps (Gemini and Codex lack a single strict-MCP flag).
Two vendor-neutral checks read ground truth, not config:

- **Pre-run workdir scan** — refuse the run (`CONTAMINATED_WORKDIR`) if the
  worktree tree contains ambient instruction files copeca cannot disable for that
  CLI.
- **Post-hoc symmetric trace gate** — after parsing the trace: baseline
  `tool_calls ∩ tool-under-test == ∅` else `CONTAMINATED_TRACE` (excluded from the
  delta); the tool arm must have used the tool (`tool_adopted`). Because it reads
  the parsed trace, it catches leaks on **any** CLI — it is the guard that would
  have caught the contamination incident, and it is why the deliberate no-Docker
  choice (invariant 4, §8) holds.

### 13.4 The per-CLI descriptor (data, not code)

Each runner YAML carries an `isolation:` block — the data the orchestrator reads
to apply the contract uniformly, with **no per-CLI branches** in the engine
(invariant 4).

```yaml
isolation:
  config_home_env: CLAUDE_CONFIG_DIR        # set alongside HOME, into the per-run dir
  strict_mcp_flags: [--strict-mcp-config]   # baseline: applied with no --mcp-config
  disable_ambient_env: { CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1" }
  disable_session_flags: [--no-session-persistence]
  disable_telemetry_env: { CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1" }
  ambient_files: [CLAUDE.md, CLAUDE.local.md]   # for the pre-run workdir scan
  api_key_env: ANTHROPIC_API_KEY                # present in host env → API-KEY profile
  version_cmd: [claude, --version]              # provenance
```

Lock-1 summary per shipped CLI:

| CLI | private home (API-KEY profile) | strict-MCP (baseline=none) | ambient off | session off | api_key_env |
|---|---|---|---|---|---|
| Claude Code | `HOME` + `CLAUDE_CONFIG_DIR` | `--strict-mcp-config` | `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` | `--no-session-persistence` | `ANTHROPIC_API_KEY` |
| Codex | `HOME` + `CODEX_HOME` | `--ignore-user-config` | fresh home + workdir scan (`AGENTS.md`) | `--ephemeral` | `OPENAI_API_KEY` |
| Gemini CLI | `HOME` + `GEMINI_CLI_HOME` | `--allowed-mcp-server-names` (none) | `context.fileName` override + workdir scan (`GEMINI.md`) | fresh `--session-id` | `GEMINI_API_KEY` |

The tool arm injects MCP per CLI: Claude `--mcp-config <file>`; Codex repeated
`-c mcp_servers.<name>...`; Gemini writes `mcpServers` into the scoped
`settings.json` inside its private home, then allows it by name.

### 13.5 Version provenance

Each record stores the resolved tool-under-test version + path (the descriptor's
`version_cmd`). A preflight detects multiple installed versions of the tool and
warns (the homebrew-0.9.0-vs-cargo-1.0.0 trap that voided an early run). "Which
version was tested?" is always answerable from the artifact.

### 13.6 Scope

Claude Code, Codex, and Gemini CLI are implemented and **empirically verified** —
a baseline run against a host config that carries an MCP server must show zero use
of it. Cline, Goose, Copilot CLI, Amp, and aider are data-only descriptors added
on demand. OpenCode is deferred (config-merge + cost-event bugs; see findings.md).
