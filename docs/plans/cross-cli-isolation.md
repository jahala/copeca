# Cross-CLI Isolation — Epic Plan

**Goal:** make every copeca run a *verifiable clean room* across Claude Code,
Codex, and Gemini CLI — zero host-config footprint, exactly the declared
tools/MCP, and a post-hoc proof the baseline was clean. Closes the full-haiku
contamination (baseline silently used the host `tilth` MCP) and the wrong-version
trap (tested homebrew 0.9.0, not the cargo 1.0.0 under test).

**Design:** `docs/architecture.md` §13 (the contract + two locks + per-CLI
descriptor + version provenance). **Research:**
`docs/research/cross-cli-isolation/findings.md`.

Every task below: **follow `docs/architecture.md` and `docs/engineering.md`** —
failing test first, smallest reasonable change, S.U.P.E.R. boundaries (I/O at the
edge), one execution path (no `if docker:`).

---

## Decisions (settled with maintainer, 2026-06-22)

- **D1 — CLIs:** Claude + Codex + Gemini now; Cline/Goose/Copilot/Amp/aider are
  data-only descriptors later; OpenCode deferred.
- **D2 — No Docker:** bring-your-own-home + the trace gate solve it more lightly;
  Docker stays a documented non-goal (it would replace subprocess, never branch).
- **D3 — tilth 1.0.0** (cargo, pinned by absolute path); record the resolved
  version per run; warn when multiple installed versions are found.

**Operator-safety constraint (non-negotiable):** copeca must NOT read, write, or
mutate any host CLI config. copeca runs repeatedly on shared developer machines.
The private-home model (architecture.md §13.2) is how — and it is **verified
empirically per CLI** (ISO-9), not assumed.

---

## Phases (→ tasks)

Foundation (must land first):
- **ISO-1 — Isolation descriptor model.** Add an `IsolationSpec` sub-model to
  `RunnerConfig` (config_home_env, strict_mcp_flags, disable_ambient_env,
  disable_session_flags, disable_telemetry_env, ambient_files,
  requires_api_key_env, version_cmd) + JSON schema + validation.
- **ISO-2 — Bring-your-own-home provisioning (Lock 1 core).** Every arm
  (baseline included) gets a fresh ephemeral `HOME` + the CLI's config-home env
  var pointed into the per-run dir; baseline stops returning an empty
  `ArmHarness()`. Preflight asserts the provider API-key env is present.

Per-CLI application (after foundation; ISO-3/4/5 parallel):
- **ISO-3 — Claude isolation.** `claude.yaml` isolation block: `--strict-mcp-config`
  (always), `--no-session-persistence`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`,
  telemetry-off, tool allowlist. Command-builder applies the descriptor.
- **ISO-4 — Codex isolation.** `codex.yaml`: `CODEX_HOME` via BYO-home,
  `--ignore-user-config`, `--ephemeral` (already), `OPENAI_API_KEY` requirement.
  Absorbs **#43 SD-L2** (codex `-c mcp_servers` tool arm).
- **ISO-5 — Gemini runner + parser + isolation.** New `gemini.yaml`
  (`-p --output-format json --yolo`, `GEMINI_CLI_HOME`,
  `--allowed-mcp-server-names`, `GEMINI_CLI_TRUST_WORKSPACE=true`, settings.json
  MCP injection for the tool arm) + a `gemini_json` parser (tokens from
  `stats.models.*`; no USD → `cost_source="modeled"`) + pricing.

Cross-cutting safety (Lock 2):
- **ISO-6 — Pre-run workdir ambient scan (Lock 2a).** Refuse
  (`CONTAMINATED_WORKDIR`) when the worktree holds ambient instruction files
  copeca can't disable for that CLI.
- **ISO-7 — Post-hoc symmetric trace gate (Lock 2b).** Baseline `tool_calls ∩
  tool-under-test == ∅` else `CONTAMINATED_TRACE` (excluded from delta); tool arm
  `tool_adopted ≥ 1`. Builds on SD-I / NR-FIX-2. Absorbs the baseline-clean half
  of **#58 PROXY-1**.

Provenance:
- **ISO-8 — Version provenance + multi-version preflight (D3).** Record resolved
  tool version + path per record; preflight warns on multiple installed versions;
  point `tilth.yaml` at `~/.cargo/bin/tilth` (1.0.0) absolute.

Verification:
- **ISO-9 — Per-CLI empirical isolation proof.** The capstone failing-test:
  stand up a fake host config carrying an MCP server, run a baseline for each of
  claude/codex/gemini, assert zero use of that server. Closes the findings.md §7
  empirical uncertainties.
- **ISO-CHECK — Audit + re-run.** Re-audit touched tend features
  (copeca-mode-mechanism, copeca-single-run) with real evidence; re-run
  full-haiku clean on tilth 1.0.0; confirm the delta is now meaningful.

---

## Supersedes / absorbs

- **#58 PROXY-1** (baseline-clean guard) → ISO-2/3/7.
- **#43 SD-L2** (codex MCP arm) → ISO-4.

## Empirical items to close (findings.md §7)

claude `~/.claude/settings.json` mcpServers · codex `AGENTS.md` suppression +
project `.codex/config.toml` · gemini project `.gemini/settings.json` + `GEMINI.md`
leak. Each becomes a workdir-scan rule (ISO-6) or an ISO-9 assertion.
