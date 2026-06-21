# Security Policy

## Reporting a vulnerability

Please **don't** open a public issue. Use GitHub's private advisory flow:

→ <https://github.com/jahala/copeca/security/advisories/new>

We'll acknowledge within 72 hours and coordinate disclosure with you.

## Supported versions

Only the latest minor release receives security updates. Older versions don't.

## Security testing

copeca runs:

- **Unit and integration tests** on every push (`pytest`).
- **Lint and format checks** on every push (`ruff check` / `ruff format --check`).
- **Dependency Review** on PRs that touch `pyproject.toml` — gated on `moderate` severity (public repo only).
- **OpenSSF Scorecard** weekly, results uploaded to the Code scanning view.
- **Dependabot** weekly version updates for `pip` and `github-actions`.

## Reporting non-security bugs

Open a regular issue: <https://github.com/jahala/copeca/issues/new/choose>.
