.PHONY: up down down-v ps logs seed lint format test verify

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
up:
	docker compose up -d

down:
	docker compose down

down-v:
	docker compose down -v

ps:
	docker compose ps

logs:
ifndef SERVICE
	$(error Usage: make logs SERVICE=<name>)
endif
	docker compose logs -f $(SERVICE)

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
seed:
	bash scripts/seed_data.sh

verify:
	bash scripts/verify.sh

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------
lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v
