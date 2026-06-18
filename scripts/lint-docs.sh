#!/usr/bin/env bash
# Validate + run the documentation linters (cspell + markdownlint).
#
# These are Node tools, not Python — this script ensures Node is present and
# the pinned versions (package.json) are installed, then runs them. It is the
# single entry point used by `make lint-docs`, the pre-commit hook, CI, and the
# "Lint: docs" VS Code task, so the editor and the gate never disagree.
#
#   ./scripts/lint-docs.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

# --- validate: Node + npm ---------------------------------------------------
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}✗${NC} Node.js + npm are required for the doc linters (cspell, markdownlint)."
    echo "  Install Node 18+ (https://nodejs.org, nvm, or your package manager), then re-run."
    echo "  (The Python tooling does not need Node — only documentation linting does.)"
    exit 1
fi

# --- install: pinned tools, only when stale ---------------------------------
if [ ! -d node_modules ] || [ package.json -nt node_modules ]; then
    echo -e "${CYAN}==>${NC} Installing doc-lint tools (npm install) ..."
    npm install --no-audit --no-fund --silent
fi

# --- run --------------------------------------------------------------------
echo -e "${CYAN}==>${NC} cspell (spelling)"
./node_modules/.bin/cspell --no-progress --no-summary "**/*"
echo -e "${CYAN}==>${NC} markdownlint (markdown style)"
./node_modules/.bin/markdownlint-cli2 "**/*.md"
echo -e "${GREEN}✓${NC} docs lint clean"
