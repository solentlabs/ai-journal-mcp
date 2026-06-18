# ai-journal — developer task runner.
# Every recipe is pinned to the project venv so the editor, this Makefile,
# CI, and the pre-commit hook all run the identical tool versions (SSOT).
# Run `make` or `make help` for the menu. Full guide: docs/DEVELOPMENT.md

VENV_BIN := .venv/bin
PY       := $(VENV_BIN)/python

.DEFAULT_GOAL := help
.PHONY: help setup verify test test-quick lint lint-fix format format-check \
        type-check lint-docs check clean reindex install-hooks

help: ## Show this help
	@echo "ai-journal — make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv and install the package + dev tools (idempotent)
	@bash scripts/setup.sh

verify: ## Diagnose the dev environment (read-only)
	@bash scripts/verify-setup.sh

test: ## Run the full test suite with coverage
	@$(VENV_BIN)/pytest --cov=ai_journal --cov-report=term-missing

test-quick: ## Run tests without coverage (fast feedback)
	@$(VENV_BIN)/pytest

lint: ## Lint with Ruff
	@$(VENV_BIN)/ruff check .

lint-fix: ## Lint with Ruff and auto-fix
	@$(VENV_BIN)/ruff check --fix .

format: ## Format with Ruff
	@$(VENV_BIN)/ruff format .

format-check: ## Check formatting without writing changes
	@$(VENV_BIN)/ruff format --check .

type-check: ## Type-check with mypy
	@$(VENV_BIN)/mypy

lint-docs: ## Lint docs (cspell + markdownlint; validates/installs Node tools)
	@bash scripts/lint-docs.sh

check: lint format-check type-check lint-docs test ## Run everything CI runs (the gate)
	@echo "All checks passed."

clean: ## Remove caches and the disposable index/coverage artifacts
	@rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."

reindex: ## Rebuild the local search index from configured journals
	@$(VENV_BIN)/ai-journal reindex

install-hooks: ## Install the pre-commit git hook
	@$(VENV_BIN)/pre-commit install
