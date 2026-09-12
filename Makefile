.PHONY: doctor up down down-hard logs health migrate migrate-down seed-profiles profiles seed-admin psql check test-db-reset mem-report automation-up smoke-llm test-llm check-lane tg-doctor

COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

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

down: ## Stop everything, keep volumes (FR-002)
	$(COMPOSE) down

down-hard: ## Stop and delete the volume — prompts, names the database (FR-002)
	@db=$$(grep '^POSTGRES_DB=' .env | cut -d= -f2); \
	echo "This will permanently DELETE the '$$db' database volume — all data is lost."; \
	read -p "Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	$(COMPOSE) down -v

logs: ## Tail all services' logs
	$(COMPOSE) logs -f

health: ## Call GET /health and pretty-print the report (FR-006)
	@port=$$(grep '^API_PORT=' .env | cut -d= -f2); \
	port=$${port:-8000}; \
	curl -s "http://localhost:$$port/health" | python3 -m json.tool

migrate: ## Run Alembic to head via the one-shot migrate container (FR-011)
	$(COMPOSE) --profile tools run --rm migrate alembic upgrade head

migrate-down: ## Roll back one revision (FR-011, SC-006)
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
	@scripts/check.sh

test-db-reset: ## Recreate injaz_ai_test from migrations; refuses non-_test names (FR-029)
	@scripts/test_db_reset.sh

mem-report: ## docker stats against the 5 GB budget (SC-004)
	@scripts/mem_report.sh

smoke-llm: ## One real structured generation + one real embedding; requires Ollama (FR-028, SC-015)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.smoke_llm $(ARGS)

test-llm: ## Run only @pytest.mark.llm tests — the ones `make check` excludes (FR-027)
	(cd apps/ai-api && uv run pytest -m llm)

check-lane: ## Prove the llm lane admits at most one caller at a time (FR-029, research D-33)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.check_lane

automation-up: ## Start n8n deliberately (FR-003)
	$(COMPOSE) --profile automation up -d n8n

tg-doctor: ## Report Telegram ingestion setup: credential, getMe, subscriptions, per-chat standing (FR-036)
	$(COMPOSE) --profile tools run --rm migrate python -m app.scripts.tg_doctor
