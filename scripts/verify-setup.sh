#!/usr/bin/env bash
# Diagnose a dev environment. Read-only: reports problems and the exact
# command to fix each, but changes nothing. Run this when the editor shows
# unexpected import errors or a tool is "not found".
#
#   ./scripts/verify-setup.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
bad()  { echo -e "${YELLOW}!${NC} $*"; PROBLEMS=$((PROBLEMS + 1)); }
PROBLEMS=0

echo ""
echo "ai-journal — dev environment check"
echo "=================================="

# 1. venv exists
echo -e "${CYAN}[1/6]${NC} Virtual environment"
if [ -x .venv/bin/python ]; then
    ok ".venv present ($(./.venv/bin/python --version 2>&1))"
else
    bad ".venv missing — run: ./scripts/setup.sh"
fi

# 2. Python is 3.11+
echo -e "${CYAN}[2/6]${NC} Python version"
if [ -x .venv/bin/python ] && ./.venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    ok "Python 3.11+"
else
    bad "venv Python is older than 3.11 — recreate: rm -rf .venv && ./scripts/setup.sh"
fi

# 3. Package + key imports resolve (this is what fixes editor "problems")
echo -e "${CYAN}[3/6]${NC} Imports"
if [ -x .venv/bin/python ] && ./.venv/bin/python -c 'import ai_journal, yaml, mcp' 2>/dev/null; then
    ok "ai_journal, yaml, mcp all importable"
else
    bad "imports fail — run: ./.venv/bin/pip install -e \".[dev,server]\""
fi

# 4. Dev tools functional
echo -e "${CYAN}[4/6]${NC} Dev tools"
for tool in ruff mypy pytest; do
    if [ -x ".venv/bin/$tool" ] && "./.venv/bin/$tool" --version >/dev/null 2>&1; then
        ok "$tool"
    else
        bad "$tool not found — run: ./.venv/bin/pip install -e \".[dev]\""
    fi
done

# 5. Documentation linters (Node)
echo -e "${CYAN}[5/6]${NC} Doc linters (Node)"
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    if [ -x node_modules/.bin/cspell ] && [ -x node_modules/.bin/markdownlint-cli2 ]; then
        ok "cspell + markdownlint installed ($(node --version))"
    else
        bad "Node present but tools not installed — run: npm install"
    fi
else
    bad "Node.js not found — needed for cspell/markdownlint. Install Node 18+."
fi

# 6. Git hooks (optional)
echo -e "${CYAN}[6/6]${NC} Git hooks"
if [ -f .git/hooks/pre-commit ] && [ -f .git/hooks/pre-push ]; then
    ok "pre-commit + pre-push installed"
elif [ -f .git/hooks/pre-commit ]; then
    bad "pre-commit only — run: ./.venv/bin/pre-commit install (installs pre-push too)"
else
    bad "not installed (optional) — run: ./.venv/bin/pre-commit install"
fi

echo ""
if [ "$PROBLEMS" -eq 0 ]; then
    ok "All checks passed — environment is ready."
else
    echo -e "${YELLOW}$PROBLEMS issue(s) found.${NC} Fix with the commands above, or just run ./scripts/setup.sh."
fi
echo ""
exit 0
