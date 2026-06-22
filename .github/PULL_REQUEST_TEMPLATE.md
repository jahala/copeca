## Summary

<!-- One paragraph. What changed, why. -->

## Test plan

<!-- How to verify this works. CI checks format + lint + tests on every push. -->

- [ ] `ruff format --check .`
- [ ] `ruff check .`
- [ ] `pytest`

## If this PR adds a task

<!-- Remove this section if the PR does not add task YAML files. -->

- [ ] `copeca validate <tasks-dir>` passes (schema, provenance, tool-agnosticism)
- [ ] `copeca check-task <task.yaml>` passes (edit tasks only — test fails on mutated code, passes on clean)
- [ ] `source` field cites an Apache-2.0, MIT, or CC-BY origin; not on the contamination blocklist
- [ ] Prompt is tool-agnostic: names the information required, not the retrieval method
- [ ] `category` is set correctly (`locate` / `trace` / `fix` / `debug`); `control: true` added if applicable
- [ ] Target repo is in `repos.yaml` at a full 40-character pinned commit that is publicly accessible
