# `scripts/`

Developer tooling. The authoritative setup guide is
[`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md); this file is just an index.

| Script | Purpose |
| ------ | ------- |
| `setup.sh` | One-command environment setup: finds Python 3.11+, creates `.venv`, installs `ai-journal[dev,server]` editable, installs the pre-commit hook. Idempotent. |
| `verify-setup.sh` | Read-only health check. Reports what's missing (venv, imports, tools, hook) and the exact command to fix each. Run it when the editor shows unexpected import errors. |
| `dev/activate_venv.sh` | VS Code terminal init hook — activates `.venv` on terminal open (or nudges you to run setup). Wired in `.vscode/settings.json`. |
| `dev/welcome.sh` | Printed by the folder-open "Welcome" task (`.vscode/tasks.json`); shows next-steps or a setup nudge based on venv state. |
| `dev/next_steps.txt`, `dev/welcome_message.txt` | Messages shown by the terminal hook and `welcome.sh`. |
| `assign_themes.py` | One-off maintenance helper for back-filling entry themes. |

Day-to-day you'll go through the `Makefile` rather than calling these
directly: `make setup`, `make verify`, `make check`, `make test`.
