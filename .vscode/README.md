# `.vscode/` — workspace config

These files are committed so every contributor opens the project the same way.
They are the editor-facing half of the dev environment; the authoritative
setup guide is [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md).

| File | What it does |
| ---- | ------------ |
| `settings.json` | Points Pylance/pytest at `.venv`, makes **Ruff** the formatter (format + organize-imports on save), enables pytest discovery, and auto-activates the venv in new terminals. |
| `extensions.json` | Recommends the handful of extensions this project uses, and marks conflicting ones (black, isort, flake8, pylint) as unwanted. |
| `launch.json` | Debug configs: current file, current test file, `-k` pattern, and the MCP server. |
| `tasks.json` | Wraps the `Makefile` targets so the palette runs the same commands as the terminal. |

## First-time setup

If you see a wall of "unresolved import" problems, the venv interpreter
isn't selected yet:

1. Run `./scripts/setup.sh` (or the **Setup: create venv + install** task).
2. Reload the window (`Ctrl/Cmd+Shift+P → Developer: Reload Window`).
3. Confirm the interpreter reads `.venv/bin/python` (status bar, bottom right).

When prompted, install the recommended extensions — Ruff and Pylance do the
heavy lifting.

## Why Ruff-only?

Linting **and** formatting come from a single tool configured in
`pyproject.toml` (`[tool.ruff]`). That's the single source of truth: the
extension, the `Makefile`, and the pre-commit hook all read the same rules,
so the editor never disagrees with CI.
