#!/usr/bin/env bash
# One-command dev environment setup for ai-journal.
#
#   ./scripts/setup.sh
#
# Idempotent: safe to re-run. Creates .venv, installs the package editable
# with dev + server extras, and (optionally) installs the pre-commit hook.
# See docs/DEVELOPMENT.md for the full guide.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}==>${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
die()   { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# --- 1. Find a Python 3.11+ interpreter ------------------------------------
# tomllib (stdlib) requires 3.11; pyproject's requires-python enforces it too.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.11+ not found. Install it and re-run (see docs/DEVELOPMENT.md)."
ok "Using $($PYTHON --version) ($PYTHON)"

# --- 2. Create the virtual environment -------------------------------------
if [ -d .venv ]; then
    ok ".venv already exists"
else
    info "Creating .venv ..."
    "$PYTHON" -m venv .venv
    ok ".venv created"
fi

# --- 3. Install the package + dev/server extras (editable) ------------------
info "Upgrading pip and installing ai-journal[dev,server] (editable) ..."
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -e ".[dev,server]"
ok "Dependencies installed"

# --- 4. Documentation linters (Node: cspell + markdownlint) ----------------
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    info "Installing doc-lint tools (npm install) ..."
    npm install --no-audit --no-fund --silent
    ok "Doc linters installed (cspell, markdownlint)"
else
    warn "Node.js not found — documentation linting (cspell, markdownlint) will be"
    warn "  unavailable until you install Node 18+. The Python tooling works without it."
fi

# --- 5. Optional: git hooks (pre-commit + pre-push) ------------------------
if [ -d .git ]; then
    if [ -f .pre-commit-config.yaml ]; then
        info "Installing git hooks ..."
        ./.venv/bin/pre-commit install >/dev/null
        ok "Hooks installed — pre-commit: ruff + mypy + docs lint; pre-push: tests"
    fi
else
    warn "Not a git repo — skipping git hook install"
fi

echo ""
ok "Setup complete."
echo ""
echo "Next steps:"
echo "  • Activate:    source .venv/bin/activate   (VS Code terminals do this automatically)"
echo "  • Run checks:  make check"
echo "  • Run tests:   make test"
echo "  • In VS Code:  reload the window so Pylance picks up .venv/bin/python"
echo ""
echo "Full guide: docs/DEVELOPMENT.md"
