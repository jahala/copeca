# tend — field notes from copeca

Feedback from ~8 hours of heavy tend usage — positioning, brainstorming 9 features + 3 personas + 6 opportunities, narrating all 18 polyglots with thumbnails, and writing the garden overview. Not a bug report. Honest impressions from a real user.

---

## What worked well

- **The spine concept is solid.** Personas → opportunities → features with `validates_job` pointers. Once the 3 personas were planted, every downstream write (brainstorm checks, narrate scenarios) had an anchor. The chain held.
- **`tend_update_catalog` deep-merge is correct.** Adding 3 personas + 6 opportunities + 6 journey phases in one call, then later dropping the orphan `trust` phase, worked cleanly. The refusal to drop without `force: true` is the right safety check.
- **Schema validation catches real mistakes.** It rejected `method: "manual"` (should be `user-report`), caught the missing `impact` check on copeca-validate-tasks, and flagged the empty `trust` journey phase. Each rejection was correct and the error message was specific enough to fix.
- **Narrative cross-reference checks (`narrative_cite_stale`).** The validator finding that narrative cites files that don't exist on disk is technically correct for a pre-code project — and it'll be genuinely useful once code exists.
- **The polyglot bash `data` verb is reliable.** Every read for the link audit, the narrative extraction, and the catalog survey worked identically across all 19 polyglots.

## Confusions and rough edges

### Garden `id` is `"garden"` — not obvious
The garden is written via `tend_update_feature({ id: "garden", ... })`, not via `tend_update_catalog`. The catalog write is only for `personas`, `opportunities`, `journey_phases`, and `source_dirs`. The garden's slots, narrative, dek, and thumbnail all go through the feature write path. This boundary is correct once you know it, but nothing in the schema reference or the init scaffolding tells you the garden's special `id`.

**Suggestion:** `tend init` could emit a comment in `overview.html` or a note in the init output: "The garden's id is `garden`. Write its slots and narrative via `tend_update_feature`."

### Link path conventions differ by polyglot level
- Feature → feature: `[text](other-feature.tend.html)` (bare filename, same directory)
- Garden → feature: `[text](features/other-feature.tend.html)` (garden is one level up)
- Garden → doc: `[text](../ideas/some-file.md)` (docs/ is one level up from docs/tend/)

This is logical once you trace the file tree, but I got it wrong on the first garden narrative pass (used bare filenames, which resolved to `docs/tend/` instead of `docs/tend/features/`). The `narrative_cite_stale` check caught code-file cites but not broken tend links.

**Suggestion:** `tend_validate` could add a `narrative_link_stale` check for tend-internal links that don't resolve to an existing polyglot or the correct path convention. Even a one-line warning: "garden narrative links to `copeca-single-run.tend.html` — garden links to features need `features/` prefix."

### The `dek` field is easy to miss
Every polyglot shipped with `dek: 0 chars` — not because I didn't want deks, but because the narrate skill prioritises narrative prose and thumbnails, and the dek lives in a separate mental slot. Nobody reminded me to fill deks until I audited the output myself.

**Suggestion:** `tend_get_gaps` or `tend_validate` could surface `dek_missing` as a low-severity info warning: "Feature `copeca-validate-tasks` has a narrative but no dek — the masthead will render compact." That single prompt would have caught all 19 missing deks.

### `max_workers` in scenario YAML — shouldn't garden track project-level parallelism as a real field?
It's written into the `how` slot text in the scenario-matrix feature narrative. The scenario schema supports it. But for a greenfield project with no actual schema on disk, it lives only in prose. Since every Phase 2+ feature depends on worktrees and concurrency, it's cross-cutting config that probably belongs in the garden's `catalog`.

### Self-referential links feel odd
`[integration-only-mcp](integration-only-mcp.tend.html)` links to itself. It renders fine (same-page anchor), but it reads as a mistake during authoring. I wrote it in the opportunity's "Where the signal came from" section to link back to the opportunity's own landscape survey context.

**Suggestion:** `tend_validate` could flag self-links as a warning: "Polyglot `integration-only-mcp` links to itself. This is technically valid but usually unintentional."

---

## Features I wanted

### Batch narrate dispatch
I needed 18 polyglots narrated with thumbnails. The narrate skill says "dispatch one subagent per polyglot" but provides no orchestration. I split 18 polyglots across 3 manual subagent dispatches. The subagents did the work, but distribution + result collection was all manual.

**Wish:** `tend narrate --batch --all` or an adapter that fans out parallel narrate runs, collects results, and runs the shuffle test once. Or at minimum: document the batch pattern as a recipe rather than leaving it to the user.

### A "what changed" view
After 3 rounds of fixes (voice cleanup, link fixes, narrative trimming), I wanted to see what I'd actually changed. The only option was re-reading every polyglot. A CLI command like `tend diff <id>` — or even just `tend status <id>` showing last-modified timestamps on the narrative/thumbnail/slots — would have saved time.

### A link target validator for tend-internal links
I wrote a bash one-liner to extract and verify every `[text](target.tend.html)` link. That script should be a first-party `tend check-links` or part of `tend_validate`.

---

## Notes about the product itself

- **tend feels like infrastructure, not a product.** This is actually a compliment — it doesn't impose a workflow, it provides primitives (slots, checks, steps, audit, narrative) that compose. But it means the first hour has a learning curve. The CLAUDE.md daily-loop instructions are good; a "build your first feature in 10 minutes" walkthrough would be better.
- **The garden-as-feature pattern is elegant but under-explained.** The garden IS a feature polyglot — it carries slots, a narrative, media, even checks if you wanted them. The catalog is the only special thing. Once you internalize this, the write surface is uniform. But the init output doesn't tell you this, and the schema reference buries it.
- **Journey phases are a strong concept that wants a visual.** Having 5 phases (orient → author → calibrate → verify → compare) with features distributed across them matters for understanding project shape. A one-line CLI output grouping features by phase would be more useful than the current flat list.
- **The thumbnails + shuffle test workflow is thorough but heavy for 18 polyglots.** `preview-thumbnail → Read PNG → iterate → preview-cards → Read composite PNG → shuffle test` is the right process for a handful of features. For 18, the visual verification cost dominates the narrative authoring cost. A batch mode that shows all 18 thumbnails in one composite without requiring per-thumbnail PNG reads would help.

---

## Mistakes I made (that the tool didn't catch)

- **Forgot `features/` prefix in garden links** — wrote `[text](copeca-single-run.tend.html)` instead of `[text](features/copeca-single-run.tend.html)`. The validator caught code-path cites but not tend-internal link paths.
- **Wrote `method: "manual"` instead of `method: "user-report"`** — schema validation caught this correctly. The error message named the allowed values.
- **Left garden title as "Project Garden"** — the init default. Nothing prompted me to rename it. A "garden title is still the default" info warning in `tend_validate` would help.
- **Tried to drop journey phases via catalog update without `force: true`** — the refusal was correct, the error message was clear enough.
- **Assumed `tend_update_catalog` could write the garden's slots** — it can't. The garden's `what/why/impact/fit/where/how` go through `tend_update_feature({ id: "garden" })`. This boundary took two failed calls to learn.

---

## Update: 2026-06-19 — tend-plan session (54 steps across 9 features)

### What went well

- **The test-first format is excellent.** Every step carries a `Test:` block with file path, asserts, boundary, setup, and run command — followed by an `Implement:` block with concrete files and logic. This is genuinely buildable: an agent (or human) can pick up any step in any feature and write the failing test from the prose alone. No ambiguity. The format's constraint that "you do not modify the test file once written" is the right discipline.

- **`traces_to` is the load-bearing bridge.** Every step links to one or more check IDs. The checks carry `validates_job` pointers to persona-jobs. The persona-jobs carry validation clauses. Reading the chain backwards (step → check → persona-job → validation) tells you *why* a step exists and what its test must prove. This traceability is what makes the plan auditable. Without it, steps would be a flat todo list.

- **`tend_update_feature` handled large step arrays cleanly.** Writing 5-9 step objects per feature with full Test:/Implement: blocks in each description — some 500+ chars — worked without schema rejections or truncation. The write surface is solid.

- **The architecture layer split (domain → ports → adapters) mapped cleanly to step ordering.** Validate-tasks builds domain-first (models → schema → loader → CLI). Single-run builds parsers + base classes (domain) before subprocess + repo (adapters). The step DAG in every feature respects the dependency direction from `architecture.md` §2.

- **Context-rich subagent prompts work — when the subagent survives.** The three agents got architecture.md + engineering.md + tilth reference + polyglot data + tend-plan format spec. The one that completed (Phase 1a) produced high-quality, correctly-formatted, architecture-respecting steps. The format was right; the reliability was not.

### What went poorly

- **Two of three tend-plan subagents stalled (600s stream watchdog timeout).** The Phase 1b agent (single-run + mode-mechanism + cost-model + artifact-integrity — 4 features) and the Phase 2-4 agent (scenario-matrix + analysis-reporting + docs-and-init — 3 features) both timed out. No partial output. No error message. No recovery. The Phase 1a agent (validate-tasks + task-corpus — 2 features) completed in ~66s.

  Root cause hypothesis: the Phase 1b agent had the most complex prompt (4 features, the entire tilth reference, architecture + engineering context, and tend-plan format). The Phase 1a agent had 2 features and completed fast. The Phase 2-4 agent had 3 features but also stalled. The 600s watchdog may be too short for subagents that need to read multiple polyglots, cross-reference architecture docs, and author detailed step descriptions with Test:/Implement: blocks.

- **Writing 6 of 9 features inline saved the session but was suboptimal.** I wrote 6 features' worth of steps from my own context (architecture.md, engineering.md, the agent's successful output as a format template, and tilth knowledge). The steps are correct — but they lack the subagent's fresh cross-referencing against the polyglot's checks and persona-jobs. The inline steps trace to check IDs correctly; the subagent would have done a richer job linking `validates_job` clauses into the Test: asserts.

- **No partial output from stalled subagents.** The stall is silent — the agent just stops. A partial output with the steps completed so far (even unstably) would have saved the session: I could have taken the completed features and only written the remainder inline. As it was, the stall meant all 7 features from those two agents had to be written from scratch.

### What I'd change for next time

- **Smaller batch size.** 2 features per agent seems to be the reliable ceiling (Phase 1a: 2 features, 66s, completed). 3-4 features per agent failed. For parallel planning, dispatch one agent per feature, not per batch.

- **A tend-plan batch adapter.** The narrate session also suffered from no orchestration. A `tend plan --batch --features "id1,id2,…"` that dispatches one subagent per feature, collects results, and writes them via MCP would turn "maybe this works" into "this always works."

- **Timeout handling with partial salvage.** If `tend_get_context` could be called after a stall to see what changed, I could assess partial progress. Or a subagent that catches the timeout and dumps its in-progress JSON before exiting.

- **An example step in the SKILL.md or references/.** The tend-plan SKILL.md is precise but the step format is described in the schema reference, not in the plan SKILL. A single worked example — one complete step with Test:/Implement: blocks for a hypothetical check — would have saved the subagents from having to synthesize the format from the schema. I provided the format explicitly in the prompt; if the SKILL had it, the prompt could have been shorter and the subagents faster.

### What was genuinely impressive

The plan is 54 steps across 9 features, all test-first, all tracing to checks. Every step is written against the architecture (`domain first, ports second, adapters third`), the engineering handbook (`Pytest, pristine output, mock only at external boundaries`), and the tilth reference (`ADAPT ~75% from analyze.py`, `COPY from parse.py`). The subagent failure was a reliability problem, not a design problem — the format, the write surface, and the traceability chain all held.
