# copeca &middot; cost per correct answer

A neutral, reproducible, verifiable benchmark for CLI-based coding agents.  
Copeca measures **cost per correct answer** — the expected dollar cost before
getting a right answer — to A/B-compare MCP servers, context compressors,
hooks, and harness improvements against a clean baseline.

```
cost_per_correct = total_spend / correct_count
```

**Why this metric.** "-90% tokens removed!" is a marketing number if it ignores
whether the answer was *right*. A tool that saves 90% of tokens but makes
20% more mistakes has worse cost-per-correct. Copeca adjusts every savings
claim for accuracy, so the number you get is the number that actually matters.

**Why a separate benchmark.** Every tool in the ~45-tool agent-efficiency space
reports savings on its own methodology against its own baseline — the numbers
are literally incomparable. Copeca holds the agent and model fixed and varies
*one tool*, answering "did my tool help, and what did it cost?" No existing
benchmark occupies that lane.

---

## Quick start

```bash
pip install copeca
copeca init ./my-benchmark
copeca run scenarios/my-scenario.yaml
copeca analyze results/bench.jsonl
```

A scenario file defines what to measure:

```yaml
name: my-tool-vs-baseline
tasks:
  include: ["rg_*", "fastapi_*"]
modes: [baseline, my-tool]
models: [claude-sonnet-4-6]
model_runner_map:
  claude-sonnet-4-6: claude
repetitions: 5
budget_usd: 1.00
```

The report leads with the cost-per-correct delta between your tool and the
baseline, with 95% bootstrapped confidence intervals, per-task breakdowns,
and adversarial flags that catch token snowballing and expensive failures.

**Current corpus size: 16 tasks.** The roadmap targets ~85 tasks across 6
independent source families. Until the corpus grows, statistical power is
limited — small N means wide confidence intervals. See
[docs/known-limitations.md](docs/known-limitations.md) for details.

---

## What copeca measures

| Dimension | How |
|---|---|
| **Cost** | `Σ tokens × runner.pricing[model]` — computed, never trusted from vendor self-reported numbers |
| **Correctness** | String matching (comprehension tasks) or test-command exit codes (edit tasks) |
| **Completeness** | `all_of` field verifies the agent listed *everything* — not just *something* |
| **Futility** | Adversarial flags: token snowball, talkative failure, tool storm, budget exhaustion, timeout |
| **Integrity** | `.copeca` artifact zips with SHA-256 hash chains; `copeca verify --batch` proves nothing was cherry-picked |

---

## Who copeca is for

**Tool builders** — MCP/server authors, context compressor developers, code-search
tool maintainers. You ship a tool and need a number that isn't marketing. Copeca
gives you cost-per-correct with a delta and CI, and a `.copeca` zip anyone can
verify.

**Platform builders** — CLI agent authors (Codex, OpenCode, Gemini CLI style).
You need to validate that your pricing model is accurate before customers depend
on it. Copeca normalizes cost across providers and warns when pricing data is
stale.

**Skeptical evaluators** — Researchers, reviewers, procurement leads. You've
been burned by contaminated benchmarks and cherry-picked results. Copeca's
artifact model and batch completeness verification let you check every claim.

---

## How copeca works

Copeca launches a CLI coding agent as a subprocess against a real open-source
repo pinned at a known commit. The agent answers a question or fixes a bug.
Copeca parses the agent's output, checks correctness, computes cost from token
counts, and writes a JSONL record. A scenario runs the matrix of tasks × modes
× models × repetitions with parallel git-worktree-isolated workers.

**Modes** express the *one variable* that changes between baseline and
experimental. They cover all five integration types real tools use:

| Integration | Mode field | Example |
|---|---|---|
| MCP server | `mcp_config` | tilth, sigmap |
| API proxy | `env` | Context Gateway, Entroly |
| Config-dir hook | `agent_config` | RTK |
| Process wrapper | `wrapper` | `headroom wrap claude` |
| Pre-run index | `setup` | claude-context, GrepAI |

Copeca provisions each arm with its own config directory and environment, so
the baseline is provably clean — it never inherits the host's ambient hooks.

---

## Task corpus

Tasks are YAML data — no embedded code, no Docker per task. They target real
open-source repos at pinned commits. The current seed corpus is **16 tasks**
from the `SWE-QA (Apache-2.0)` source family, with **5 additional source
families planned** (SCBench, Long Code Arena, CrossCodeEval,
SWE-bench-Live, Terminal-Bench 2.0). Each task carries a
`source:` field with provenance attribution. Every edit task is verified by
`copeca check-task`: the test must pass on clean code and fail on mutated
code, proving the mutation actually bites.

**Contamination self-check:** before a task enters the corpus, copeca probes
the model with the task ID alone — if it reproduces the gold solution from
memory, the task is excluded. The task types that were formally deprecated
by their own creators (SWE-bench Verified, Feb 2026) are explicitly blocked.

---

## Runner output contract

To add a new runner, its CLI must output JSON events on stdout. Copeca
requires the *minimum*: token counts. Cost, duration, and completion are
all derived — never trusted from vendor self-reports.

```jsonl
{"type": "turn", "input_tokens": 5000, "output_tokens": 200,
 "cache_creation_tokens": 3500, "cache_read_tokens": 3000}
{"type": "assistant_message", "text": "...", "turn": 2}
{"type": "result", "total_cost_usd": 0.0734, "duration_ms": 45230}
```

Built-in parsers: `stream_json` (Claude Code), `codex_json` (Codex), `generic`
(configurable JSONPath mappings).

---

## Install

```bash
pip install copeca
```

Requires Python ≥ 3.11. See [docs/runner-configuration.md](docs/runner-configuration.md)
for setting up runners (Claude Code, Codex, etc.).

---

## Documentation

- [Task authoring guide](docs/task-authoring.md) — write comprehensions and edits
- [Runner configuration](docs/runner-configuration.md) — output contract, pricing
- [Metrics & methodology](docs/metrics.md) — cost-per-correct math, delta-not-absolute
- [Known limitations](docs/known-limitations.md) — string matching, bootstrap CIs, modeled cost

---

## License

MIT — see [LICENSE](LICENSE).

Copeca's bundled task corpus is derived from independent benchmark sources
under permissive licenses (Apache-2.0, MIT, CC BY 4.0). Each task carries a
`source:` field with provenance. Tasks from NonCommercial, ShareAlike, or
no-license sources are explicitly excluded.

---

## Related

Copeca is part of the [plotplot](https://github.com/plotplot-ai) garden of
tools for building with AI. Siblings: [tilth](https://github.com/jahala/tilth)
(AST-aware code intelligence for agents), [petals](https://github.com/jahala/petals)
(brand intelligence for agents), [tend](https://github.com/jahala/tend)
(feature mapping across sessions).
