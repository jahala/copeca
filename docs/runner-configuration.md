# Runner Configuration

How to configure and extend copeca runners. Runners are YAML-declared adapters
that wrap CLI coding agents as subprocesses.

---

## Runner YAML structure

Runner configs live in `defaults/runners/`. Each file is **the** definition of a
runner — its CLI interface and its pricing both come from this YAML, so you add
a new agent CLI by writing a YAML file, not by editing any Python. The file has
two top-level keys: a `runner:` interface block and a `pricing:` table.

```yaml
# defaults/runners/claude.yaml
runner:
  cli: claude                      # binary name; defaults to the file stem
  default_args:                    # args always prepended to the command
    - -p
    - --output-format
    - stream-json
    - --verbose
    - --dangerously-skip-permissions
  arg_map:                         # copeca parameter -> CLI flag
    model: --model
    budget: --max-budget-usd
    system_prompt: --system-prompt
    mcp_config: --mcp-config
    prompt_separator: --
  config_dir_env: CLAUDE_CONFIG_DIR  # env var carrying the per-arm config dir
  parser: stream_json              # output parser name (see Parser registry)

pricing:
  claude-sonnet-4-6:
    input: 3.00
    cache_creation: 3.75
    cache_read: 0.30
    output: 15.00
    updated: "2026-06-19"
```

`copeca run --runner <name>` resolves `<name>.yaml` (project-local
`defaults/runners/` first, then the packaged defaults) via `load_runner`, then
`build_runner` constructs a `SubprocessRunner` from it. An unknown runner name
fails loudly (exit 2); an unknown `parser` name fails loudly too.

### `runner:` interface fields

- **`cli`** — The binary to exec. Optional; defaults to the file's stem (so
  `claude.yaml` → `claude`).
- **`default_args`** — Args always prepended to the command, e.g.
  `["-p", "--output-format", "stream-json", "--verbose"]`.
- **`arg_map`** — Maps copeca parameters to this CLI's flags. Recognized keys:
  `model`, `budget`, `system_prompt`, `tools`, `mcp_config`, and the special
  `prompt_separator` (emitted right before the positional prompt, e.g. `--`).
  A flag is only emitted when copeca has a value for it.
- **`invoke_template`** — Escape hatch for CLIs whose argument shape `arg_map`
  can't express. Example: `"{cli} exec --json -m {model} -- {prompt}"`.
  Placeholders: `{cli}`, `{model}`, `{prompt}`, `{budget}`, `{system_prompt}`,
  `{tools}`, `{mcp_config}`. When present, it takes precedence over `arg_map`.
  A runner must declare **either** `arg_map` **or** `invoke_template`.
- **`config_dir_env`** — Name of the env var through which copeca delivers each
  arm's isolated agent config directory (Claude: `CLAUDE_CONFIG_DIR`). Omit for
  CLIs without a config-dir concept.
- **`parser`** — The name of the output parser (see Parser registry below). The
  named parser must be built, or `build_runner` raises.
- **`isolation`** — Per-CLI clean-room descriptor (architecture §13.4). An
  optional sub-block; omitting it yields safe empty defaults. All sub-fields are
  optional:

  | Sub-field | Type | Description |
  |---|---|---|
  | `config_home_env` | `str \| null` | Env var pointing at the per-run private config home (`CLAUDE_CONFIG_DIR` / `CODEX_HOME` / `GEMINI_CLI_HOME`). |
  | `strict_mcp_flags` | `list[str]` | Flags that force "only my MCP" (claude: `--strict-mcp-config`; codex: `--ignore-user-config`; gemini: `--allowed-mcp-server-names`). Default: `[]`. |
  | `disable_ambient_env` | `dict[str, str]` | Env vars that neutralize ambient instruction files (e.g. `{CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1"}`). Default: `{}`. |
  | `disable_session_flags` | `list[str]` | Flags that disable session persistence (e.g. `[--no-session-persistence]` / `[--ephemeral]`). Default: `[]`. |
  | `disable_telemetry_env` | `dict[str, str]` | Env vars that disable telemetry / nonessential traffic (e.g. `{CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"}`). Default: `{}`. |
  | `ambient_files` | `list[str]` | File names to scan for in the pre-run workdir (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`). Default: `[]`. |
  | `requires_api_key_env` | `str \| null` | Preflight asserts this env var is present before the run (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`). |
  | `version_cmd` | `list[str]` | Command to resolve the CLI/tool version for provenance (e.g. `[claude, --version]`). Default: `[]`. |

  Example (Claude Code):
  ```yaml
  isolation:
    config_home_env: CLAUDE_CONFIG_DIR
    strict_mcp_flags: [--strict-mcp-config]
    disable_ambient_env: { CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1" }
    disable_session_flags: [--no-session-persistence]
    disable_telemetry_env: { CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1" }
    ambient_files: [CLAUDE.md, CLAUDE.local.md]
    requires_api_key_env: ANTHROPIC_API_KEY
    version_cmd: [claude, --version]
  ```

  Validated by the `IsolationSpec` Pydantic model at load time — no separate
  JSON schema exists for runner configs (Pydantic is the validator, per
  engineering.md §12).

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

These rates produce `computed_cost_usd` (Σ tokens × rates) — the reproducible,
provider-neutral cost used as a cross-check and as the fallback when a runner
reports no cost of its own. The headline `total_cost_usd` is the vendor's billed
cost when reported. A staleness warning fires if `updated` is older than 30 days
(`architecture.md` invariant 2).

---

## The SubprocessRunner

`src/copeca/runners/subprocess.py:SubprocessRunner` is the default adapter.
It spawns the CLI agent as a subprocess with process-group isolation:

- **Process-group isolation** — `preexec_fn=os.setsid` creates a new session.
  On timeout, `os.killpg()` kills the entire process group, not just the
  parent. No orphaned children.
- **Env allowlist** — The child process receives an explicit, minimal
  environment built from `BASE_ENV_ALLOWLIST` (infra vars, locale `LC_*`, and
  provider credentials). Everything else — `CLAUDECODE`, `CLAUDE_*`, `MCP_*`,
  and arbitrary ambient hooks — is excluded. Per-arm `mode.env` vars are merged
  on top so only declared tool vars reach the experimental child.
- **Timeout** — `subprocess.communicate(timeout=...)` with a configurable
  `timeout_seconds` (default 300). On expiry, the process group is SIGKILL'd.

---

## Parser registry

A runner names its output parser by string (`parser: <name>` in the YAML). The
registry in `src/copeca/runners/parsers/__init__.py` maps that name to a `Parser`
implementation; `build_runner` resolves it via `get_parser(name)` and injects the
instance into the `SubprocessRunner`.

Shipped parsers:

- **`stream_json`** (`StreamJsonParser`) — Parses Claude Code's verbose
  stream-json output (`--output-format stream-json --verbose`). Extracts `Turn`
  objects (token counts per turn), `ToolCall` objects, and the final result text.

A CLI with a different output format needs a matching parser — these are not yet
built. `get_parser` raises `ParserNotFoundError` for an unknown name, so a runner
YAML pointing at an unbuilt parser fails loudly instead of silently producing a
parserless (zero-token) result. To add one:

1. Implement `parse(stdout: str, supported_events: list[str] | None) -> RunResult`
   (the `Parser` protocol) in `runners/parsers/`.
2. Register it in `_PARSERS` in `runners/parsers/__init__.py` (`name -> class`).
3. Set `parser: <name>` in the runner YAML.

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
| MCP server | `mcp_config` | Write MCP config JSON to the per-arm dir; path passed via the runner's configured MCP arg |
| API proxy | `env` | Set env vars for the subprocess |
| Config-dir hook | `agent_config` | Overlay a `settings.json` into the arm's config dir |
| Process wrapper | `wrapper` | Prefix the runner command (e.g. `["your-wrapper-tool", "wrap"]`) |
| Pre-run index | `setup` | Run a per-worktree pre-step command |

Each mode arm gets its own config directory and an allow-listed environment.
The baseline arm's child receives only the allowlist vars; the experimental
arm's child receives the allowlist plus whatever its `mode.env` declares.
Ambient host vars outside the allowlist never reach either arm.

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
- [README.md](../README.md) — runners (config-driven), output contract, install
