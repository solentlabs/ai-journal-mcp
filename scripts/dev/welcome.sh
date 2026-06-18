#!/usr/bin/env bash
# Printed on VS Code folder-open (see .vscode/tasks.json "Welcome", runOn:
# folderOpen) so a first-time contributor gets an unmissable starting point —
# even if they never open a terminal. Picks the message by venv state and
# reuses the same text the terminal greeting shows.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"

if [ -x "$ROOT/.venv/bin/python" ]; then
    cat "$DIR/next_steps.txt"
else
    cat "$DIR/welcome_message.txt"
fi
