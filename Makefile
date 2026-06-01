VMWARE_NAT_PROXY ?= http://192.168.127.1:10808
DEFAULT_NO_PROXY ?= localhost,127.0.0.1,postgres,redis,api,prometheus,grafana

export HTTP_PROXY ?= $(VMWARE_NAT_PROXY)
export HTTPS_PROXY ?= $(VMWARE_NAT_PROXY)
export NO_PROXY ?= $(DEFAULT_NO_PROXY)

.PHONY: dev-up dev-down logs migrate test lint test-api docker-api-test real-provider-regression observability-up observability-down install-local

dev-up:
	docker compose up --build

dev-down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api pytest

test-api:
	docker compose run --rm api pytest tests/test_api_integration.py

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
