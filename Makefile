.PHONY: help dev up down build logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Development ─────────────────────────────────────────────────────────────

dev: ## Start infrastructure only (MySQL, Redis, ChromaDB) for local dev
	docker compose up -d mysql redis chromadb
	@echo "\n✓ Infrastructure started"
	@echo "  MySQL:    localhost:3306"
	@echo "  Redis:    localhost:6379"
	@echo "  ChromaDB: localhost:8000"

up: ## Start all services
	docker compose up -d
	@echo "\n✓ All services started"
	@echo "  Platform: http://localhost"

down: ## Stop all services
	docker compose down

build: ## Build all Docker images
	docker compose build

rebuild: ## Rebuild all images from scratch
	docker compose build --no-cache

# ─── Logs ────────────────────────────────────────────────────────────────────

logs: ## Follow all service logs
	docker compose logs -f

logs-api: ## Follow API server logs
	docker compose logs -f api-server

logs-workers: ## Follow worker logs
	docker compose logs -f celery-worker-preprocessing celery-worker-rag celery-worker-report

# ─── Database ────────────────────────────────────────────────────────────────

db-shell: ## Open MySQL shell
	docker compose exec mysql mysql -uptm_user -pptm_password_change_me ptm_platform

db-reset: ## Reset database (WARNING: destroys data)
	docker compose down -v
	docker volume rm ptm-mysql-data 2>/dev/null || true
	docker compose up -d mysql
	@echo "Database reset. Restart api-server to recreate tables."

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove all containers, volumes, and images
	docker compose down -v --rmi local
	@echo "Cleaned up all containers, volumes, and local images"

# ─── Frontend Dev ────────────────────────────────────────────────────────────

frontend-dev: ## Start frontend in dev mode (requires npm install first)
	cd frontend && npm run dev

frontend-install: ## Install frontend dependencies
	cd frontend && npm install

# ─── API Server Dev ──────────────────────────────────────────────────────────

api-dev: ## Start API server in dev mode
	cd api-server && uvicorn app.main:app --reload --port 8000
