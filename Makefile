.PHONY: setup dev dev-api dev-web install test lint format db-migrate clean

# ═══════════════════════════════════════════════════════════════
# Meridian RAG System - Makefile
# ═══════════════════════════════════════════════════════════════
# All dependencies are LOCAL - no global packages required
# Python: uses apps/api/.venv
# Node.js: uses local node_modules
# ═══════════════════════════════════════════════════════════════

# Python virtual environment path
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
ALEMBIC := $(VENV)/bin/alembic

# ═══════════════════════════════════════════════════════════════
# Setup (run this first)
# ═══════════════════════════════════════════════════════════════

# Full project setup
setup:
	@chmod +x setup.sh && ./setup.sh

# ═══════════════════════════════════════════════════════════════
# Development
# ═══════════════════════════════════════════════════════════════

# Start all services (frontend + backend in parallel)
dev:
	@echo "Starting Meridian..."
	@echo "API:  http://localhost:8000/docs"
	@echo "Web:  http://localhost:3000"
	@echo ""
	@make -j2 dev-api dev-web

# Start backend only (uses local venv)
dev-api:
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start frontend only (uses local node_modules)
dev-web:
	@cd apps/web && pnpm dev

# ═══════════════════════════════════════════════════════════════
# Installation (prefer 'make setup' for full setup)
# ═══════════════════════════════════════════════════════════════

# Install all dependencies
install: install-web install-api

# Install frontend dependencies
install-web:
	@echo "Installing frontend dependencies..."
	@pnpm install

# Install backend dependencies (creates venv if needed)
install-api:
	@echo "Setting up Python virtual environment..."
	@cd apps/api && \
		python3 -m venv .venv && \
		.venv/bin/pip install --upgrade pip -q && \
		.venv/bin/pip install -e ".[dev]"

# ═══════════════════════════════════════════════════════════════
# Testing
# ═══════════════════════════════════════════════════════════════

test: test-api test-web

test-api:
	@cd apps/api && $(PYTEST) -v

test-web:
	@cd apps/web && pnpm test

# ═══════════════════════════════════════════════════════════════
# Linting & Formatting
# ═══════════════════════════════════════════════════════════════

lint: lint-api lint-web

lint-api:
	@cd apps/api && $(RUFF) check .

lint-web:
	@cd apps/web && pnpm lint

format: format-api format-web

format-api:
	@cd apps/api && $(RUFF) format .

format-web:
	@cd apps/web && pnpm format

# ═══════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════

db-migrate:
	@cd apps/api && $(ALEMBIC) upgrade head

db-revision:
	@cd apps/api && $(ALEMBIC) revision --autogenerate -m "$(msg)"

# ═══════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════

build: build-web

build-web:
	@cd apps/web && pnpm build

# ═══════════════════════════════════════════════════════════════
# Clean
# ═══════════════════════════════════════════════════════════════

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf apps/web/.next apps/web/node_modules
	@rm -rf apps/api/__pycache__ apps/api/.venv apps/api/*.egg-info
	@rm -rf node_modules
	@rm -rf .pnpm-store
	@echo "Done. Run 'make setup' to reinstall."

# ═══════════════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════════════

help:
	@echo "Meridian RAG System"
	@echo ""
	@echo "Setup:"
	@echo "  make setup      - Full project setup (run this first)"
	@echo ""
	@echo "Development:"
	@echo "  make dev        - Start frontend + backend"
	@echo "  make dev-api    - Start backend only"
	@echo "  make dev-web    - Start frontend only"
	@echo ""
	@echo "Testing:"
	@echo "  make test       - Run all tests"
	@echo "  make test-api   - Run backend tests"
	@echo "  make test-web   - Run frontend tests"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint       - Run linters"
	@echo "  make format     - Format code"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate           - Run migrations"
	@echo "  make db-revision msg='x'  - Create migration"
	@echo ""
	@echo "Other:"
	@echo "  make build      - Build for production"
	@echo "  make clean      - Remove all dependencies"
