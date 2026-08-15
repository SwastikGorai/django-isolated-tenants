SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -f compose.test.yml
POSTGRES_PORT ?= 55432

E2E_ENV := \
	RUN_POSTGRES_E2E=1 \
	E2E_POSTGRES_DB_ACME=isolated_tenants_acme \
	E2E_POSTGRES_DB_GLOBEX=isolated_tenants_globex \
	E2E_POSTGRES_USER=postgres \
	E2E_POSTGRES_PASSWORD=postgres \
	E2E_POSTGRES_HOST=127.0.0.1 \
	E2E_POSTGRES_PORT=$(POSTGRES_PORT)

.PHONY: help check-tools sync services-up services-down services-logs test test-unit test-e2e lint check clean

help: ## Show available test targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-tools: ## Verify required WSL development tools are available
	@command -v docker >/dev/null || { echo "docker is unavailable in WSL; enable Docker Desktop WSL integration" >&2; exit 1; }
	@docker compose version >/dev/null || { echo "the Docker Compose plugin is unavailable in WSL" >&2; exit 1; }
	@command -v uv >/dev/null || { echo "uv is unavailable in WSL; install uv before running tests" >&2; exit 1; }
	@docker info >/dev/null || { echo "the Docker engine is not running or unavailable to WSL" >&2; exit 1; }

sync: check-tools ## Synchronize the locked WSL test environment
	@uv sync --locked --extra test

services-up: check-tools ## Start disposable PostgreSQL and wait until healthy
	@E2E_POSTGRES_PORT=$(POSTGRES_PORT) $(COMPOSE) up --detach --wait postgres

services-down: ## Stop test services and remove their volumes
	@E2E_POSTGRES_PORT=$(POSTGRES_PORT) $(COMPOSE) down --volumes --remove-orphans

services-logs: ## Show PostgreSQL test-service logs
	@E2E_POSTGRES_PORT=$(POSTGRES_PORT) $(COMPOSE) logs postgres

test-unit: sync ## Run fast tests without PostgreSQL E2E scenarios
	@uv run pytest -m "not postgres_e2e" -q

test-e2e: sync services-up ## Run real PostgreSQL E2E scenarios, then tear services down
	@status=0; \
	$(E2E_ENV) uv run pytest -m postgres_e2e -q || status=$$?; \
	E2E_POSTGRES_PORT=$(POSTGRES_PORT) $(COMPOSE) down --volumes --remove-orphans; \
	exit $$status

test: test-unit test-e2e ## Run unit/integration tests followed by PostgreSQL E2E tests

lint: sync ## Run Ruff
	@uv run ruff check .

check: lint test ## Run lint and every test layer

clean: services-down ## Remove disposable test services
