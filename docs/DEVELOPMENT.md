# Development

How to set up, run, and check the ai-journal codebase. This is the
authoritative dev-environment doc; `CLAUDE.md` and `README.md` point here
rather than restating it. For what the code *does*, see `ARCHITECTURE.md` and
`SPECIFICATION.md`.

## Prerequisites

- **Python 3.11+** — required (the config loader uses the stdlib `tomllib`,
  added in 3.11). `setup.sh` checks this and refuses older interpreters.
- **make** and **bash** — used by the task runner and setup scripts.
- **Node.js 18+** — *only* for documentation linting (cspell + markdownlint,
  pinned in `package.json`). The Python tooling works without it; `make
  lint-docs` and the docs portion of `make check` need it. `setup.sh` installs
  the linters when Node is present and warns when it isn't.
- **VS Code** (recommended) with the extensions in `.vscode/extensions.json`.
  WSL2 and macOS are first-class; everything runs the same.

## Quickstart

```bash
git clone <repo> && cd ai-journal
./scripts/setup.sh        # creates .venv, installs the package + dev tools
```

`setup.sh` is idempotent — safe to re-run any time. It:

1. Finds a Python 3.11+ interpreter.
2. Creates `.venv/`.
3. Installs the package editable with dev + server extras: `pip install -e ".[dev,server]"`.
4. Installs the Node doc linters (cspell + markdownlint) if Node is present.
5. Installs the git hooks (pre-commit + pre-push).

Then in VS Code, reload the window so Pylance picks up `.venv/bin/python`.

## Daily workflow

Everything goes through the `Makefile` so the editor, the terminal, and CI run
the *identical* commands. `make` (or `make help`) lists them:

| Command | What it does |
| ------- | ------------ |
| `make setup` | Create `.venv` and install (idempotent). |
| `make verify` | Read-only health check of the environment. |
| `make test` | Full test suite with coverage. |
| `make test-quick` | Tests without coverage (fast inner loop). |
| `make lint` / `make lint-fix` | Ruff lint (and auto-fix). |
| `make format` / `make format-check` | Ruff format (and check-only). |
| `make type-check` | mypy. |
| `make lint-docs` | cspell + markdownlint (validates/installs the Node tools). |
| `make check` | **The gate**: lint + format-check + type-check + docs lint + tests. What CI runs. |
| `make clean` | Remove caches and the disposable index/coverage artifacts. |
| `make reindex` | Rebuild the local search index from configured journals. |
| `make install-hooks` | Install the git hooks (pre-commit + pre-push). |

The same targets are available in VS Code via *Tasks: Run Task*
(`make check` is the default build task, `make test` the default test task).

## Tooling philosophy

**One tool per job, configured once.** All tool config lives in
`pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`,
`[tool.coverage]`) — a single source of truth that the VS Code extensions, the
`Makefile`, and the pre-commit hook all read. There is no `setup.cfg`,
`.flake8`, `mypy.ini`, or competing config to drift out of sync.

- **Ruff** is the *only* linter and formatter (it replaces black, isort, and
  flake8). Import sorting is Ruff rule `I`. Line length is **120**, matching
  the sibling Cable Modem Monitor repo to keep house style consistent.
- **mypy** is the type-check authority; Pylance type-checking is left off in
  the editor so the two don't double-report (`pyproject.toml` `[tool.mypy]`).
- **pytest** with coverage.

### Test data: fixtures over inline

Test inputs are fixture-based, not pasted into the test body. The taxonomy
mirrors the sibling Cable Modem Monitor repo:

| Kind of test | How data is supplied |
| ------------ | -------------------- |
| **Formats / parsing** | A real sample file under `tests/fixtures/` + a sibling expectation, discovered by `glob()` and run via `parametrize` (one named case per file). See `tests/fixtures/parser/`. |
| **Pure logic** | Table-driven: `@pytest.mark.parametrize` over inline `(input, expected)` rows. |
| **Filesystem behavior** | The `make_journal` factory fixture in `tests/conftest.py`, not ad-hoc `mkdir`/`write_text` repeated per test. |

Adding a new parser format is a two-file drop — `case.md` +
`case.expected.json` — with no test-code change (`tests/fixtures/parser/README.md`
documents the expectation schema). This is what the `CLAUDE.md` rule
"parser changes require a fixture reproducing the real-world format" means in
practice. The fixtures dir is excluded from cspell and markdownlint because the
samples are deliberately messy real-world input, not curated prose.

### Formatting note

Ruff format was adopted on a clean (uncommitted) tree, so there is no churn
against history. With format-on-save enabled in VS Code, files stay formatted
as you work; `make check` enforces it. If you prefer to format manually, turn
off `editor.formatOnSave` in your user settings and run `make format`.

## Git hooks

Optional, installed by `setup.sh` or `make install-hooks` (both stages at
once). The hooks are **check-only** — they never rewrite your files. They block
work that would fail CI and tell you what to fix; staging stays in your hands
(the repo convention is: tools present diffs, you stage and commit).

| Stage | Runs | Why here |
| ----- | ---- | -------- |
| **pre-commit** | `ruff check`, `ruff format --check`, `mypy`, docs lint | Fast — keeps every commit clean without slowing you down. |
| **pre-push** | the full `pytest` suite | Slower, so it gates the push rather than every commit — a broken suite can't reach `main`. |

Fix what they flag with `make lint-fix && make format` (code) or by correcting
the reported file (docs/types).

## Continuous integration

`.github/workflows/ci.yml` runs **`make check`** — the exact same gate — on
every push to `main` and every pull request, across Python 3.11/3.12/3.13 (with
Node for the doc linters). Because CI calls the same `make` target you run
locally, there is no "passes here, fails in CI" divergence: green locally means
green in CI.

## Troubleshooting

**"Lots of problems" / unresolved imports in VS Code** — Pylance hasn't
selected the venv interpreter. Run `./scripts/setup.sh`, then reload the
window. Confirm the status bar shows `.venv/bin/python`.

**A tool is "not found" or behaves oddly** — run the diagnostic:

```bash
make verify          # or: ./scripts/verify-setup.sh
```

It checks the venv, Python version, imports, dev tools, the Node doc linters,
and the hooks, and prints the exact fix for anything missing. It changes
nothing.

**`make lint-docs` / `make check` fails with "Node.js + npm are required"** —
the doc linters are Node tools. Install Node 18+ and re-run; `make lint-docs`
installs the pinned linters on first run.

**Start over** — `rm -rf .venv node_modules && ./scripts/setup.sh`.

## Repo guardrails (don't get surprised)

These are enforced conventions, detailed in `CLAUDE.md`:

- Markdown is the source of truth; the SQLite index and `.coverage` are
  disposable and gitignored — never commit them.
- Generated views (`JOURNAL.md`, `themes/*.md`) are never hand-edited.
- Intake/migration paths never delete data — originals move to `attic/`.
- `mode = "indexed"` journals are read-only.
- Don't run `migrate --apply` against live journals without an explicit
  request and a fresh backup.
