# copeca &middot; cost per correct answer

[![Live site](https://img.shields.io/badge/live_site-1F8A7B?logo=githubpages&logoColor=white)](https://jahala.github.io/copeca/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/jahala/copeca/ci.yml?branch=master)](https://github.com/jahala/copeca/actions)

🌱 **[What is copeca? →](https://jahala.github.io/copeca/)** &nbsp;·&nbsp; the visual overview

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
git clone https://github.com/jahala/copeca && cd copeca
pip install -e .
copeca init ./my-benchmark
copeca run --task scenarios/my-scenario.yaml --runner claude
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
baseline, with 95% bootstrapped confidence intervals, per-task and
**per-capability** breakdowns (locate / trace / fix / debug — *where* the tool
helps, not just an overall number), and adversarial flags that catch token
snowballing and expensive failures.

**Current corpus: 52 tasks** across four real repos (ripgrep, gin, express,
fastapi — Rust, Go, JavaScript, Python), each tagged by capability so the report
shows where a tool helps. Broader coverage is on the roadmap; small N still means
wide confidence intervals — see
[docs/known-limitations.md](docs/known-limitations.md).

---

## What copeca measures

| Dimension | How |
|---|---|
| **Cost** | The vendor's billed cost when the runner reports it (the real bill — reflects cache TTL/tier/discounts; frozen into the artifact at run time). copeca also records a reproducible, provider-neutral cross-check: `computed_cost_usd = Σ tokens × runner.pricing[model]`. Token counts are read from the agent CLI and not re-tokenized — see known-limitations. |
| **Correctness** | String matching (comprehension tasks) or test-command exit codes (edit tasks) (case-insensitive substring matching — gameable on single tasks; see known-limitations) |
| **Completeness** | `all_of` field verifies the agent listed *everything* — not just *something* |
| **Futility** | Adversarial flags: token snowball, talkative failure, tool storm, budget exhaustion, timeout |
| **Integrity** | Each result is packaged with an integrity manifest — a SHA-256 hash of every file in the artifact. `copeca verify ARTIFACT` recomputes these to detect accidental corruption. The manifest alone is **not tamper-proof**: anyone who rewrites the zip can recompute it. For real tamper-evidence, sign artifacts with `copeca run … --artifacts --sign-key <private.pem>` — this writes a detached **Ed25519** signature over the content hash, and `copeca verify ARTIFACT --pubkey <public.pem>` rejects any artifact a holder of the private key did not sign (so a tampered-and-recomputed artifact fails). Unsigned artifacts get corruption detection only and are reported as unsigned. External transparency-log anchoring is a further planned option. |

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
been burned by contaminated benchmarks and selectively reported results. Copeca's
artifact model lets you verify any individual result; batch completeness verification
(`copeca verify --batch --scenario <path>`) confirms all expected runs are present
and names any specific missing runs.

---

## How copeca works

Copeca launches a CLI coding agent as a subprocess against a real open-source
repo pinned at a known commit. The agent answers a question or fixes a bug.
Copeca parses the agent's output, checks correctness, computes cost from token
counts, and writes a JSONL record. A scenario runs the matrix of tasks × modes
× models × repetitions with parallel git-worktree-isolated workers. A validity
gate confirms the experimental arm actually used its tool before its result
counts — so a win can't be credited to a tool that never ran.

**Modes** express the *one variable* that changes between baseline and
experimental. They cover all five integration types real tools use:

| Integration | Mode field | Example |
|---|---|---|
| MCP server | `mcp_config` | any MCP server |
| API proxy (env) | `env` | `ANTHROPIC_BASE_URL` proxy |
| Config-dir hook | `agent_config` | PreToolUse hook via settings overlay |
| Process wrapper | `wrapper` | `["your-wrapper-tool", "wrap"]` |
| Pre-run index | `setup` | per-worktree indexing command |

Copeca provisions each arm with its own config directory and an allow-listed
environment. The baseline arm receives only a minimal set of host vars (infra,
locale, and provider credentials); all ambient hooks, `CLAUDE_*` vars, and
`MCP_*` vars are excluded. Experimental modes may declare additional vars via
`mode.env`, which are merged on top.

---

## Task corpus

Tasks are YAML data — no embedded code, no Docker per task. They target real
open-source repos pinned at exact commits (per task, so one repo can serve
several code states). The corpus is **52 tasks** across ripgrep, gin, express,
and fastapi — drawn from six public source families plus a set migrated from the
tilth benchmark (MIT); each carries a `source:` field with provenance and a
`category` (locate / trace / fix / debug). Tasks are **tool-agnostic** — they name
the information required, never the method, so no tool is privileged; `copeca
validate` lints for it. Every edit task is verified by `copeca check-task`: the
test must pass on clean code and fail on mutated code, proving the mutation
actually bites. See [docs/task-taxonomy.md](docs/task-taxonomy.md).

**Contamination defense:** `copeca validate` checks every task's `source:`
field against a blocklist of known-contaminated source benchmarks (SWE-bench
Verified, RepoBench, ClassEval, DevEval, CoderEval). A task from any of
these sources is rejected before it can enter the corpus. This is a static
provenance check — no model calls, no network. A planned authoring-time
option (requires an API key) will also probe a live model with the task ID
and exclude it if the model reproduces the gold solution from memory; that
feature is not shipped yet.

---

## Runners

The runner interface is **config-driven**: a runner is a YAML file in
`defaults/runners/` declaring the CLI binary, its argument mapping, its config-dir
env var, and which output parser to use — plus a pricing table. Copeca builds the
subprocess invocation from that YAML, so adding an agent CLI means writing a YAML,
not editing copeca's code. See
[docs/runner-configuration.md](docs/runner-configuration.md).

To compute cost, copeca requires the *minimum* from the agent's output: token
counts. From those it derives `computed_cost_usd` — a reproducible, provider-neutral
cross-check; when the runner also reports its own billed cost, that vendor figure is
the headline. Duration and completion are derived from the output too.

```jsonl
{"type": "turn", "input_tokens": 5000, "output_tokens": 200,
 "cache_creation_tokens": 3500, "cache_read_tokens": 3000}
{"type": "assistant_message", "text": "...", "turn": 2}
{"type": "result", "total_cost_usd": 0.0734, "duration_ms": 45230}
```

Two runners ship today: **Claude Code** (`stream_json` parser) and **OpenAI
Codex** (`codex_json` parser) — each added as a YAML plus a parser, with no
changes to copeca's core. A CLI with a different output format needs a matching
parser, and a runner YAML naming an unbuilt parser fails loudly rather than
silently miscounting.

---

## Install

A built wheel bundles its runtime data (`schemas/`, `tasks/`, `defaults/`, and
`repos.yaml`), so a pip install is fully functional — `copeca init`, `validate`,
and `run` work off the packaged corpus. Copeca is **not** published on PyPI yet,
so install from git or a source checkout:

```bash
pip install git+https://github.com/jahala/copeca
```

Or from a clone (use `-e` for development):

```bash
git clone https://github.com/jahala/copeca
cd copeca
pip install .
```

Requires Python ≥ 3.11. The Claude Code and Codex runners ship ready to use; the
runner interface is config-driven, so other CLIs are added by writing a YAML (and,
if their output format differs, a parser). See
[docs/runner-configuration.md](docs/runner-configuration.md).

---

## Documentation

- [Task authoring guide](docs/task-authoring.md) — write comprehensions and edits
- [Runner configuration](docs/runner-configuration.md) — output contract, pricing
- [Metrics & methodology](docs/metrics.md) — cost-per-correct math, delta-not-absolute
- [Known limitations](docs/known-limitations.md) — string matching, bootstrap CIs, modeled cost

---

## Support

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/jahala)

## License

MIT — see [LICENSE](LICENSE).

Copeca's bundled task corpus is derived from independent benchmark sources
under permissive licenses (Apache-2.0, MIT, CC BY 4.0). Each task carries a
`source:` field with provenance. Tasks from NonCommercial, ShareAlike, or
no-license sources are explicitly excluded.

---

## Related

Copeca is part of the [plotplot](https://github.com/plotplot-ai) garden of small,
sharp tools for building with AI. Siblings:
[tilth](https://github.com/jahala/tilth) (AST-aware code intelligence),
[umbel](https://github.com/jahala/umbel) (drive many agent CLIs from one session),
[pleach](https://github.com/jahala/pleach) (conduct agent work in isolated worktrees),
[petals](https://github.com/jahala/petals) (brand intelligence),
[tend](https://github.com/jahala/tend) (feature mapping across sessions).
