.PHONY: dev install format lint test frontend-lint frontend-build phase1 phase2 phase3 setup-wizard doctor up down clean

# ── Development ────────────────────────────────────
dev:
	cd backend && uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload

install:
	cd backend && uv sync

# ── Code Quality ───────────────────────────────────
format:
	cd backend && uv run ruff check --fix . && uv run ruff format .

lint:
	cd backend && uv run ruff check .

test:
	cd backend && uv run pytest

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

phase1:
	python scripts/verify_phase1.py --skip-docker

phase2:
	python scripts/verify_phase2.py

phase3:
	python scripts/verify_phase3.py

setup-wizard:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1

doctor:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/doctor.ps1

# ── Docker ─────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f gateway

# ── Setup ──────────────────────────────────────────
setup:
	@echo "📋 Setting up NexAgent..."
	cp -n config.example.yaml config.yaml 2>/dev/null || true
	cp -n .env.example .env 2>/dev/null || true
	cd backend && uv sync
	@echo "✅ Setup complete! Edit .env and config.yaml, then run: make dev"

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
