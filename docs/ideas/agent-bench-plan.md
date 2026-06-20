# Copeca — Architecture & Implementation Plan

> **Status:** Decided (2 reviews + design discussion, 2026-06-07)  
> **Goal:** Generic, repeatable, verifiable benchmark for CLI-based coding agents.  
> **Primary metric:** Cost per correct answer.

---

## 1. What It Is

Copeca runs code tasks through CLI agents (Claude Code, Codex, OpenCode, etc.) and measures **cost per correct answer** — how many dollars you spend, on average, before getting a right answer. This combines cost and accuracy into a single number representing expected spend under retry.

```
cost_per_correct = total_spend / correct_count
```

Equivalent to `avg_cost / accuracy_rate`. A tool that costs $0.10/run at 50% accuracy has cost-per-correct of $0.20 — same as a tool at $0.20/run with 100% accuracy.

### Why

Nobody can measure whether their MCP server, memory system, or harness improvement *actually helps*. Existing benchmarks are tied to one tool or measure accuracy without cost. Copeca fills that gap with:

1. **Declarative tasks** — 20 lines of YAML, no per-task Docker, no Python class
2. **Pluggable runners** — any CLI that reports token counts on stdout
3. **A/B modes** — baseline vs. experimental tool profiles
4. **Verifiable results** — tamper-evident `.copeca` zips with content hashing and batch completeness checking

### What It Replaces

| Benchmark | Cost tracked? | Configurable runners? | Task format | Verifiable? |
|-----------|:---:|:---:|---|---|
| SWE-bench | No | No | JSON + Docker | No |
| Aider benchmark | Yes | No (Aider only) | Fixed suite | No |
| can-ai-code | No | Multiple backends | YAML anchors | No |
| OpenHands eval | No | Agent config | Python per-benchmark | No |
| agent_eval | Yes (raw) | Claude Code only | YAML | No |
| **Copeca** | **Yes (cost/correct)** | **Any CLI** | **YAML + JSON Schema** | **Yes (hashed + batch)** |

### What Nobody Does

1. **Cost-per-correct as THE headline metric.** Everyone tracks cost separately from accuracy. Nobody combines them into a single number. Two tools — one cheap at 50% accuracy, one expensive at 100% — look incomparable, when in fact they have the same expected cost under retry.

2. **Generic runner abstraction.** You cannot plug a new CLI agent into any existing benchmark without forking code. Every benchmark hardcodes its agent invocation. Copeca decouples the runner (CLI + args + parser + pricing) from everything else.

3. **YAML-first tasks with JSON Schema validation.** SWE-bench uses JSON but requires Docker per task. can-ai-code uses YAML but for interview-style coding, not codebase navigation. Nobody has declarative, validated tasks for the "explore a codebase and answer" use case.

4. **A/B mode comparison as a built-in workflow.** No benchmark is designed for "baseline vs. experimental tool profile." You run two separate benchmarks and compare manually. Copeca makes this a single scenario file.

5. **Futility detection.** SWE-Effi identified "token snowball" and "expensive failures" — unresolved tasks burning 4–13× more tokens than solved ones. No eval tool flags these. Copeca bakes adversarial flags into every run and reports them.

6. **Cross-provider cost normalization.** Models from Anthropic, OpenAI, and Google have different pricing. No tool normalizes per-task cost across providers. Copeca computes cost from token counts against a single pricing source — not each vendor's self-reported number — which is the only way the comparison is apples-to-apples.

7. **Tamper-proof and complete results.** No benchmark produces verifiably authentic artifacts. Copeca's `.copeca` zips with SHA-256 content hashing let anyone verify authenticity. Batch verification ensures no runs were silently dropped.

### Positioning & Scope

**The lane.** Live cost leaderboards exist — SWE-rebench reports `$/problem`, HAL reports cost-per-rollout, SWE-Effi formalizes cost-budget AUC — but they all compare *whole agent×model stacks* and answer "which stack is cheapest." Copeca holds the agent and model **fixed** and varies **one tool**, answering a different question with a different user: *"did my tool help, and what did it cost?"* No existing suite occupies that lane.

**The real need.** The space floods with unverified, accuracy-blind, non-comparable savings claims — RTK "60–90%", Headroom "90%", various tools "−30%/−96%/−99%", each on its own methodology with no shared baseline. A 2026 pre-registered trial found compression can *expand output tokens and negate the saving* — so many of these numbers are misleading. Copeca is the neutral, accuracy-adjusted, verifiable yardstick: *"−90% tokens but +15% wrong answers is worse cost-per-correct — and here is the hash."* Its full input+output cost accounting catches exactly the output-expansion that input-only self-reports hide.

**In scope (v1):** within-session efficiency tools — code-context/navigation MCP, context/output filters, compression proxies and hooks. These are what the integration mechanisms in §2 are built to A/B.

**Out of scope (v1), deliberately:** cross-session/persistent memory (mem0, Letta, Graphiti). Their value lives *across* sessions; copeca's stateless single-shot model resets the exact boundary they exploit, and measuring them needs a stateful multi-episode model + external store fixtures that would compromise copeca's reproducible, no-external-services core. Dedicated memory benchmarks already own this (LoCoMo, LongMemEval) — point users there rather than diluting the tool.

---

## 2. Core Concepts

### Task
A code question. YAML file, **data only** (no embedded code — see §10 #15). Two types that differ in how correctness is checked:

| Type | Validation |
|------|-----------|
| **comprehension** | Required/all_of/forbidden strings in agent response |
| **edit** | Mutation applied → agent fixes → test command must pass. Strings are diagnostic. |

Diff tasks ("a recent commit broke X, find and fix it") are edit tasks where the prompt references git history instead of naming the bug. The validation is identical: a test command that must pass. The reporting layer infers task category from the presence of mutations, not from a type field.

**Task ↔ runner compatibility:** Comprehension tasks require a runner that emits `assistant_message` events. If a scenario pairs a comprehension task with a runner that only reports tokens, copeca warns at validation time. Edit tasks work with any runner that reports tokens.

#### Completeness verification (comprehension tasks)

`required_strings` checks presence — did the agent mention X? `all_of` checks completeness — did the agent mention EVERYTHING in the canonical list? `forbidden_strings` checks absence — did the agent say something it shouldn't?

```yaml
ground_truth:
  required_strings: ["Matcher", "find_at"]       # must ALL appear
  all_of: ["RegexMatcher", "GlobMatcher", "MultiMatcher"]  # must ALL appear
  forbidden_strings: ["I cannot"]                 # must NONE appear
```

Keeping `all_of` separate from `required_strings` is deliberate, not redundant. Code-navigation tools — the primary thing copeca benchmarks — are sold on *completeness*: "finds every implementor in one search." Measuring completeness as its own signal lets reports say "agents locate the trait 95% of the time but enumerate all implementors only 60%" — exactly the axis such tools claim to improve. The mechanism is the same (every listed string must appear, case-insensitive substring); the separation carries the author's intent about *which* failure is which. Regex is deferred (§12).

**Known limitation:** String matching can't detect hallucinated extras or validate structured output (JSON/YAML) — use an edit task with a test command when that matters (§12).

#### How `correct` is computed

- **comprehension:** `correct = required_strings_passed AND all_of_passed AND forbidden_strings_passed`. An empty or absent agent response fails every string check → `correct: false`.
- **edit:** `correct = test_command_passed`. The test is authoritative (SWE-bench lesson #1 below). `required_strings`/`forbidden_strings`, if present on an edit task, are recorded in `correctness_detail` for diagnostics but do **not** change `correct` — a passing test with a missing required string is still correct, but the disagreement is visible in the detail (often a sign of a weak test or an unusual-but-valid fix).

#### Why multi-faceted correctness

SWE-bench's post-release audits revealed structural failure modes in single-strategy validation:

1. **String matching alone is too weak.** ~31% of SWE-bench "successful" patches didn't actually fix the bug. For edit tasks, a passing test command is the only honest signal.

2. **Test commands can be gamed.** ~59% of SWE-bench Verified tasks have flawed test cases. Copeca's mutation-validity check (§3) guards against the worst case — a test that passes even with the bug present.

3. **Problem statements must not leak answers.** ~33% of SWE-bench "successes" involved solutions copied verbatim from the issue text. Ground truth strings are audited against prompts.

4. **Static historical data gets memorized.** Frontier models reproduce SWE-bench gold patches verbatim from task IDs alone. Multi-faceted validation means memorizing strings isn't enough for edit tasks.

### Runner
A CLI tool that accepts a prompt and reports token usage as JSON on stdout. Defined in YAML. A runner declares which event types it supports; this determines which task types it's compatible with.

### Mode
A tool profile for A/B testing — the *one variable* that changes between baseline and experimental. Surveying the actual tool population (token-savings tools, code-context MCP, context filters) showed they attach to a CLI agent five different ways; a mode expresses all of them:

| Integration | Mode field | Example tool |
|------|-----------|-----------|
| MCP server | `mcp_config` | tilth, sigmap |
| API proxy (redirect the endpoint) | `env` (e.g. `ANTHROPIC_BASE_URL`) | Context Gateway, Entroly |
| Config-dir hook (PreToolUse etc.) | `agent_config` (settings overlay) | RTK |
| Process wrapper | `wrapper` (command prefix) | `headroom wrap claude` |
| Pre-run index / install | `setup` (runs once per worktree) | claude-context, GrepAI |

This breadth is not optional: the most popular token-savings tools (RTK ~59k⭐, Context Gateway, Headroom ~16k⭐) attach via hooks, proxies, and wrappers — **not** MCP. A mode that only knew `mcp_config` could benchmark a minority of the field.

**Per-arm harness isolation:** copeca launches each arm with its *own* config dir and env, so the baseline is provably clean. It never inherits the host's ambient hooks or proxies — otherwise a baseline that silently carried a host-installed RTK hook would measure nothing. Controlling the harness per-arm is what makes the one-variable A/B trustworthy (see §10 #15).

A pre-call *prompt* compressor (e.g. LLMLingua) gets no dedicated field: in a coding task the tokens live in mid-session tool output, not the initial prompt, so prompt-level compression is near-useless here — and if someone wants it anyway, the `env` proxy path covers it. Adding a field for it would be overfitting.

### Scenario
What to run: tasks × modes × models × reps. YAML file or CLI flags. Models use full model IDs (matching runner pricing keys).

---

## 3. Task Format

### Comprehension Task

```yaml
name: rg_trait_implementors
description: "Find all implementors of the Matcher trait"
type: comprehension
difficulty: hard
language: rust
repo: ripgrep
version: 1

prompt: |
  Find the `Matcher` trait definition in the matcher crate, and list
  its required methods. Then find all types that implement this trait.

ground_truth:
  required_strings:
    - "Matcher"
    - "find_at"
  all_of:
    - "RegexMatcher"
    - "GlobMatcher"
    - "MultiMatcher"
  forbidden_strings:
    - "I cannot"
  source: "SWE-QA (Apache-2.0)"     # optional: provenance, not in grading
```

### Edit Task

```yaml
name: rg_edit_line_count
description: "Fix off-by-one in line counting"
type: edit
difficulty: medium
language: rust
repo: ripgrep
version: 1

mutations:
  - file: crates/searcher/src/lines.rs
    find: "memchr::memchr_iter(line_term, bytes).count() as u64"
    replace: "memchr::memchr_iter(line_term, bytes).count() as u64 + 1"
    # If `find` appears multiple times, use `occurrence: 2` (1-indexed)

test_command: [cargo, test, "-p", grep-searcher, line_count]

prompt: |
  The count() function in crates/searcher/src/lines.rs is returning
  one more than the actual number of newlines. Find and fix the bug.

ground_truth:
  required_strings: []  # diagnostic only (optional for edit)
  forbidden_strings: [] # optional
```

### Mutation Format

```yaml
mutations:
  # Replace (default action): find → replace
  - file: src/lib.rs
    find: "old_code"
    replace: "new_code"
    occurrence: 1    # optional, 1-indexed. Required if find appears >1 times.

  # Delete a line
  - file: src/lib.rs
    action: delete
    find: "remove this line"

  # Insert after a line
  - file: src/lib.rs
    action: insert_after
    find: "existing line"
    content: "new line to insert"

  # Create a new file
  - file: src/new_test.rs
    action: create
    content: |
      #[test]
      fn new_test() {}
```

Multi-file mutations are supported via the array. All mutations are applied atomically and committed before the agent runs. If any mutation's `find` does not match (or matches a different count than `occurrence` permits), the task aborts with an error before the agent runs — copeca never runs an agent against a partially-mutated repo.

### Repo Registry

Tasks reference repos by name. A central `repos.yaml` avoids copy-paste:

```yaml
# repos.yaml
ripgrep:
  url: https://github.com/BurntSushi/ripgrep.git
  commit: 0a88cccd5188074de96f54a4b6b44a63971ac157
  language: rust
  toolchain: { rust: "1.80.0" }     # verified before runs; mismatch is a hard error
  setup_command: [cargo, fetch]

fastapi:
  url: https://github.com/tiangolo/fastapi.git
  commit: 6fa573ce0bc16fe445f93db413d20146dd9ff35d
  language: python
  toolchain: { python: "3.11" }
  setup_command: [python, -m, pip, install, -e, "."]

gin:
  url: https://github.com/gin-gonic/gin.git
  commit: d7776de7d444935ea4385999711bd6331a98fecb
  language: go
  toolchain: { go: "1.22" }
  setup_command: [go, mod, download]

express:
  url: https://github.com/expressjs/express.git
  commit: 1140301f6a0ed5a05bc1ef38d48294f75a49580c
  language: javascript
  toolchain: { node: "20" }
  setup_command: [npm, install]
```

The orchestrator state machine:

```
Clone → Verify toolchain → [per worktree: Setup → [Reset → Mutate → Run → Validate] × reps]
```

**Reset semantics:** Between runs targeting the same repo in the same worktree, `git reset --hard HEAD && git clean -fd` (NOT `-fdx` — preserves `node_modules/`, `target/`, `vendor/`). When a worktree is removed and a fresh one created, setup runs again from scratch.

**Environment is declared, not assumed.** Each repo pins its toolchain versions. Right after cloning — before any of the run matrix executes — copeca verifies the host provides them (`rustc --version`, `python --version`, …). A mismatch aborts the scenario with a clear error, never a silent wrong result from compiling against the wrong compiler. *How* you provide the toolchain — Docker image, devcontainer, nix, asdf, or a bare host — is your choice and outside copeca's scope. Docker is the easiest way to pin an exact toolchain, and the docs recommend it; but **copeca has no Docker mode and no `--sandbox` flag**. There is one execution path: verify the declared environment, then run (§10 #17). For comprehension tasks (no compilation) the toolchain is irrelevant and verification is a no-op.

### JSON Schema (static validation)

Validated at load time — no cloning or execution:
- `name`: required, `^[a-z][a-z0-9_]*$`
- `type`: `comprehension | edit`
- `repo`: must match a key in `repos.yaml`
- `version`: required, integer. Incremented when ground truth changes.
- `difficulty`: `easy | medium | hard` (task-author declared, used for reporting aggregation)
- `comprehension`: at least one of `required_strings`, `all_of` must be non-empty. `forbidden_strings` optional.
- `edit`: `test_command` required. `required_strings` and `forbidden_strings` optional (empty lists valid).
- Mutations: `find` with `action: replace|delete|insert_after` must match at least once. If more than once, `occurrence` is required.
- Mutations: `action: create` requires `content`, must not shadow an existing file.

### Mutation validity (deep check)

Static validation can't prove an edit task is *meaningful*. A mutation that doesn't actually break the test makes the task solvable by doing nothing — the exact weak-test failure that left ~59% of SWE-bench Verified tasks flawed. `copeca check-task <task.yaml>` proves the mutation bites:

1. Clone the repo at the pinned commit, verify toolchain, run `setup_command`.
2. Run `test_command` on the clean tree — must **PASS** (the test is valid to begin with).
3. Apply mutations, run `test_command` again — must **FAIL** (the bug is real and the test detects it).

A task that fails either check is rejected. This is slow (clone + build + test), so it is **not** run on every benchmark execution — it's an authoring-time and CI gate, not a per-run cost. The task suite's CI should run `copeca check-task` over all edit tasks.

### Corpus Design & Neutrality

A benchmark whose author ships their own tool's win-set is worthless. copeca's seed corpus is **derived from independent, license-safe, low-contamination sources** — not from the author's tool-favorable hand-picked set. The ~35 tilth tasks are **not the canonical corpus**; they are an initial convenience seed whose bias is acknowledged. The canonical set is meant to be governed independently (§11).

#### Source Licensing Tiers

Corpus candidates were surveyed across 4 independent source families (SWE-bench-based, code-generation, repo-navigation, contamination research). License-eligible sources permissively available for derivation with attribution:

| Source | License | Contamination | Domain | Use for |
|---|---|---|---|---|
| **Long Code Arena** (JetBrains) | Apache-2.0 | LOW | Cross-file comprehension; multi-task | Comprehension seed |
| **SWE-QA** | Apache-2.0 | LOW (Sep 2025) | Multi-hop QA across 12 repos | Comprehension seed |
| **SCBench / RepoQA** (Microsoft) | MIT | MED | Function retrieval from repos | Comprehension seed |
| **CrossCodeEval** | Apache-2.0 | MED (The Stack v2) | Cross-file completion | Comprehension bulk |
| **SWE-bench-Live** (Microsoft) | MIT | LOW (monthly post-cutoff) | Multi-language edit tasks | Edit seed |
| **SWE-rebench** (Nebius) | CC BY 4.0 | LOW (timestamp-filtered) | Python edit tasks | Edit bulk |
| **Terminal-Bench 2.0** | Apache-2.0 | LOW | CLI/environment navigation | Specialty tasks |

**Explicitly blocked:** RepoBench (CC BY-NC-ND — derivative works prohibited), ClassEval (CC-BY-NC — non-commercial), DevEval / CoderEval (no license file), SWE-bench Verified / HumanEval / MBPP (confirmed memorized — OpenAI formally deprecated SWE-bench Verified Feb 2026; gold patches reproducible from task IDs alone).

#### Contamination Self-Check

Before a task enters the corpus, copeca's `check-task` (for edits) or a simple probe (for comprehension) verifies the model can't answer from memory: if the model reproduces the gold solution from the task ID + minimal hint alone, the task is flagged as contaminated and excluded. This is run once at corpus assembly time, not per benchmark run.

#### Seed Corpus Taxonomy (~25 tasks, expanding to ~50)

Derived from the independent-source survey's coverage of comprehension + edit task types across 4+ languages. Organized by what the agent must **do**, not how any tool represents code — no category aligns exclusively with one mechanism:

| # | Category | Type | Count | Languages | Discriminates on |
|---|----------|------|-------|-----------|------------------|
| 1 | Local Definition Lookup | Comprehension | 3 | RS, PY, GO, JS | Symbol resolution speed, token efficiency |
| 2 | Cross-File Dependency Tracing | Comprehension | 5 | All four | Import graph / re-export chain navigation |
| 3 | Architectural Comprehension | Comprehension | 4 | RS, GO, JS | Synthesis across many files, structural understanding |
| 4 | Data Flow & Control Flow | Comprehension | 4 | All four | Call chain tracing through indirection |
| 5 | Error Diagnosis & Localization | Comprehension | 3 | All four | Diagnostic reasoning from error to root cause |
| 6 | Targeted Bug Fix | Edit | 3 | All four | Precise single-site edit generation |
| 7 | Cross-Cutting Change | Edit | 2 | RS, JS, PY | Blast-radius awareness, multi-site consistency |
| 8 | Dependency / Config Fix | Edit | 1 | Any | Build-system semantics |

The comprehension-heavy split (15 vs 10) is deliberate: copeca's differentiator from SWE-bench is measuring cost-efficiency of *finding answers* in a codebase, and comprehension is where the cost-per-correct gap between a good tool and a bad one is widest. Edit tasks exist to prevent the corpus from being a pure search benchmark. The taxonomy rewards general effectiveness: a tool that excels at one category but fails others shows a partial win, not a sweep.

Tasks carry an optional `source:` field for provenance — not displayed in reports, not in marketing, just traceability for anyone who audits the corpus. The taxonomy categories themselves are generic and require no attribution.

#### Concrete source families (tasks authored fresh, deriving at most repo lists + category inspiration)

| Source | License | Contamination | What we take | New tasks (~) |
|---|---|---|---|---|
| **SWE-QA** | Apache-2.0 | LOW (Sep 2025) | Repos + question *topics* → write our own prompts and ground truth | 20–30 comprehension QA tasks |
| **RepoQA (via SCBench)** | MIT | MED | Repos + function-retrieval pattern → "find the function that does X" | 15–20 comprehension |
| **Long Code Arena — Bug Localization** | Apache-2.0 | LOW (Jun 2024) | Bug-description pattern → "diagnose this symptom, find the root cause" | 10–15 comprehension |
| **CrossCodeEval** | Apache-2.0 | MED (The Stack v2) | Pre-vetted permissively-licensed repos + commit pins | (repo discovery only) |
| **SWE-bench-Live** | MIT | LOW (monthly post-cutoff) | Edit-task pattern + repos → issue → patch format | 10+ edit tasks |
| **Terminal-Bench 2.0** | Apache-2.0 | LOW | Repos + CLI navigation pattern | 5 specialty tasks |

#### Competitive landscape note

Some 45 tools now populate this space (~35 surveyed in the initial landscape + 20 more from follow-up searches). The field's self-reported claims follow an identical pattern: "-X% tokens," different methodology, no accuracy adjustment. One notable exception: **Headroom** publishes both marketing numbers (95%) and real-world telemetry medians (4.8%) — the only tool that acknowledges the gap. **sense/bench** (May 2026) is the only independently published multi-tool comparison but is author-biased (author's tool ranked #1). No existing tool, benchmark, or leaderboard provides a reproducible, accuracy-adjusted, verifiable, tool-as-variable A/B harness. The lane is unoccupied.

---


## 4. Runner Configuration

### Runner YAML

```yaml
# runners/claude.yaml
name: claude
cli: claude
version_command: [claude, "--version"]   # Populates metadata.runner_version
default_args:
  - "-p"
  - "--output-format"
  - "stream-json"
  - "--verbose"
  - "--dangerously-skip-permissions"
  - "--no-session-persistence"

arg_map:
  model: "--model"
  budget: "--max-budget-usd"
  system_prompt: "--system-prompt"
  tools: "--tools"
  mcp_config: "--mcp-config"
  prompt_separator: "--"   # flags precede this; the task prompt follows as a positional arg

# invoke_template is the escape hatch. If present, arg_map is ignored.
# invoke_template: "{cli} exec --json -m {model} -- {prompt}"
# Template variables: {cli}, {model}, {system_prompt}, {tools},
#   {mcp_config}, {prompt}, {budget}
# Values come from: runner config (cli), scenario (model, budget, system_prompt),
#   mode (tools, mcp_config), task (prompt)

parser: stream_json
supported_events: [turn, result, tool_call, assistant_message, error]

pricing:                          # Example rates — verify current pricing AND model IDs at use.
  claude-sonnet-4-6:              # The staleness warning (below) exists precisely because these go stale.
    input: 3.00
    cache_creation: 3.75
    cache_read: 0.30
    output: 15.00
    updated: "2026-06-01"
  claude-opus-4-6:
    input: 15.00
    cache_creation: 18.75
    cache_read: 1.50
    output: 75.00
    updated: "2026-06-01"
  claude-haiku-4-5:
    input: 0.80
    cache_creation: 1.00
    cache_read: 0.08
    output: 4.00
    updated: "2026-06-01"
```

**Invocation resolution:** `invoke_template` takes precedence over `arg_map`. If both are present, `invoke_template` is used and `arg_map` is ignored. If neither is present, copeca errors at load time.

**Template variables** available in `invoke_template`: `{cli}`, `{model}`, `{system_prompt}`, `{tools}`, `{mcp_config}`, `{prompt}`, `{budget}`. Values resolve from: runner config (`cli`), scenario (`model`, `budget`, `system_prompt`), mode (`tools`, `mcp_config`), and task (`prompt`).

**`arg_map` construction:** Each key maps to a value from the scenario/mode/task. e.g., `model: "--model"` produces `--model claude-sonnet-4-6`. Resolved arguments are concatenated after `default_args`. The final arg is `prompt_separator` (e.g. `--`) followed by the task prompt as a positional.

**Model resolution:** Models in the scenario use full model IDs that match pricing keys. `models: [claude-sonnet-4-6]`, not short names. `model_runner_map: {claude-sonnet-4-6: claude}` maps the model ID to the runner name. There is no alias layer — the pricing key IS the canonical model identifier.

**Staleness:** Each model entry has an `updated` date. Copeca warns if any used model's pricing is >30 days old. Per-model granularity.

**Budget enforcement** is runner-dependent: Claude Code enforces `--max-budget-usd`, but other CLIs may have no budget flag. `timeout_seconds` is the universal backstop — every run is killed at the wall-clock limit regardless of runner.

**Security:** The default Claude runner uses `--dangerously-skip-permissions` — the agent has unrestricted bash in the repo. If you run untrusted repos, run *copeca itself* inside a container or VM. That isolation is the operator's responsibility, not a per-run copeca mode (§10 #17).

**Mode ↔ runner compatibility:** If a mode has `mcp_config` but the runner's `arg_map` has no `mcp_config` key (and no `invoke_template` referencing `{mcp_config}`), copeca warns at scenario load time. The run continues but without MCP tools.

### Runner Output Contract

Copeca depends on the *least* possible from a runner: **token counts.** Everything else it derives. This is what lets "any CLI" plug in — cost, duration, and completion are never trusted to the vendor.

**Required** — total token usage, as a final total or summed from per-turn `turn` events:
```jsonl
{"type": "turn", "input_tokens": 5000, "output_tokens": 200,
 "cache_creation_tokens": 3500, "cache_read_tokens": 3000}
```

**Required for comprehension tasks** — the agent's answer text:
```jsonl
{"type": "assistant_message", "text": "The Matcher trait is defined in...", "turn": 2}
```

**copeca derives, never trusts the vendor for:**
- **cost** = `Σ tokens × runner.pricing[model]`. Computing cost from one pricing source is what makes cross-vendor numbers comparable — vendors round and discount differently, so self-reported costs aren't.
- **duration** = wall-clock around the subprocess.
- **completion** = process exit.

**Optional — enriches when present:**
```jsonl
{"type": "tool_call", "name": "tilth_search", "input": {"query": "Matcher"}, "turn": 0}
{"type": "result", "total_cost_usd": 0.0734, "duration_ms": 45230}   # CROSS-CHECK ONLY
{"type": "error", "code": "timeout", "message": "Subprocess killed after 300s"}
```
- Per-turn breakdown enables `token_snowball`; `tool_call` enables `tool_storm`/adoption; `error` gives precise classification.
- The vendor's `total_cost_usd`, when present, is used **only as a cross-check**. If it diverges from the computed cost by >5%, copeca warns — usually a stale `updated` pricing entry.

**Cost is modeled, not invoiced.** On a flat-rate subscription you still get the API-rate-equivalent cost. That's correct for comparison (you want normalized cost, not "$20/mo") but it is not your bill.

**Why cost reporting isn't trusted:** it's inconsistent — Claude Code reports `total_cost_usd`, Codex reports none (tokens only), others vary. Tokens are near-universal because every agentic CLI needs them for context management. Computing from tokens is both more robust and the only honest basis for cross-provider comparison.

**Built-in parsers:** `stream_json` (Claude Code), `codex_json` (Codex), `generic` (JSONPath mappings in the runner YAML). Custom parsers implement `BaseParser.parse(stdout: str, supported_events: list[str]) -> RunResult`.

### Mode

```yaml
# modes/baseline.yaml
name: baseline
description: "Built-in tools only"
tools: [Read, Edit, Grep, Glob, Bash]

# modes/tilth.yaml — MCP server
name: tilth
description: "Built-in tools + tilth MCP"
tools: [Read, Edit, Grep, Glob, Bash]
mcp_config:
  tilth:
    command: "~/.cargo/bin/tilth"
    args: ["--mcp", "--edit"]

# modes/rtk.yaml — config-dir hook (no MCP)
name: rtk
description: "Built-in tools + RTK PreToolUse output filter"
tools: [Read, Edit, Grep, Glob, Bash]
agent_config: ./modes/rtk-settings.json   # overlaid into the arm's isolated config dir

# modes/gateway.yaml — API proxy
name: gateway
description: "Built-in tools + Context Gateway compression proxy"
tools: [Read, Edit, Grep, Glob, Bash]
env:
  ANTHROPIC_BASE_URL: "http://localhost:8080"
setup: [context-gateway, start, "--port", "8080"]   # runs once per worktree

# modes/headroom.yaml — process wrapper
name: headroom
description: "Agent launched through `headroom wrap`"
tools: [Read, Edit, Grep, Glob, Bash]
wrapper: [headroom, wrap]   # prefixed to the agent launch command
```

`env`, `agent_config`, `wrapper`, and `setup` are all applied inside the per-arm isolated environment (§2), so the baseline never inherits them. A runner must support the mechanism a mode uses (e.g. MCP modes need a runner whose `arg_map` has `mcp_config`); copeca warns at scenario load if a mode and runner are incompatible.

### Scenario

```yaml
# scenarios/tilth_vs_baseline.yaml
name: tilth-vs-baseline
tasks:
  include: ["rg_*", "fastapi_*", "gin_*", "express_*"]   # matches task `name` fields
  exclude: ["*_edit_*"]

modes: [baseline, tilth]
models: [claude-sonnet-4-6]
model_runner_map:
  claude-sonnet-4-6: claude

repetitions: 5
budget_usd: 1.00
timeout_seconds: 300
max_workers: 4

adversarial_thresholds:            # Optional, customize per scenario
  token_snowball_factor: 2.0
  talkative_failure_tokens: 1000
  tool_storm_count: 50

system_prompt: |
  You are a code assistant. Ignore CLAUDE.md files.

output_dir: results/
```

**Minimum repetitions:** Copeca warns if `repetitions < 5`. The scenario schema validation also emits this warning.

**Task globs** (`include`/`exclude`): Match against task `name` fields. Glob syntax: `*` matches any characters, `?` matches one character.

---

## 5. Adversarial Flags

Computed during the run, reported in every JSONL record and in analysis summaries.

| Flag | Definition | Threshold |
|------|-----------|-----------|
| **token_snowball** | Per-turn context token growth exceeds linear growth by more than the configured factor | `max(per_turn) > num_turns × avg(first_3_turns) × factor` (default factor: 2.0) |
| **talkative_failure** | Agent produced substantial output but still failed | `output_tokens > threshold AND correct == false` (default: 1000 tokens) |
| **tool_storm** | Excessive tool calls suggesting the agent is flailing | `num_tool_calls > threshold` (default: 50) |
| **budget_exhausted** | Hit the dollar cap without producing a result | `total_cost_usd >= budget_usd AND (result_text is null OR result_text == "")` |
| **timeout** | Hit the wall-clock limit | `duration_ms >= timeout_seconds * 1000` |

All thresholds are configurable in the scenario file. Flags that depend on missing runner data are `null` (not `false`).

---

## 6. Architecture

```
copeca/
├── pyproject.toml
├── repos.yaml
│
├── schemas/
│   ├── task.schema.json
│   ├── runner.schema.json
│   └── scenario.schema.json
│
├── src/copeca/
│   ├── cli.py                       # Typer CLI
│   ├── config/
│   │   ├── models.py                # Dataclasses
│   │   └── loader.py                # YAML + jsonschema
│   ├── tasks/
│   │   ├── loader.py
│   │   ├── validator.py             # Correctness check + mutation-validity deep check
│   │   └── mutations.py
│   ├── repos/
│   │   └── manager.py               # Clone → verify toolchain → worktree → setup → reset
│   ├── runners/
│   │   ├── base.py                  # Abstract runner + parser + invoke resolution + cost-from-tokens
│   │   ├── subprocess.py
│   │   └── parsers/
│   │       ├── stream_json.py
│   │       ├── codex_json.py
│   │       └── generic.py
│   ├── orchestration/
│   │   ├── run.py                   # Matrix loop + worker pool
│   │   ├── state.py                 # Worktree lifecycle + setup
│   │   └── validation.py           # Scenario-level warnings (task↔runner compat, etc.)
│   ├── results/
│   │   ├── writer.py
│   │   ├── artifact.py              # .copeca zip (opt-in)
│   │   └── verification.py          # verify + batch completeness
│   └── analysis/
│       ├── stats.py
│       ├── report.py
│       └── compare.py
│
├── defaults/
│   ├── runners/{claude,codex,opencode}.yaml
│   └── modes/default.yaml
│
├── tasks/{ripgrep,fastapi,gin,express,grok}/*.yaml
│
└── tests/                           # grows per phase; see phase tables
```

### CLI

```
copeca run scenarios/my.yaml
copeca run --tasks "rg_*" --modes baseline,tilth --models claude-sonnet-4-6 --reps 5
copeca analyze results/bench.jsonl
copeca analyze results/bench.jsonl -o report.md
copeca compare results/v0.4.jsonl results/v0.5.jsonl
copeca verify run_20260607T120000.copeca
copeca verify --batch results/ --scenario scenarios/my.yaml
copeca inspect run_20260607T120000.copeca
copeca validate tasks/                            # static (fast)
copeca check-task tasks/ripgrep/edit_line_count.yaml   # deep: proves mutation breaks the test
copeca init ./my-benchmark
copeca list tasks
```

### JSONL Output

```json
{
  "task": "rg_trait_implementors",
  "repo": "ripgrep",
  "mode": "tilth",
  "model": "claude-sonnet-4-6",
  "runner": "claude",
  "repetition": 0,
  "timestamp": "2026-06-07T12:00:00Z",
  "correct": true,
  "correctness_detail": {
    "required_strings_passed": true,
    "all_of_passed": true,
    "forbidden_strings_passed": true,
    "test_command_passed": null
  },
  "num_turns": 6,
  "num_tool_calls": 15,
  "tool_calls": {"tilth_search": 3, "tilth_read": 5},
  "total_cost_usd": 0.0734,          // computed from tokens × pricing
  "duration_ms": 45230,              // copeca wall-clock
  "context_tokens": 28450,
  "output_tokens": 1230,
  "input_tokens": 18500,
  "cache_creation_tokens": 7200,
  "cache_read_tokens": 2750,
  "per_turn_context_tokens": [5000, 8200, 12500, 18400, 22100, 28450],
  "result_text": "The Matcher trait is defined in ...",
  "tool_sequence": [
    {"name": "tilth_search", "args": {"query": "Matcher"}}
  ],
  "error": null,
  "adversarial_flags": {
    "token_snowball": false,
    "talkative_failure": false,
    "tool_storm": false,
    "budget_exhausted": false,
    "timeout": false
  },
  "artifact_hash": null,
  "metadata": {
    "copeca_version": "0.1.0",
    "runner_version": "2.1.156",
    "task_version": 1,
    "vendor_cost_usd": 0.0731        // cross-check, if the runner reported one
  }
}
```

---

## 7. Results Integrity

### Per-run artifacts (opt-in via `--artifacts`)

```
run_20260607T120000_rg_trait_implementors_tilth_claude-sonnet-4-6_rep0.copeca
├── result.json          # JSONL record
├── stdout.txt           # Raw agent stdout
├── stderr.txt           # Raw agent stderr
├── session.json         # Parsed turns + tool calls
├── post_mutation.diff   # Edit tasks only: diff between clean repo and post-mutation state
├── manifest.json        # SHA-256 hashes + content_hash + repo commit SHA + toolchain versions
├── task.yaml            # Task definition used
├── runner.yaml          # Runner config used (incl. pricing that produced the cost)
└── repos.yaml           # Repo registry entry for this repo (single entry only)
```

**Hash chain:** `content_hash = SHA-256(concat(sorted per-file hashes))`. Every file present is covered (`post_mutation.diff` is omitted for comprehension tasks, which have no mutation). The repo commit SHA and verified toolchain versions are recorded in `manifest.json` — so a reviewer knows exactly what code and environment produced the result. Bundling `runner.yaml` (with its pricing) means the cost is recomputable from the recorded tokens.

**Verification:** `copeca verify artifact.copeca` — detects any modification.
**Inspection:** `copeca inspect artifact.copeca` — dumps session for review.

### Batch Completeness

Hash chains prevent zip tampering but don't prevent selective publishing (running 20 reps and publishing only the best). Batch verification closes this gap:

```
copeca verify --batch results/ --scenario scenarios/my.yaml
# → "Scenario expects 200 runs. Found 200 artifacts. All authentic."
# → "Scenario expects 200 runs. Found 185 artifacts. 15 missing, 0 tampered."
```

Given the scenario file, copeca computes the expected set of run IDs. Failed/timeout runs are expected to be missing — these are reported separately from tampered artifacts.

### Why Opt-In

A 40-task × 2-mode × 3-model × 5-rep matrix is 1200 runs = 1200 zips = 9600 files. For local iteration, that's noise. For publication/sharing, enable `--artifacts`.

---

## 8. Concurrency Model

Matrix runs are independent — each task × mode × model × rep combination can run in parallel. Copeca uses **git worktrees** for isolation:

- One bare clone per repo (shared object database)
- `max_workers` parallel worktrees per scenario (default: 1, sequential)
- Worktrees are **repo-affine**: a worktree serves runs for one repo only. Cross-repo reuse requires a fresh worktree.
- Pool per repo: `max_workers` worktrees are distributed across repos proportionate to the number of tasks targeting each repo

**Worktree lifecycle:**
```
Create worktree from bare clone → Run setup_command → [Reset* → Mutate → Run → Validate] × N reps
  *Reset = git reset --hard HEAD && git clean -fd (preserves node_modules/, target/, etc.)
```

(Toolchain is verified once per repo at clone time, not per worktree — the host's `rustc` is the same for every worktree.)

**Cleanup on failure:** If a run times out or crashes:
1. Kill process group (SIGKILL)
2. `git worktree remove --force <path>` (handles locked/corrupt metadata)
3. Create fresh worktree from bare clone
4. Re-run setup

This avoids corrupt `.git` state from SIGKILL'd mid-git subprocesses.

**Resource budget:** Each worktree uses ~disk space of one checkout. 4 workers × 4 repos = 16 worktrees max. Shared object database is ~50–200MB per repo.

---

## 9. Implementation Phases

### Phase 1a: Task Loading + Validation + Migration

Goal: `copeca validate tasks/` works. First 5–10 tilth tasks migrated to YAML.

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python ≥3.11, deps: typer, pyyaml, jsonschema, pydantic |
| `repos.yaml` | Repo registry with toolchain + setup_command per repo |
| `schemas/task.schema.json` | Task JSON Schema (comprehension + edit, all_of, mutations, forbidden_strings) |
| `src/copeca/cli.py` | `validate`, `list` commands only |
| `src/copeca/config/models.py` | Task, Repo, GroundTruth dataclasses |
| `src/copeca/config/loader.py` | YAML + jsonschema validation |
| `src/copeca/tasks/loader.py` | Discover and load tasks from directory |
| `scripts/migrate_from_tilth.py` | Convert tilth Python tasks → YAML (first pass) |
| `tasks/**/*.yaml` | First 5–10 migrated tasks |
| `tests/test_config_loader.py` | Valid/invalid task YAML tests |

**Acceptance:** `copeca validate tasks/` catches malformed tasks. First migrated tasks pass validation. All tests pass.

### Phase 1b: Runner + Single Task Execution

Goal: `copeca run --task ... --runner claude --model claude-sonnet-4-6` works end-to-end.

| File | Purpose |
|------|---------|
| `src/copeca/runners/base.py` | Abstract runner + parser + invoke resolution + cost computation (tokens × pricing) |
| `src/copeca/runners/subprocess.py` | Subprocess runner with process group management |
| `src/copeca/runners/parsers/stream_json.py` | Claude Code parser (all event types) |
| `src/copeca/runners/parsers/generic.py` | Configurable parser (JSONPath, declared event support) |
| `src/copeca/orchestration/run.py` | Single-run orchestrator (measures duration; computes cost) |
| `src/copeca/orchestration/state.py` | Clone → Verify toolchain → Setup → Reset → Mutate → Run → Validate |
| `src/copeca/orchestration/validation.py` | Scenario load-time warnings (task↔runner compat, mode↔runner compat) |
| `src/copeca/tasks/validator.py` | Correctness checker (strings + all_of + forbidden + test_command) + mutation-validity deep check |
| `src/copeca/tasks/mutations.py` | Apply/revert with all action types; abort on unmatched find |
| `src/copeca/repos/manager.py` | Clone, verify toolchain, create worktree, setup, reset, remove worktree |
| `src/copeca/results/writer.py` | JSONL writer |
| `src/copeca/results/artifact.py` | .copeca zip (--artifacts) with post_mutation.diff + repos.yaml + toolchain in manifest |
| `src/copeca/results/verification.py` | `copeca verify` |
| `src/copeca/cli.py` | add `run`, `check-task`, `verify` commands |
| `defaults/runners/claude.yaml` | Claude runner with supported_events, version_command, pricing |
| `defaults/modes/default.yaml` | Default mode |
| `tests/test_task_validator.py` | Correctness tests (all strategies) + mutation-validity check |
| `tests/test_runner_parsers.py` | Parser tests (stream_json + generic + error events + cost-from-tokens + vendor cross-check) |
| `tests/test_artifact_verification.py` | Tamper detection + hash chain tests |
| `tests/test_validation_warnings.py` | Scenario validation warning tests |
| `tests/fixtures/sample_stream_json.txt` | Sample Claude output |

**Acceptance:** `copeca run --task ...` produces valid JSONL with cost computed from tokens. Toolchain mismatch aborts with a clear error. `copeca verify` works. `copeca check-task` verifies an edit task's test fails-on-mutated / passes-on-clean. All correctness strategies work. All mutation actions work; an unmatched `find` aborts before the agent runs.

### Phase 2: Scenarios, Modes, Multi-Rep, Concurrency

Goal: `copeca run scenarios/my.yaml` runs the full matrix with parallel workers.

| File | Purpose |
|------|---------|
| `src/copeca/orchestration/run.py` | Matrix loop with worker pool |
| `src/copeca/orchestration/state.py` | Multi-worktree lifecycle management |
| `src/copeca/config/loader.py` | Mode + Scenario loading |
| `schemas/runner.schema.json` | Runner JSON Schema (incl. supported_events, invoke_template, pricing) |
| `schemas/scenario.schema.json` | Scenario JSON Schema (incl. adversarial_thresholds, max_workers) |
| `defaults/runners/{codex,opencode}.yaml` | Additional runner configs |
| `src/copeca/results/verification.py` | Batch completeness verification |

**Acceptance:** Full matrix runs in parallel. Worktrees provide isolation. Scenario validation catches incompatibilities. Batch verification detects missing runs.

### Phase 3: Analysis & Reporting

Goal: `copeca analyze` produces the full report.

| File | Purpose |
|------|---------|
| `src/copeca/analysis/stats.py` | Median, mean, stdev, bootstrapped 95% CI |
| `src/copeca/analysis/report.py` | Markdown report |
| `src/copeca/analysis/compare.py` | Run comparison |
| `src/copeca/cli.py` | `analyze`, `compare` commands |

**Report must include:**
- **Headline:** Cost-per-correct **delta** for each mode/model (baseline → experimental), with CI — not the bare absolute (§11)
- Per-task table: baseline vs experimental (so concentrated wins are visible)
- Cost breakdown by token category
- Per-turn context sparklines
- Tool adoption rate
- Adversarial flag summary
- Per-language, per-difficulty aggregation
- **Confidence intervals** on cost-per-correct (bootstrapped, 95% CI)

**CI limitation:** Bootstrap CIs assume i.i.d. runs. Model behavior across repetitions can be correlated (models get stuck in the same wrong reasoning path). CIs will underestimate variance when runs are correlated. The report notes this caveat.

### Phase 4: Docs, Polish, Remaining Migration

| File | Purpose |
|------|---------|
| `README.md` | Quick start, examples, security warning |
| `docs/task-authoring.md` | Task reference (all types, mutation actions, completeness, check-task) |
| `docs/runner-configuration.md` | Runner reference + output contract + cost computation |
| `docs/metrics.md` | Cost-per-correct math, delta-not-absolute, CI + i.i.d. caveat |
| `docs/methodology.md` | §11 expanded: how to read results honestly, task governance |
| `docs/known-limitations.md` | String matching, bootstrap CIs, modeled cost, no structured-output validation |
| `scripts/migrate_from_tilth.py` | Batch migrate remaining tilth tasks |
| `src/copeca/cli.py` | `init` command |
| `tests/test_orchestrator.py` | Integration tests |

**Acceptance:** All ~85 tasks validate (35 tilth migrated + 50 independent authored). Edit tasks pass `check-task`. `copeca init` bootstraps a working directory.

---

## 10. Key Design Decisions

### 1. Two task types, not three
`comprehension` and `edit` differ in validation. "Diff" tasks are edits with history-referencing prompts. The reporting infers categories from mutation presence.

### 2. Runner ≠ Model
A runner is a CLI tool. A model is what it invokes. Full model IDs (matching pricing keys) are used throughout — no alias indirection.

### 3. Repo registry with per-worktree setup
One `repos.yaml`, referenced by name. `setup_command` runs in each worktree after checkout. Dependencies persist for the worktree's lifetime.

### 4. Mutation validity is proven, not assumed
`check-task` verifies the test passes-on-clean and fails-on-mutated. Without this, an edit task with a weak test gives credit for doing nothing — SWE-bench's most damaging flaw. Run at authoring/CI time, not per-run.

### 5. Test is authoritative for edit correctness
Edit `correct` = test passed. Strings are diagnostic only. This keeps the honest signal honest (SWE-bench lesson #1) while still surfacing test/string disagreement.

### 6. Artifacts are opt-in
`.copeca` zips created when `--artifacts` is passed. Local iteration doesn't need 9600 files.

### 7. No false reproducibility promise
`copeca inspect` shows the session. No `reproduce` command — LLM runs are non-deterministic.

### 8. Per-model pricing staleness
Each model entry has an `updated` date. Warning fires per-model, not per-file.

### 9. Defined adversarial flags with null semantics
All five flags have precise definitions. Thresholds are configurable. Flags on missing data are `null`, not `false`.

### 10. Nondeterminism is a first-class concern
95% bootstrapped CIs on cost-per-correct. High variance flagged. Minimum 5 reps enforced. Bootstrap i.i.d. assumption documented.

### 11. Git worktrees, repo-affine
Isolated working directories, shared object database. Worktrees stay with one repo. Cleanup sequence handles corrupt state.

### 12. Batch completeness verification
`copeca verify --batch --scenario` checks that all expected runs exist, not just that present artifacts are untampered.

### 13. Invocation resolution: invoke_template > arg_map
`invoke_template` takes precedence. Both paths documented. Mutually exclusive in practice.

### 14. assistant_message is a required event for comprehension
Comprehension tasks cannot function without text output. Validated at scenario load time, not silently failed.

### 15. Tasks are data, not code
Correctness is strings + test commands, expressed as data — no embedded Python. If a task seems to need custom code to grade, treat that as a signal it may not be objectively gradeable, and reconsider it. (It's also a supply-chain risk: a shared task set you run locally must be safe to load.) No arbitrary-code escape hatch.

### 16. Cost is computed, not trusted
`Σ tokens × pricing`, with any vendor-reported cost used only as a cross-check. Cost reporting is inconsistent across CLIs; tokens are near-universal. Computing from one pricing source is the only basis on which cross-vendor numbers are comparable.

### 17. One execution path; environment is verified, not provided
Repos declare their toolchain; copeca verifies it and aborts on mismatch. *Provisioning* that environment (Docker, nix, asdf, bare host) is the operator's choice — copeca has no Docker mode and no `--sandbox` flag. Safety isolation for untrusted repos is also the operator's job (run copeca in a container). One code path, one result type.

### 18. LLM judges are out of the scoring path
Non-deterministic (breaks reproducibility), self-preferring (a judge favors its own model's outputs), and they reward the verbosity `talkative_failure` exists to catch. Judges are allowed only for *post-hoc* failure analysis and *authoring-time* audits (answer-leakage, string quality) — never to decide `correct`/`incorrect`.

### 19. Modes cover every integration, isolated per arm
A tool attaches via MCP, `env` (proxy), `agent_config` (config-dir hook), `wrapper` (process prefix), or `setup` (per-worktree index/install). Modes express all five, because the most popular token-savings tools are *not* MCP. Each arm runs in its own config dir and env, so the baseline is provably clean — copeca never inherits the host's ambient hooks or proxies. Per-arm isolation is what makes the one-variable A/B trustworthy. A pre-call prompt-compression field is deliberately omitted (low value on coding tasks; the proxy path covers it) — not overfitting to a tool that doesn't fit the domain.

### 20. The bundled corpus is a tool-agnostic seed, not a verdict
A benchmark whose author ships their own tool's win-set is worthless. The bundled tasks are deliberately *not* tilth-favorable: general code-comprehension and edit tasks spanning navigation, cross-file dependency/dataflow, and bug-fixing — chosen to *discriminate* between approaches, not flatter one. The seed is explicitly **not canonical**; the canonical set is versioned and meant to be governed independently of any tool (§11). For a standalone suite, neutrality is the whole game — without it, copeca is just marketing with a hash.

---

## 11. Methodology & Objectivity

Cost-per-correct is a measurement, not a verdict. Copeca makes results *reproducible and verifiable* — it cannot make task selection or ground-truth curation objective, because those are human judgments. Read results accordingly.

The metric isn't invented here: **Cost-of-Pass** (arXiv 2504.13359) formalizes cost-per-correct as `C/R` (expected cost per correct output), and **SWE-Effi** independently arrived at cost-budget framing. Copeca's contribution is operationalizing it as a living, tool-as-variable, verifiable harness — not a new metric, a missing instrument.

**Report the delta, not the absolute.** `$0.15/correct` is meaningless across task sets — it depends entirely on which tasks you chose. Only the within-study delta (baseline vs. experimental, same tasks) is comparable, and only within that study. Never compare your absolute to someone else's on a different task set.

**Equal conditions cancel shared bias — but not all bias.** Running both arms on identical tasks/prompts/repos/models cancels shared confounds (task difficulty, prompt phrasing, grader leniency) in the delta. This is why the –44% is far more trustworthy than the $0.15. It fails in exactly one way: when task *selection* is correlated with the treatment's mechanism. Benchmark a "find all callers" tool only on "find all callers" tasks and it wins by a mile — same tasks for both arms, but the selection *is* the effect.

**Per-task transparency is the guard.** copeca reports every task's result. Concentrated wins — all the improvement in a handful of tool-favorable tasks — are visible, not hidden in an average. A skeptic can see the shape of the win.

**Independent task governance is the only real fix for selection bias.** A tool author benchmarking their own tool will pick favorable tasks; no schema prevents it. The mitigation is social: a shared task set governed independently of any one tool, and pre-registering which tasks you'll run before you run them. copeca *enables* this (declarative tasks, verifiable artifacts); it cannot *enforce* it.

**What's objective vs. judged.** Edit tasks are objective — a test exit code, verified meaningful by `check-task`. Comprehension tasks are human-judged — the author picks the strings; too lenient passes wrong answers, too strict fails right ones. Use edit tasks when you need hard objectivity; use comprehension tasks knowing the ground truth is curated judgment.

The honest one-line summary: **copeca delivers objectivity-by-reproducibility, not objectivity-by-authority.** When the tool is separable from the benchmark and the artifacts are verifiable, a skeptic can re-run and check — which is the strongest form of objectivity available for a stochastic system graded against human-curated truth.

---

## 12. Migration from tilth

| tilth | Copeca |
|-------|--------|
| `benchmark/tasks/*.py` (Python subclasses) | `tasks/**/*.yaml` |
| `benchmark/config.py` (ModeConfig, RepoConfig) | `modes/*.yaml`, `repos.yaml` |
| `benchmark/run.py` | `src/copeca/orchestration/run.py` |
| `benchmark/parse.py` | `src/copeca/runners/parsers/` |
| `benchmark/analyze.py` | `src/copeca/analysis/report.py` |
| `benchmark/compare_versions.py` | `src/copeca/analysis/compare.py` |
| `benchmark/fixtures/` (repos, MCP configs) | `repos.yaml`, `modes/*.yaml` |
| `benchmark/results/*.jsonl` | Same format, enriched |

tilth already computes Codex cost from a token × pricing table — copeca generalizes that to *all* runners. Migration runs in two passes: Phase 1a (first 5–10 tasks), Phase 4 (remaining). tilth's edit/diff tasks already carry mutations + test commands, so each migrated edit task should pass `check-task` — a free validation that the migration preserved meaning.

---

## 13. Resolved Decisions

| # | Question | Decision | Why |
|---|----------|----------|-----|
| 1 | Name | `copeca` | Reserved, not yet published. |
| 2 | Python | **3.11 minimum** | 3.10 EOL Oct 2026. 3.11 EOL Oct 2027. |
| 3 | CLI | **Typer 0.26.x** | Active, vendored Click, fastapi org |
| 4 | Validation | **Pydantic v2 + jsonschema** | Pydantic 2.13.4, jsonschema 4.26.0 |
| 5 | Synthetic tasks | **No** | Real repos at pinned commits only |
| 6 | Docker | **No copeca mode** | Repos declare toolchains; copeca verifies. Provisioning (Docker/nix/host) is the operator's choice. One execution path. |
| 7 | Bundled tasks | **~85 tasks (35 tilth + 50 independent)** | ~35 migrated from tilth in two phases; ~50 authored fresh from SWE-QA, RepoQA/SCBench, Long Code Arena, SWE-bench-Live, Terminal-Bench 2.0 — permissive licenses, low contamination, attributed |
| 8 | Results integrity | **`.copeca` zips + batch** | SHA-256 + scenario-aware verification |
| 9 | Cost source | **Computed from tokens** | Vendor cost is inconsistent and non-comparable; tokens × one pricing source is |
| 10 | LLM judge | **Out of scoring** | Breaks reproducibility; analysis/authoring only |

### Known Limitations

- **String matching only** (no regex). `forbidden_strings` catches "I cannot" but misses "unable to determine." Regex support deferred.
- **No structured output validation.** Can't verify JSON/YAML correctness in agent responses. Use edit tasks with test commands for this.
- **Comprehension ground truth is curated judgment.** Objective only insofar as the author chose the strings well (§11).
- **Cost is modeled, not invoiced.** API-rate-equivalent, not your subscription bill.
- **Hidden reasoning tokens.** If a model doesn't report thinking tokens, token-based cost undercounts.
- **Bootstrap CIs assume i.i.d.** Model runs are correlated across reps (same wrong reasoning), so CIs underestimate true variance.
- **No network isolation.** Agents have internet access and could search for solutions. Inherent to CLI agents, not a copeca choice.
- **Mutation `occurrence` is manual.** Task authors must count find-string occurrences. A tool could automate this.

### Dependency Verification (2026-06-07)

| Dependency | Version | Status |
|-----------|---------|--------|
| Python | 3.14.5 (current), 3.11 (min) | 3.11 EOL Oct 2027 |
| Typer | 0.26.2 | Active, fastapi org |
| Pydantic | 2.13.4 | Active, May 2026 |
| jsonschema | 4.26.0 | Active, Jan 2026 |
| PyYAML | 6.x | Stable |
| copeca (PyPI) | — | Reserved, not yet published |
