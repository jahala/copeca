# Cross-CLI Run Isolation — Research Findings

**Date:** 2026-06-22
**Trigger:** The full-haiku run's baseline arm was contaminated — it called host
`tilth` MCP tools (170× `tilth_read`, 150× `tilth_search` across 45/58 baseline
runs) because Claude Code reads MCP servers from the host `~/.claude.json`, a
**config file** the env allowlist does not touch. The A/B was void. This is the
root-cause research for a uniform, multi-vendor isolation architecture so it
cannot recur on any CLI.
**Method:** three parallel research tracks (2026 docs + installed `--help`):
claude+codex, gemini+opencode, landscape+prior-art.
**Reading note:** rows marked *(inferred)* or *(needs test)* are NOT verified —
treat them as hypotheses to confirm empirically before relying on them.

---

## 1. The problem, stated precisely

copeca holds agent + model + corpus + baseline fixed and varies **one** thing
(the tool/MCP under test). That experiment is only valid if **every run receives
exactly the tools/MCP/instructions copeca declares — and nothing from the host.**
The contamination proved the current isolation story (env allowlist + worktrees +
per-arm config dir) has four blind spots:

1. **Config files**, not just env vars, carry MCP servers (`~/.claude.json`,
   `~/.codex/config.toml`, `~/.config/opencode/opencode.json`).
2. **Ambient instruction files** the agent auto-loads (`CLAUDE.md`, `AGENTS.md`,
   `GEMINI.md`) inject context/tool-bias the baseline must not have. Agent C
   called this "the most overlooked contamination vector."
3. **Session/state persistence** can carry context across runs.
4. **No post-hoc check** verified the baseline was actually clean — copeca trusted
   a flag (`tool_adopted`, null for baseline) instead of the raw tool trace.

A correct architecture closes all four, uniformly, across vendors.

---

## 2. The universal isolation contract

Nine dimensions must be controlled on **every** run regardless of CLI. This is the
vendor-neutral contract; §3 is how each CLI satisfies it.

| Dimension | What must hold | copeca today |
|---|---|---|
| **Config root** | CLI reads settings/auth/MCP/sessions from a fresh empty dir, not the host | partial (`config_dir_env` exists, not always set, claude-incomplete) |
| **MCP servers** | exactly copeca's declared set; baseline = none | ❌ (no strict flag → host leak) |
| **Ambient instructions** | no `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` reaches the agent | ❌ (none disabled; no system prompt set) |
| **Tool allowlist** | only the declared built-in tools | partial (`tools` arg exists) |
| **Session/state** | no carryover between runs | ❌ (no `--no-session-persistence`/`--ephemeral` for claude) |
| **Working dir** | fresh checkout at pinned commit | ✅ per-item clones (RUN-CLONE) |
| **Model** | pinned via flag every invocation | ✅ |
| **Environment** | scrubbed allowlist; no ambient keys/hooks | ✅ `BASE_ENV_ALLOWLIST` |
| **Telemetry/auto-update** | no side-channel noise or mid-run binary change | ❌ (not disabled) |

**Verdict:** copeca already exceeds prior art on two dimensions (per-item clones,
strict env allowlist) and is missing four (strict-MCP, ambient instructions,
session, telemetry) plus has the config-root only half-wired.

---

## 3. Per-CLI translation matrix

How each CLI satisfies the contract. **The primary lever for most CLIs is a single
config-root env var** pointed at a fresh per-run dir; Claude Code is the exception
(needs a combination because `CLAUDE_CONFIG_DIR` doesn't cover everything).

### Claude Code (v2.1.183)

| Dimension | Mechanism |
|---|---|
| Config root | `CLAUDE_CONFIG_DIR=<fresh>` redirects `~/.claude.json` (MCP) — but **NOT** `~/.claude/settings.json` *(verify it has no `mcpServers`)* |
| MCP strict | `--strict-mcp-config` (only `--mcp-config` servers; ignores `~/.claude.json`, `.mcp.json`, settings, plugins) — **the canonical fix** |
| MCP inject (tool arm) | `--mcp-config <file>` (+ keep `--strict-mcp-config`) |
| Ambient instructions | `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (disables user + project `CLAUDE.md`) |
| Tool allowlist | `--allowedTools` / `--disallowedTools "mcp__*"` / `--tools` |
| Session | `--no-session-persistence` (or `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`) |
| Telemetry | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` |
| Sandbox | `--dangerously-skip-permissions` |
| System prompt | `--system-prompt` / `--append-system-prompt` |
| Headless+JSON | `-p --output-format stream-json --verbose` |
| Version | `claude --version` |

*Belt-and-suspenders:* `--bare` skips auto-discovery of hooks/skills/plugins/MCP/
auto-memory/CLAUDE.md in one flag — but it disables a lot; `--strict-mcp-config` +
`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` are the targeted controls. *(needs test:
whether `--bare` also suppresses `.mcp.json`; `--strict-mcp-config` makes it moot.)*

### OpenAI Codex (v0.133.0)

| Dimension | Mechanism |
|---|---|
| Config root | `CODEX_HOME=<fresh>` redirects the whole `~/.codex/` tree (config, auth, sessions, MCP) |
| MCP strict | `--ignore-user-config` (skip `~/.codex/config.toml`) — **no global "ignore all MCP" flag** |
| MCP inject (tool arm) | `-c mcp_servers.<name>.command=...` `-c mcp_servers.<name>.args=[...]` |
| Ambient instructions | `CODEX_HOME` fresh dir has no `AGENTS.md` — but a worktree `AGENTS.md` still loads; **no confirmed suppression flag** *(needs test: `-c model_instructions_file=/dev/null`)* |
| Tool allowlist | sandbox-policy based (`-s read-only|workspace-write|danger-full-access`); per-server `enabled_tools`/`disabled_tools` |
| Session | `--ephemeral` |
| Auth caveat | `auth.json` does NOT fall back when `CODEX_HOME` is fresh → use `OPENAI_API_KEY` env (issue #15410) |
| Headless+JSON | `codex exec --json` |
| System prompt | none → prepend to prompt (`prepend_system_prompt: true` — copeca already does this) |
| Version | `codex --version` |

*(needs test: project `.codex/config.toml` still loads under `--ignore-user-config`
— ensure worktrees contain none.)*

### Gemini CLI (v0.44.0)

| Dimension | Mechanism |
|---|---|
| Config root | `GEMINI_CLI_HOME=<fresh>` redirects ALL user config (settings, sessions, extensions, skills) — **confirmed by experiment** |
| MCP strict | `--allowed-mcp-server-names` (allowlist; empty = none) |
| MCP inject (tool arm) | **no `--mcp-config` flag** → write `mcpServers` into `<GEMINI_CLI_HOME>/.gemini/settings.json` before the run, then allow it by name |
| Ambient instructions | `GEMINI.md` auto-walks from cwd → neutralize via `context.fileName` override in the scoped settings, or clean worktree |
| Tool allowlist | `--policy <file>` (TOML; `mcp_*` deny rules) |
| Session | `--session-id <uuid>` (fresh per run) |
| Trust gate | `GEMINI_CLI_TRUST_WORKSPACE=true` **required** alongside `--yolo` or it reverts to prompting |
| Sandbox | `--yolo` (auto-approve) |
| Headless+JSON | `-p "<prompt>" --output-format json` |
| Cost | **no USD field** — compute from `stats.models.<m>.tokens.*` (cost_source="modeled") |
| Version | `gemini --version` |

### OpenCode (v1.15.12) — defer (tier 3)

No config-root redirect. `OPENCODE_CONFIG_CONTENT='{"mcp":{...},"instructions":[]}'`
inline override is the only lever, and **merge-vs-replace semantics are
undocumented** *(needs test)*. Cost is in `step_finish.part.cost` but a known bug
(#26855) can drop the final event. Benchmarkable, but the weakest isolation story —
defer until tier-1/2 are solid.

### Other tier-1 CLIs (data-only descriptors when needed)

All share the **`<CLI>_HOME`-style config-root** pattern, which makes them cheap to
add once the abstraction exists:

| CLI | Config root | Ambient disable | Headless / JSON |
|---|---|---|---|
| Cline 2.0 | `CLINE_DIR` | *(none documented)* | `--no-interactive --json` |
| Goose (Block) | `GOOSE_CONFIG_DIR` | *(none documented)* | `goose run -t … --format json` |
| GitHub Copilot CLI | `COPILOT_HOME` | `--no-custom-instructions` (cleanest) | `-p --output-format=json` |
| Amp (Sourcegraph) | *(none; `--settings-file`)* | run from clean dir | `-x --stream-json` |
| aider | stateless by design | `--config /dev/null` | subprocess, `--yes` |

---

## 4. The architecture spine: two layers of defense

The core design. **Prevention** stops contamination per-CLI; **detection** is the
vendor-neutral backstop that catches any prevention gap — including on CLIs that
lack a strict-isolation flag (gemini, codex AGENTS.md, opencode).

### Layer 1 — Prevention (per-run clean room)

For every run (baseline AND tool arm), before exec:
1. Create a **fresh empty config home**; point the CLI's config-root env var at it.
2. Apply **strict-MCP**: baseline gets zero servers; tool arm gets exactly the
   declared set.
3. **Neutralize ambient instructions** (disable env/flag + a clean worktree).
4. **Disable session/state** and **telemetry/auto-update**.
5. Apply the **tool allowlist**, **pinned model**, **scrubbed env** (already done),
   **clean worktree at pinned commit** (already done).

### Layer 2 — Detection (post-hoc, universal)

1. **Pre-run workdir scan** — refuse the run (`CONTAMINATED_WORKDIR`) if the
   worktree tree contains ambient instruction files copeca cannot disable for that
   CLI.
2. **Symmetric trace gate** — after parsing the trace:
   - baseline `tool_calls ∩ tool-under-test == ∅` else `CONTAMINATED_TRACE`
     (exclude from the delta);
   - tool arm used the tool ≥1 (`tool_adopted`).
   This is the guard that would have caught this incident, and it works on any CLI
   because it reads the trace, not the flags. Agent C: *"post-hoc trace
   verification is the safety net that makes Docker optional for copeca."*

### The descriptor (data, not code)

Each runner YAML gains an `isolation:` block — one descriptor per CLI; the
orchestrator reads the contract and applies it uniformly. Sketch:

```yaml
isolation:
  config_home_env: CLAUDE_CONFIG_DIR
  strict_mcp_flags: [--strict-mcp-config]
  disable_ambient_env: { CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1" }
  disable_session_flags: [--no-session-persistence]
  disable_telemetry_env: { CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1" }
  ambient_files: [CLAUDE.md, CLAUDE.local.md]   # for the pre-run scan
  version_cmd: [claude, --version]              # provenance
```

This is the literal expression of "consistent environment across vendors": one
contract, N data descriptors, no per-CLI branches in the orchestrator (preserves
architecture invariant #4, one execution path).

### Version provenance

Record the resolved tool-under-test version and each CLI version per record (run
`version_cmd`). Answers "which version was tested" and makes the artifact
self-documenting — tilth's own benchmark records `tilth_version`; copeca does not.

---

## 5. Prior art

- **SWE-bench / Terminal-Bench:** per-task pinned Docker image (sha256-digest, not
  tag), git history trimmed to the task commit, **network allowed for both arms
  equally**. Isolation = container + pinned commit. They verify the *final state*,
  not *which tools were used*.
- **Harness-Bench (arXiv 2605.27922):** the scientific justification for copeca.
  Models `Agent = Model + Harness`; holds task/sandbox/budget/timeout/evaluator
  fixed, varies the harness. Performance ranged **52.4%–76.2%** across harnesses
  with identical model+task — the harness is the dominant variable. copeca's
  "vary one tool" design is exactly this discipline.
- **The copeca edge:** copeca captures the execution **trace**, so it can verify
  *which* tools each arm used — something SWE-bench's final-state check cannot.
  That makes the post-hoc symmetric gate (Layer 2) a stronger contamination check
  than container isolation alone, and it is why copeca's deliberate **no-Docker**
  choice (architecture.md invariant #4, §8) stands: worktrees + two-layer defense
  give the guarantee without a second execution path. Docker remains a documented
  non-goal.

---

## 6. CLI landscape & support ranking

Priority for copeca, by isolation cleanliness × credibility × current support:

1. **Claude Code** — supported; deepest isolation surface.
2. **OpenAI Codex** — supported; `CODEX_HOME` makes clean-room trivial.
3. **Gemini CLI** — `GEMINI_CLI_HOME` confirmed clean; the right **third** CLI and
   the proof the abstraction generalizes beyond two.
4. Cline · 5. Goose · 6. Copilot CLI · 7. Amp · 8. aider — all data-only
   descriptors once the abstraction lands; add on demand.
- **Defer:** OpenCode (config-merge + cost-event bugs), Cursor (IDE-tied), Crush
  (not an agent CLI), Continue (IDE-first).

---

## 7. Open decisions & uncertainties

**Directional decisions (need the maintainer):**
- **D1 — CLI scope now:** design the abstraction for all; implement+test
  claude+codex now, add **gemini** next as the generalization proof; others
  data-only later. *(recommended)*
- **D2 — no Docker:** keep worktrees + two-layer defense; Docker stays a non-goal.
  *(recommended — confirms the existing invariant; research validates it)*
- **D3 — tilth version under test:** `~/.cargo/bin/tilth` **1.0.0** (matches
  tilth's own benchmark) vs `/opt/homebrew/bin/tilth` 0.9.0 (what copeca
  mistakenly used). *(recommended: 1.0.0, and record it per run)* — **open.**

**Empirical uncertainties to confirm before relying on them:**
- Claude `~/.claude/settings.json` has no `mcpServers` on the bench host.
- Claude `--bare` vs `.mcp.json` (mooted by `--strict-mcp-config`).
- Codex `AGENTS.md` suppression flag (`-c model_instructions_file=/dev/null` is a guess).
- Codex project `.codex/config.toml` under `--ignore-user-config`.
- Gemini project `.gemini/settings.json` + `GEMINI.md` leak from the worktree.
- OpenCode `OPENCODE_CONFIG_CONTENT` merge-vs-replace semantics.

These become preflight assertions (Layer 2) or are closed by clean-worktree scans.

---

## Sources

Claude Code: code.claude.com/docs (cli-reference, headless, mcp, env-vars).
Codex: developers.openai.com/codex (cli/reference, config-reference, mcp,
environment-variables); github.com/openai/codex/issues/15410.
Gemini CLI: geminicli.com/docs + google-gemini.github.io/gemini-cli (headless,
configuration, mcp-server, enterprise, policy-engine).
OpenCode: opencode.ai/docs (cli, config, mcp-servers); github issues #26855,
#17223, #4054.
Prior art: Harness-Bench arXiv 2605.27922; Terminal-Bench arXiv 2601.11868;
epoch.ai/blog/swebench-docker; aider.chat/docs/leaderboards; ai21.com SWE-bench
scaling. Landscape: wal.sh 2026-q2 CLI agents; morphllm leaderboard; Copilot CLI
GA (github.blog 2026-02-25); ampcode.com/manual; Cline/Goose deepwiki.
