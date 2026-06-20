# Runner Configuration

How to configure and extend copeca runners. Runners are YAML-declared adapters
that wrap CLI coding agents as subprocesses.

---

## Runner YAML structure

Runner configs live in `defaults/runners/`. Each file defines a runner's CLI,
invocation conventions, pricing, and output parser:

```yaml
# defaults/runners/claude.yaml
pricing:
  claude-sonnet-4-6:
    input: 3.00
    cache_creation: 3.75
    cache_read: 0.30
    output: 15.00
    updated: "2026-06-19"
```

The runner is wired in `cli.py` at startup with `arg_map` and `invoke_template`:

- **`arg_map`** — Dict mapping copeca parameters to CLI flags. The built-in
  Claude runner uses `{"model": "--model", "budget": "--max-budget-usd",
  "system_prompt": "--system-prompt", "prompt_separator": "--"}`.
  `prompt_separator` is special: it goes before the positional prompt.
- **`invoke_template`** — Escape hatch for non-standard CLI conventions.
  Example: `"{cli} exec --json -m {model} -- {prompt}"`. Available
  placeholders: `{cli}`, `{model}`, `{prompt}`, `{budget}`, `{system_prompt}`,
  `{tools}`, `{mcp_config}`. When present, `invoke_template` takes precedence
  over `arg_map`.
- **`default_args`** — Args always prepended to the command.
  Example: `["-p", "--output-format", "stream-json", "--verbose"]`.

---

## Pricing tables

Pricing lives in `defaults/runners/<runner>.yaml` under the `pricing` key.
Each model has per-million-token rates:

| Field | Description |
|---|---|
| `input` | USD per 1M input tokens |
| `output` | USD per 1M output tokens |
| `cache_creation` | USD per 1M cache write tokens |
| `cache_read` | USD per 1M cache read tokens |
| `updated` | ISO date of last price update |

Cost is computed from token counts and these rates — never from vendor
self-reported cost. A staleness warning fires if `updated` is older than
30 days (`architecture.md` invariant 2).

---

## The SubprocessRunner

`src/copeca/runners/subprocess.py:SubprocessRunner` is the default adapter.
It spawns the CLI agent as a subprocess with process-group isolation:

- **Process-group isolation** — `preexec_fn=os.setsid` creates a new session.
  On timeout, `os.killpg()` kills the entire process group, not just the
  parent. No orphaned children.
- **Env filtering** — The `CLAUDECODE` env var (used by Claude's nested-agent
  detection) is stripped before subprocess launch, allowing `claude -p` to
  run inside a Claude Code session.
- **Timeout** — `subprocess.communicate(timeout=...)` with a configurable
  `timeout_seconds` (default 300). On expiry, the process group is SIGKILL'd.

---

## Parser injection

Each runner gets a parser that transforms raw stdout into a `RunResult`:

- **`StreamJsonParser`** (`stream_json`) — Parses Claude Code's verbose
  stream-json output (`--output-format stream-json --verbose`). Extracts
  `Turn` objects (token counts per turn), `ToolCall` objects, and the final
  result text.
- **`CodexJsonParser`** (`codex_json`) — Parses Codex output format.
- **`GenericParser`** (`generic`) — Configurable JSONPath mappings for custom
  CLI agents.

The parser is injected at construction: `SubprocessRunner(parser=StreamJsonParser())`.
If no parser is provided, the raw stdout becomes `result_text` with zero token counts.

---

## GitWorktreeManager

`src/copeca/repos/manager.py:GitWorktreeManager` provides isolated workspaces:

1. **Bare clone** — On first use of a repo key, clones the repo as a bare
   clone into `repos/_bare/<key>/`. The bare clone shares disk across all
   worktrees.
2. **Worktree creation** — `git worktree add --detach` at the pinned commit
   into `repos/_worktrees/<key>-worktree/`.
3. **Reset** — After each run: `git reset --hard HEAD` then `git clean -fd`.
   Uses `-fd` not `-fdx` to preserve ignored directories (`node_modules/`,
   `target/`, `vendor/`).
4. **Pruning** — Stale worktrees are removed via `git worktree remove --force`
   with a fallback to manual cleanup and `git worktree prune`.

Two workers never share a worktree. The bare clone provides a shared object
database; each worktree has an independent working directory.

---

## Mode mechanism: 5 integration paths

Modes express the *one variable* that changes between baseline and
experimental. The five paths cover every real tool found in the landscape
survey (`README.md`):

| Integration | Mode field | What it does |
|---|---|---|
| MCP server | `mcp_config` | Write MCP config JSON into the worktree |
| API proxy | `env` | Set env vars for the subprocess |
| Config-dir hook | `agent_config` | Overlay a `settings.json` into the arm's config dir |
| Process wrapper | `wrapper` | Prefix the runner command (e.g. `headroom wrap claude`) |
| Pre-run index | `setup` | Run a per-worktree pre-step command |

Each mode arm gets its own config directory and environment. The baseline
arm is provably clean — it gets an empty config directory and no mode
provisioning.

---

## Output contract

Every runner must emit these token counts (or zero if not available) in its
parsed `RunResult`:

| Field | Type |
|---|---|
| `input_tokens` | int |
| `output_tokens` | int |
| `cache_creation_tokens` | int |
| `cache_read_tokens` | int |
| `result_text` | str |
| `duration_ms` | int |

These are the *minimum* — the cost model, adversarial flags, and correctness
checker all derive from them. Fields the runner cannot provide are zero, not
null (`architecture.md` invariant 2 — cost is always computed).

---

## References

- [architecture.md](architecture.md) §2 — ports-and-adapters, extension points
- [engineering.md](engineering.md) §4 — MCP & subprocess rules
- [README.md](../README.md) — runner output contract, install
