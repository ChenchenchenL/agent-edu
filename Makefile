VMWARE_NAT_PROXY ?= http://192.168.29.1:10808
DEFAULT_NO_PROXY ?= localhost,127.0.0.1,postgres,redis,api,prometheus,grafana

export HTTP_PROXY ?= $(VMWARE_NAT_PROXY)
export HTTPS_PROXY ?= $(VMWARE_NAT_PROXY)
export NO_PROXY ?= $(DEFAULT_NO_PROXY)

.PHONY: dev-up dev-down logs logs-api logs-worker ps migrate test lint test-api \
	mvp-smoke mvp-regression mvp-check docker-mvp-check frontend-build release-check \
	docker-api-test real-provider-regression observability-up observability-down \
	install-local smoke-api smoke-stack frontend-dev-doc memory-check reflection-check

dev-up:
	docker compose up --build

dev-down:
	docker compose down

logs:
	docker compose logs -f api

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

ps:
	docker compose ps

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api pytest

test-api:
	docker compose run --rm api pytest tests/test_api_integration.py

# ---------------------------------------------------------------------------
# MVP validation baseline (layered)
# ---------------------------------------------------------------------------

# Fastest: acceptance main path only. Use during development.
mvp-smoke:
	docker compose build api
	docker compose run --rm api pytest tests/test_mvp_acceptance.py -v

# Core regression: acceptance + api integration + worker + task runtime.
mvp-regression:
	docker compose build api
	docker compose run --rm api pytest \
		tests/test_mvp_acceptance.py \
		tests/test_api_integration.py \
		tests/test_worker_runtime.py \
		tests/test_task_runtime_skill.py \
		-q

# Default release gate: in-process regression + docker blackbox.
mvp-check: mvp-regression docker-api-test

# Docker-only blackbox: requires running stack, runs HTTP-only tests.
#
# Limitation: docker compose's `.env` takes precedence over `--env-file`, so
# the blackbox inherits the dev environment's LLM provider settings. If the
# dev `.env` points at a real provider, the blackbox will be slow and require
# credentials. Workaround:
#
#   docker compose --env-file blackbox.env.example up -d postgres redis api
#   docker compose --env-file blackbox.env.example --profile test run --rm \
#       -e AGENT_EDU_API_BASE_URL=http://api:8000 \
#       tester pytest tests/test_mvp_blackbox.py -q
#
# Until the compose stack supports a dedicated blackbox profile, this target
# is not included in `release-check`.
docker-mvp-check:
	docker compose up -d --build postgres redis api
	docker compose --profile test run --rm \
		-e AGENT_EDU_API_BASE_URL=http://api:8000 \
		-e AGENT_EDU_LLM_PROVIDER=mock \
		-e AGENT_EDU_LLM_MODEL=mock-tutor-v1 \
		-e AGENT_EDU_EMBEDDING_PROVIDER=mock \
		-e AGENT_EDU_EMBEDDING_MODEL=mock-embedding-v1 \
		-e AGENT_EDU_OPERATOR_API_KEY=secret-operator \
		tester \
		pytest tests/test_mvp_blackbox.py tests/test_docker_blackbox.py -q

# Frontend build (TypeScript + Vite). Used by release-check.
frontend-build:
	npm --prefix packages/frontend run build

# Full release gate: lint + frontend build + backend regression + docker blackbox.
release-check: lint frontend-build mvp-check

# Legacy alias kept for back-compat.
docker-api-test:
	docker compose up -d --build postgres redis api
	docker compose --profile test run --rm --no-deps \
		-e AGENT_EDU_API_BASE_URL=http://api:8000 \
		tester \
		pytest tests/test_docker_blackbox.py -q

real-provider-regression:
	docker compose up -d --build postgres redis api
	docker compose --profile test run --rm --no-deps \
		-e AGENT_EDU_API_BASE_URL=http://api:8000 \
		-e AGENT_EDU_RUN_REAL_PROVIDER_REGRESSION=1 \
		tester \
		pytest tests/test_real_provider_regression.py -q

observability-up:
	docker compose up -d postgres redis api
	docker compose --profile observability up -d prometheus grafana

observability-down:
	docker compose --profile observability stop prometheus grafana

lint:
	npm run lint

install-local:
	pip install -e .[dev]

smoke-api:
	@echo "Checking API health..."
	@curl -f http://localhost:8000/healthz || (echo "API health check failed" && exit 1)
	@echo ""
	@echo "Checking API readiness..."
	@curl -f http://localhost:8000/readyz || (echo "API readiness check failed" && exit 1)
	@echo ""
	@echo "API smoke test passed"

smoke-stack:
	@echo "=== Stack Smoke Test ==="
	@echo ""
	@echo "1. Checking service status..."
	@docker compose ps
	@echo ""
	@echo "2. Checking API health..."
	@curl -f http://localhost:8000/healthz || (echo "API health check failed" && exit 1)
	@echo ""
	@echo "3. Checking API readiness..."
	@curl -f http://localhost:8000/readyz || (echo "API readiness check failed" && exit 1)
	@echo ""
	@echo "4. Checking worker status..."
	@docker compose ps worker | grep -q "running" || (echo "Worker is not running" && exit 1)
	@echo "Worker is running"
	@echo ""
	@echo "=== Stack smoke test passed ==="
	@echo ""
	@echo "Frontend is not part of Docker stack."
	@echo "To start frontend: cd packages/frontend && npm run dev"
	@echo "Then open: http://localhost:5173"

frontend-dev-doc:
	@echo "=== Frontend Development ==="
	@echo ""
	@echo "Start frontend dev server:"
	@echo "  cd packages/frontend"
	@echo "  npm install  # if not already done"
	@echo "  npm run dev"
	@echo ""
	@echo "Access frontend at: http://localhost:5173"
	@echo ""
	@echo "Environment variables (optional):"
	@echo "  VITE_API_PROXY_TARGET - API proxy target (default: http://localhost:8000)"
	@echo "  VITE_API_BASE_URL     - API base URL (only for non-standard setups)"
	@echo ""
	@echo "Prerequisites:"
	@echo "  Backend must be running: make dev-up"
	@echo ""
	@echo "For detailed instructions, see: docs/LOCAL_DEV_RUNBOOK.md"

memory-check:
	docker compose build api
	docker compose run --rm api pytest \
		tests/test_memory_service.py \
		tests/test_memory_maintenance_service.py \
		tests/test_memory_quality_regression.py \
		tests/test_memory_fail_closed.py \
		tests/test_memory_downstream_contracts.py \
		-v

reflection-check:
	docker compose build api
	docker compose run --rm api pytest \
		tests/test_reflection_skill_evolution_regression.py \
		-v
