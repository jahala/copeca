# Tilth → copeca Migration Delta

**Generated:** 2026-06-21  
**Source corpora:**
- copeca tasks: `src/copeca/data/tasks/` (16 tasks)
- tilth tasks: `/tmp/tilth-eval/benchmark/tasks/` (45 tasks across 20 files)
- tilth config: `/tmp/tilth-eval/benchmark/config.py`

---

## Summary

**Total tilth tasks: 45**

| Metric | Count |
|--------|-------|
| NEW (migrate as-is) | 38 |
| DUPLICATE (copeca already covers) | 4 |
| REFRAME (grok_ tasks: strip tool-priming, rename) | 3 |
| locate | 11 |
| trace | 17 |
| fix | 13 |
| debug | 4 |
| mechanism = none (ready now) | 36 |
| mechanism = committed-history (SD-P) | 4 |
| mechanism = synthetic-repo (SD-Q) | 5 |

---

## Full Task Table

Commit SHAs: ripgrep `0a88cccd`, gin `d7776de7`, express `1140301f`, fastapi `6fa573ce`, synthetic = n/a.

| tilth name | verdict | category | repo | mechanism | commit | proposed copeca name |
|---|---|---|---|---|---|---|
| find_definition | NEW | locate | synthetic | synthetic-repo (SD-Q) | n/a | find_definition |
| read_large_file | NEW | locate | synthetic | synthetic-repo (SD-Q) | n/a | read_large_file |
| edit_task | NEW | fix | synthetic | synthetic-repo (SD-Q) | n/a | edit_task |
| codebase_navigation | NEW | trace | synthetic | synthetic-repo (SD-Q) | n/a | codebase_navigation |
| markdown_section | NEW | locate | synthetic | synthetic-repo (SD-Q) | n/a | markdown_section |
| rg_trait_implementors | DUPLICATE | trace | ripgrep | — | — | — |
| rg_flag_definition | NEW | locate | ripgrep | none | 0a88cccd | rg_flag_definition |
| rg_search_dispatch | DUPLICATE | trace | ripgrep | — | — | — |
| rg_walker_parallel | NEW | trace | ripgrep | none | 0a88cccd | rg_walker_parallel |
| rg_lineiter_definition | NEW | locate | ripgrep | none | 0a88cccd | rg_lineiter_definition |
| rg_lineiter_usage | NEW | trace | ripgrep | none | 0a88cccd | rg_lineiter_usage |
| rg_edit_line_count | NEW | fix | ripgrep | none | 0a88cccd | rg_edit_line_count |
| rg_edit_line_locate | NEW | fix | ripgrep | none | 0a88cccd | rg_edit_line_locate |
| rg_edit_preceding | NEW | fix | ripgrep | none | 0a88cccd | rg_edit_preceding |
| fastapi_dependency_resolution | NEW | trace | fastapi | none | 6fa573ce | fastapi_dependency_resolution |
| fastapi_request_validation | NEW | trace | fastapi | none | 6fa573ce | fastapi_request_validation |
| fastapi_depends_internals | NEW | locate | fastapi | none | 6fa573ce | fastapi_depends_internals |
| fastapi_depends_function | NEW | locate | fastapi | none | 6fa573ce | fastapi_depends_function |
| fastapi_depends_processing | NEW | trace | fastapi | none | 6fa573ce | fastapi_depends_processing |
| fastapi_edit_dep_cache | NEW | fix | fastapi | none | 6fa573ce | fastapi_edit_dep_cache |
| fastapi_edit_response_filter | NEW | fix | fastapi | none | 6fa573ce | fastapi_edit_response_filter |
| fastapi_edit_scope_cache | NEW | fix | fastapi | none | 6fa573ce | fastapi_edit_scope_cache |
| gin_radix_tree | NEW | locate | gin | none | d7776de7 | gin_radix_tree |
| gin_client_ip | NEW | locate | gin | none | d7776de7 | gin_client_ip |
| gin_middleware_chain | DUPLICATE | trace | gin | — | — | — |
| gin_context_next | DUPLICATE | locate | gin | — | — | — |
| gin_servehttp_flow | NEW | trace | gin | none | d7776de7 | gin_servehttp_flow |
| gin_edit_middleware_skip | NEW | fix | gin | none | d7776de7 | gin_edit_middleware_skip |
| gin_edit_abort_check | NEW | fix | gin | none | d7776de7 | gin_edit_abort_check |
| gin_edit_context_reset | NEW | fix | gin | none | d7776de7 | gin_edit_context_reset |
| express_json_send | NEW | trace | express | none | 1140301f | express_json_send |
| express_render_chain | NEW | trace | express | none | 1140301f | express_render_chain |
| express_app_init | NEW | trace | express | none | 1140301f | express_app_init |
| express_res_send | NEW | locate | express | none | 1140301f | express_res_send |
| express_app_render | NEW | trace | express | none | 1140301f | express_app_render |
| express_edit_json_type | NEW | fix | express | none | 1140301f | express_edit_json_type |
| express_edit_cookie_prefix | NEW | fix | express | none | 1140301f | express_edit_cookie_prefix |
| express_edit_send_type | NEW | fix | express | none | 1140301f | express_edit_send_type |
| express_diff_multi_mutation | NEW | debug | express | committed-history (SD-P) | 1140301f | express_diff_multi_mutation |
| fastapi_diff_which_commit | NEW | debug | fastapi | committed-history (SD-P) | 6fa573ce | fastapi_diff_which_commit |
| rg_diff_misdirected_error | NEW | debug | ripgrep | committed-history (SD-P) | 0a88cccd | rg_diff_misdirected_error |
| gin_diff_comprehension | NEW | debug | gin | committed-history (SD-P) | d7776de7 | gin_diff_comprehension |
| grok_gin_new | REFRAME | trace | gin | none | d7776de7 | gin_new_constructor |
| grok_depends | REFRAME | trace | fastapi | none | 6fa573ce | fastapi_depends_callers |
| grok_context_next | REFRAME | trace | gin | none | d7776de7 | gin_context_next_peers |

---

## Duplicates

Each entry: tilth task name — copeca task it overlaps — reasoning.

**rg_trait_implementors** → copeca `rg_trait_implementors` (`ripgrep/trait_implementors.yaml`)  
Identical task name, identical subject: find the Matcher trait definition in the matcher crate, list required methods, enumerate all implementing types with crate locations. The tilth version adds "like `find_at`" as an example but is otherwise the same question against the same pinned repo. Also substantially overlaps copeca `t001_find_matcher_trait` (same Matcher trait + all implementors), but the name match with `rg_trait_implementors` makes that the primary duplicate.

**rg_search_dispatch** → copeca `t005_ripgrep_search_flow`  
Both tasks ask the agent to trace how ripgrep dispatches search execution. Tilth's version focuses on the Searcher → ReadByLine/MultiLine split and generic type parameter flow (ground truth: `ReadByLine`, `MultiLine`, `Sink`, `glue.rs`). Copeca's version starts from `main()` and traces through Worker coordination to first match (ground truth: `search`, `Worker`, `grep`, `matcher`, `printer`). The two questions overlap at the Searcher level and a correct answer to either requires understanding the same dispatch mechanism; a merged task would cover both entry points.

**gin_middleware_chain** → copeca `t003_gin_middleware`  
Both trace the full gin middleware chain. Tilth's version starts from `Engine.ServeHTTP`, pools a Context, finds route handlers, and advances through HandlersChain via `Context.Next()` (ground truth: `ServeHTTP`, `HandlersChain`, `Next`, `pool`, `index`). Copeca's version traces `c.Next()` execution, handler storage, invocation order, and `Abort()` short-circuit (ground truth: `Next`, `handlers`, `HandlersChain`, `index`, `Abort`). The symbol sets are nearly identical; the tilth version adds `ServeHTTP`/`pool` as entry-point framing but the core question is the same.

**gin_context_next** → copeca `t003_gin_middleware`  
This tilth task asks only for the `Context.Next()` implementation ("Show its complete implementation"). Copeca's `t003_gin_middleware` is a strict superset: it requires Next, HandlersChain, Abort, and the storage model. The narrower question is fully answered as part of answering the copeca task.

---

## Ready Now vs Blocked

### Ready now — mechanism = none (36 tasks)

These tasks exercise real-repo comprehension or single-mutation edit repair against the pinned commit. No infrastructure beyond CV-1 / CV-2 task conversion is required.

**ripgrep (7):** rg_flag_definition, rg_walker_parallel, rg_lineiter_definition, rg_lineiter_usage, rg_edit_line_count, rg_edit_line_locate, rg_edit_preceding

**fastapi (8):** fastapi_dependency_resolution, fastapi_request_validation, fastapi_depends_internals, fastapi_depends_function, fastapi_depends_processing, fastapi_edit_dep_cache, fastapi_edit_response_filter, fastapi_edit_scope_cache

**gin (6, including 1 REFRAME):** gin_radix_tree, gin_client_ip, gin_servehttp_flow, gin_edit_middleware_skip, gin_edit_abort_check, gin_edit_context_reset, gin_new_constructor (REFRAME of grok_gin_new), gin_context_next_peers (REFRAME of grok_context_next)

Wait — REFRAME tasks are also mechanism = none. Corrected gin count: 8 (6 NEW + 2 REFRAME).

**gin (8):** gin_radix_tree, gin_client_ip, gin_servehttp_flow, gin_edit_middleware_skip, gin_edit_abort_check, gin_edit_context_reset, gin_new_constructor (REFRAME), gin_context_next_peers (REFRAME)

**express (8):** express_json_send, express_render_chain, express_app_init, express_res_send, express_app_render, express_edit_json_type, express_edit_cookie_prefix, express_edit_send_type

**fastapi REFRAME (1):** fastapi_depends_callers (REFRAME of grok_depends)

Total ready now: 7 + 8 + 8 + 8 + 1 = 32 NEW/REFRAME tasks (the 4 DUPLICATEs above also have mechanism = none but are not migrated).

Actual count: 36 mechanism=none rows in the table (including the 4 DUPLICATEs which are not migrated).  
**Actionable ready-now migrations: 32** (36 minus 4 DUPLICATEs).

### Blocked on SD-P — committed-history (4 tasks)

These tasks require the benchmark runner to commit the mutation into git history before launching the agent, so the agent can use `git log` / `git diff` to discover the regression. This requires the SD-P (committed-diff) harness extension.

| task | repo | what blocks it |
|------|------|----------------|
| express_diff_multi_mutation | express | 3-mutation commit; agent must distinguish bugs from refactoring via git diff |
| fastapi_diff_which_commit | fastapi | 3-commit sequence; agent must navigate git history to pinpoint the bug commit |
| rg_diff_misdirected_error | ripgrep | single mutation committed; test error points at wrong file, agent needs diff to find source |
| gin_diff_comprehension | gin | pure diff comprehension of committed header-order change; no code fix needed |

### Blocked on SD-Q — synthetic-repo (5 tasks)

These tasks run against the generated synthetic fixture repo (`benchmark/fixtures/repo`), not any real OSS codebase. They require the SD-Q synthetic-repo setup to be instantiated before conversion.

| task | what it tests |
|------|---------------|
| find_definition | locate `validate_jwt_token` in `tokens.py` |
| read_large_file | find rate-limiting logic in `src/api/routes.py` |
| edit_task | change return type of `get_pool` in `src/database/connection.py` |
| codebase_navigation | list files handling database operations |
| markdown_section | read Deployment section from README.md |

---

## Intra-tilth Redundancy Note (non-blocking)

Three tilth task pairs cover the same FastAPI symbol at overlapping granularities. These are all NEW relative to copeca (copeca has no Depends tasks), but CV-1 conversion should pick one canonical form per concept rather than importing all three:

- `fastapi_depends_function` (single-function locate: signature + docstring) is a strict subset of `fastapi_depends_internals` (same plus: what it returns, where the impl lives) which is itself a subset of `fastapi_depends_processing` (same plus: how solve_dependencies resolves the tree at request time). Recommended: import `fastapi_depends_processing` as the single canonical Depends trace task; drop `fastapi_depends_function` and `fastapi_depends_internals`.

- Similarly, `grok_depends` (REFRAME → `fastapi_depends_callers`) overlaps `fastapi_depends_processing` on the Depends symbol but adds the caller-enumeration angle that `fastapi_depends_processing` does not explicitly require. Keep as a separate task post-reframe since the ground-truth strings differ.
