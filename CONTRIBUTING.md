# Contributing to Nacho

Thank you for considering a contribution. This document describes how the
project is developed, tested, and released, so your pull request lands
smoothly.

## Code of conduct

Be respectful and constructive. Assume good intent, consider differing
viewpoints, and keep discussions focused on what is best for the project.

## Branch model

```
feature branch -> dev -> staging -> main
```

- `dev` — active development. All features and fixes are integrated here first.
- `staging` — pre-production. Changes are promoted here for integration testing.
- `main` — production. Merging here triggers an automated release.

Create feature branches from `dev`, using descriptive names:

- `feature/<short-description>` for new features
- `fix/<issue-description>` for bug fixes
- `docs/<update-description>` for documentation
- `refactor/<component>` for restructuring

Keep each branch focused on a single change.

## Development setup

1. Fork the repository and clone your fork:

   ```bash
   git clone https://github.com/<your-username>/nacho.git
   cd nacho
   git remote add upstream https://github.com/Nya-Foundation/nacho.git
   ```

2. Install with [uv](https://docs.astral.sh/uv/):

   ```bash
   uv sync --all-extras
   ```

   This creates a virtual environment with every extra and all development
   tools. Run project commands through it: `uv run pytest`,
   `uv run nacho --help`.

   If you prefer pip:

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e .[dev]
   ```

## Code style

Formatting is enforced by Black and isort (Black-compatible profile). Format
before pushing:

```bash
uv run isort --profile black .
uv run black .
```

CI checks formatting on every pull request. Beyond formatting, match the
style of the surrounding code: small focused functions, explicit error
handling, and comments only where the code cannot speak for itself.

## Testing

Tests live under `tests/`, grouped by scope: `unit/`, `smoke/`,
`integration/`, `e2e/`, and `docker/`. Each test is automatically tagged with
a pytest marker matching its folder, so there is no per-file marker
boilerplate.

The default run executes the fast suites only; the heavier suites are opt-in:

```bash
uv run pytest                                   # unit + smoke; run on every change
uv run pytest -m "integration or e2e" --no-cov  # spawns real server processes
uv run pytest -m docker --no-cov                # builds and exercises the Docker image
uv run pytest -m "" --no-cov                    # everything
```

The default run enforces a 95% coverage gate. Pass `--no-cov` when running an
opt-in suite on its own — a single marker selection does not exercise enough
of the codebase to clear the threshold.

Ship new code with tests in the folder matching its scope. Bug fixes should
include a test that fails without the fix. Prefer event- or condition-based
waits over fixed sleeps in anything asynchronous.

## Pull requests

1. Branch from `dev` and make your change.
2. Add or update tests, and run the fast suites locally.
3. Open a pull request against `dev` with a description of what changed and
   why.
4. Make sure CI passes, and address review feedback.

Every pull request needs at least one maintainer approval before merging.

## Commit messages

Releases are automated with semantic-release, so commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Effect |
|---|---|
| `feat:` | minor version bump |
| `fix:` | patch version bump |
| `docs:`, `refactor:`, `test:`, `chore:` | no version bump |

Note breaking changes with a `BREAKING CHANGE:` footer, which triggers a
major version bump.

## Release process

Merges to `main` run the release pipeline automatically:

1. The full test suite runs (unit, smoke, integration, and e2e), and the
   release is blocked if anything fails.
2. semantic-release calculates the next version from commit messages.
3. A GitHub release is created with a generated changelog.
4. The package is published to PyPI.
5. Multi-architecture Docker images are built, scanned, and pushed to Docker
   Hub and GHCR.

Versioning follows [Semantic Versioning](https://semver.org/).

## Reporting bugs and requesting features

Use the [GitHub issue tracker](https://github.com/Nya-Foundation/nacho/issues).

For bugs, include: a clear title, steps to reproduce, expected and actual
behavior, environment details (OS, Python version, install extras), and logs
where applicable.

For feature requests, include: the problem you are trying to solve, the
solution you would like, and any alternatives you have considered.
