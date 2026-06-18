#!/usr/bin/env bash
# VS Code terminal init hook (see .vscode/settings.json terminal profile).
# Sources the user's normal bashrc, then activates .venv if present —
# otherwise prints a short "run setup" nudge. Never fails the shell.

# Keep the user's interactive shell behaving normally.
[ -f "$HOME/.bashrc" ] && source "$HOME/.bashrc"

_AJ_DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_AJ_ROOT="$(cd "$_AJ_DEV_DIR/../.." && pwd)"

if [ -f "$_AJ_ROOT/.venv/bin/activate" ]; then
    source "$_AJ_ROOT/.venv/bin/activate"
    [ -f "$_AJ_DEV_DIR/next_steps.txt" ] && cat "$_AJ_DEV_DIR/next_steps.txt"
else
    [ -f "$_AJ_DEV_DIR/welcome_message.txt" ] && cat "$_AJ_DEV_DIR/welcome_message.txt"
fi

unset _AJ_DEV_DIR _AJ_ROOT
