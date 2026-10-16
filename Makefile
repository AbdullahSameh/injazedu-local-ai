.PHONY: doctor up down down-hard logs health migrate migrate-down seed-profiles profiles seed-admin psql check test-db-reset mem-report automation-up logs-ui smoke-llm smoke-moderation smoke-attention qualify qualify-moderation test-llm check-lane tg-doctor

# Production's .env says DEPLOYMENT_ENV=production (docs/runbooks/production-deployment.md): there
# every target uses the production override too — so `make up` can never publish Postgres or Redis
# on 0.0.0.0 — and the destructive targets and the test suite refuse to run (runbook §12).
# Development's .env has no such line, and nothing below changes for it.
_PRODUCTION := $(shell grep -qs '^DEPLOYMENT_ENV=production' .env && echo yes)
ifeq ($(_PRODUCTION),yes)
COMPOSE_FILES ?= -f infra/docker-compose.yml -f infra/docker-compose.prod.yml
else
COMPOSE_FILES ?= -f infra/docker-compose.yml
endif
COMPOSE := docker compose $(COMPOSE_FILES) --env-file .env

define refuse_in_production
@if [ "$(_PRODUCTION)" = "yes" ]; then echo "make $@: refused on production (.env has DEPLOYMENT_ENV=production)" >&2; exit 1; fi
endef

doctor: ## Check prerequisites: Docker memory, Ollama, .env completeness (FR-034)
	@echo "== .env =="
	@if [ ! -f .env ]; then echo "  MISSING: copy .env.example to .env and fill it in"; exit 1; fi
	@if grep -v '^#' .env | grep -q 'CHANGE_ME'; then \
		echo "  INCOMPLETE: .env still has placeholders:"; \
		grep -v '^#' .env | grep 'CHANGE_ME' | cut -d= -f1 | sed 's/^/    /'; \
	else \
		echo "  OK: .env has no CHANGE_ME placeholders"; \
	fi
	@echo "== Docker =="
	@if ! docker info >/dev/null 2>&1; then echo "  NOT RUNNING: start Docker Desktop"; exit 1; fi
	@mem_bytes=$$(docker info --format '{{.MemTotal}}' 2>/dev/null); \
	mem_gb=$$(python3 -c "print(round($$mem_bytes/1073741824,1))"); \
	limit=5368709120; \
	if [ "$$mem_bytes" -gt "$$limit" ]; then \
		echo "  TOO HIGH: Docker memory is $${mem_gb} GiB — reduce to 5 GB (Settings -> Resources -> Memory -> Apply & Restart)"; \
	else \
		echo "  OK: Docker memory is $${mem_gb} GiB (<= 5 GB)"; \
	fi
	@echo "== Ollama =="
	@if curl -s -o /dev/null --max-time 2 http://localhost:11434/api/version; then \
		echo "  OK: Ollama reachable on :11434"; \
	else \
		echo "  UNREACHABLE: start Ollama"; \
	fi
	@echo "== Ollama environment variables =="
	@scripts/check_ollama_env.sh || true
	@echo "== Model profiles (M1) =="
	@if ! docker info >/dev/null 2>&1; then \
		echo "  SKIPPED: Docker not running"; \
	elif ! $(COMPOSE) exec -T postgres pg_isready -q >/dev/null 2>&1; then \
		echo "  SKIPPED: Postgres not reachable (run 'make up' first)"; \
	else \
		$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.check_profiles_pulled || true; \
	fi

up: ## Start the default services (FR-001)
	$(COMPOSE) up -d --build

down: ## Stop everything, keep volumes (FR-002); '*' includes opt-in profiles (dozzle, n8n, migrate)
	$(COMPOSE) --profile '*' down

down-hard: ## Stop and delete the volume — prompts, names the database (FR-002)
	$(refuse_in_production)
	@db=$$(grep '^POSTGRES_DB=' .env | cut -d= -f2); \
	echo "This will permanently DELETE the '$$db' database volume — all data is lost."; \
	read -p "Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	$(COMPOSE) --profile '*' down -v

logs: ## Tail all services' logs
	$(COMPOSE) logs -f

health: ## Call GET /health and pretty-print the report (FR-006)
	@port=$$(grep '^API_HOST_PORT=' .env | cut -d= -f2); \
	port=$${port:-$$(grep '^API_PORT=' .env | cut -d= -f2)}; \
	port=$${port:-8000}; \
	curl -s "http://localhost:$$port/health" | python3 -m json.tool

migrate: ## Run Alembic to head via the one-shot migrate container (FR-011)
	$(COMPOSE) --profile tools run --rm migrate alembic upgrade head

migrate-down: ## Roll back one revision (FR-011, SC-006)
	$(refuse_in_production)
	$(COMPOSE) --profile tools run --rm migrate alembic downgrade -1

seed-profiles: ## Seed the model roster into model_profiles, idempotent (FR-010, research D-36)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.seed_profiles

profiles: ## Print the roster: name, role, model, endpoint, dim, active (FR-049)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.print_profiles

seed-admin: ## Create or update the panel account (FR-022)
	$(COMPOSE) exec ai-control php artisan app:seed-admin

psql: ## Open psql inside the postgres container (research D-20)
	@user=$$(grep '^POSTGRES_USER=' .env | cut -d= -f2); \
	db=$$(grep '^POSTGRES_DB=' .env | cut -d= -f2); \
	$(COMPOSE) exec postgres psql -U "$$user" -d "$$db"

check: ## Quality gate: ruff, mypy, pytest, PHP feature test, secret scan (FR-025)
	$(refuse_in_production)
	@scripts/check.sh

test-db-reset: ## Recreate injaz_ai_test from migrations; refuses non-_test names (FR-029)
	$(refuse_in_production)
	@scripts/test_db_reset.sh

mem-report: ## docker stats against the 5 GB budget (SC-004)
	@scripts/mem_report.sh

smoke-llm: ## One real structured generation + one real embedding; requires Ollama (FR-028, SC-015)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.smoke_llm $(ARGS)

smoke-moderation: ## Classify FIXTURES=<path outside the repo> against the real model before activating it (runbook §C TG-M5, SC-001)
	@if [ -n "$(FIXTURES)" ]; then \
		$(COMPOSE) --profile tools run --rm -T migrate python -m app.scripts.smoke_moderation $(ARGS) < "$(FIXTURES)"; \
	else \
		$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.smoke_moderation $(ARGS); \
	fi

smoke-attention: ## Quick check of the attention pair on FIXTURES=<path outside the repo>, ARGS='--profile … --prompt …'; the qualification's own path (TG-M5.3)
	@if [ -n "$(FIXTURES)" ]; then \
		$(COMPOSE) --profile tools run --rm -T migrate python -m app.scripts.smoke_attention $(ARGS) < "$(FIXTURES)"; \
	else \
		$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.smoke_attention $(ARGS); \
	fi

# `~/…` is expanded here: zsh leaves `FIXTURES_DIR=~/…` unexpanded on the command line.
_QUALIFY_FIXTURES = $(abspath $(patsubst ~/%,$(HOME)/%,$(FIXTURES_DIR)))

qualify: ## Qualify TASK=attention|moderation PROFILE=<profile> over FIXTURES_DIR=<dir outside the repo> [PROMPT=<version> | CANDIDATE=<file in FIXTURES_DIR>] [REPEAT=2] [MODERATION_P95_MS=<ms>] [SERVING=single|concurrent]; read-only (TG-M5.3)
	@if [ -z "$(TASK)" ] || [ -z "$(PROFILE)" ] || [ -z "$(FIXTURES_DIR)" ]; then \
		echo "usage: make qualify TASK=attention|moderation PROFILE=<profile> FIXTURES_DIR=<dir outside the repo> [PROMPT=<version> | CANDIDATE=<file in FIXTURES_DIR>] [REPEAT=2] [MODERATION_P95_MS=<ms>] [SERVING=single|concurrent]" >&2; \
		exit 2; \
	fi
	@if [ ! -d "$(_QUALIFY_FIXTURES)" ]; then \
		echo "qualify: no fixtures directory at $(_QUALIFY_FIXTURES)" >&2; \
		exit 2; \
	fi
	$(COMPOSE) --profile tools run --rm -T -v "$(_QUALIFY_FIXTURES)":/fixtures:ro migrate \
		python -m app.scripts.qualification --task $(TASK) --profile $(PROFILE) \
		$(if $(PROMPT),--prompt $(PROMPT)) $(if $(CANDIDATE),--candidate-file /fixtures/$(CANDIDATE)) \
		$(if $(MODERATION_P95_MS),--moderation-p95-ms $(MODERATION_P95_MS)) $(if $(SERVING),--serving $(SERVING)) \
		--fixtures-dir /fixtures --repeat $(or $(REPEAT),2)

qualify-moderation: ## Alias of `make qualify TASK=moderation`: PROFILE=<profile> [PROMPT=<version>] FIXTURES_DIR=<dir outside the repo> [REPEAT=2]; read-only (TG-M5.2)
	@if [ -z "$(PROFILE)" ] || [ -z "$(FIXTURES_DIR)" ]; then \
		echo "usage: make qualify-moderation PROFILE=<profile> FIXTURES_DIR=<dir outside the repo> [PROMPT=<version>] [REPEAT=2]" >&2; \
		exit 2; \
	fi
	@if [ ! -d "$(_QUALIFY_FIXTURES)" ]; then \
		echo "qualify-moderation: no fixtures directory at $(_QUALIFY_FIXTURES)" >&2; \
		exit 2; \
	fi
	$(COMPOSE) --profile tools run --rm -T -v "$(_QUALIFY_FIXTURES)":/fixtures:ro migrate \
		python -m app.scripts.qualification --task moderation --profile $(PROFILE) $(if $(PROMPT),--prompt $(PROMPT)) \
		--fixtures-dir /fixtures --repeat $(or $(REPEAT),2)

test-llm: ## Run only @pytest.mark.llm tests — the ones `make check` excludes (FR-027)
	(cd apps/ai-api && uv run pytest -m llm)

check-lane: ## Prove the llm lane admits at most one caller at a time (FR-029, research D-33)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.check_lane

automation-up: ## Start n8n deliberately (FR-003)
	$(COMPOSE) --profile automation up -d n8n

logs-ui: ## Start Dozzle (dev-only browser log viewer) on http://localhost:9999
	$(COMPOSE) --profile devtools up -d dozzle

tg-doctor: ## Report Telegram ingestion setup: credential, getMe, subscriptions, per-chat standing (FR-036)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.tg_doctor
