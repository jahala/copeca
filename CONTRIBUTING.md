# Contributing

Thanks for your interest. copeca is small and intentionally so — clean, focused changes are easiest to land.

## Workflow

1. Fork, branch, change.
2. Run the gates locally:
   ```bash
   ruff format --check .
   ruff check .
   pytest
   ```
3. Open a PR. Describe what changed and how to test it.

CI runs the same three commands on every push.

## What helps

- **Small PRs.** Easier to review, easier to merge.
- **Conventional commits.** `fix: ...`, `feat: ...`, `refactor: ...`, `docs: ...`. The log is the changelog.
- **A test.** Bug fixes need a regression test. Features need at least one.
- **Surgical edits.** Don't rewrite surrounding code unrelated to the change.

## Code style

See [CLAUDE.md](./CLAUDE.md) for the project layout and conventions. Match the style of the file you're editing.

## Contributing a task

The benchmark corpus grows through PRs. Here is the full flow:

1. **Fork and branch** off `master`.
2. **Author a task YAML** following [docs/task-authoring.md](docs/task-authoring.md).
   Use `copeca new-task <path>` to scaffold a commented skeleton.
3. **Add the repo** to `repos.yaml` if it is not already there (pinned commit, permissive license).
4. **Run the gates locally** until both are green:
   ```bash
   copeca validate src/copeca/data/tasks/<repo>/
   copeca check-task src/copeca/data/tasks/<repo>/my_task.yaml   # edit tasks only
   ```
5. **Open a PR** with a clear description of what the task tests and why it discriminates.

### Acceptance criteria

A task PR is accepted when all of the following hold:

- **(a) Valid** — `copeca validate` passes (schema, provenance, tool-agnosticism).
- **(b) Discriminating** — neither trivial (all agents pass) nor impossible (none pass).
  Aim for a baseline pass-rate of roughly 40–70% so a tool can move the needle.
  Explain your estimate in the PR description.
- **(c) Real repo at a pinned commit** — the target `repo` is in `repos.yaml`
  at a full 40-character SHA that is publicly accessible.
- **(d) Tool-agnostic phrasing** — the prompt names the information required,
  not the retrieval method (no tool names, no "search for", no single-shot-aggregator cues).
- **(e) Correct category + `control` flag** — `category` matches what the task
  actually tests (locate / trace / fix / debug); set `control: true` if the task
  is a non-regression / answer-in-context task (once that field is active).
- **(f) Approved-license provenance** — `source` cites an Apache-2.0, MIT, or
  CC-BY origin; no NC/ND; no benchmark on the contamination blocklist.

## Bigger changes

For anything that adds a new task type, changes the benchmark schema, or restructures a module: open an issue first so we can agree on the shape before you spend time on the implementation.

## License

By contributing, you agree your work is licensed under the project's [MIT License](./LICENSE).
