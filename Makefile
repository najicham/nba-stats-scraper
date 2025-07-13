# Makefile for NBA Analytics Platform
.PHONY: help build test deploy clean up down logs

# Default target
.DEFAULT_GOAL := help

# Configuration
PROJECT_ID ?= $(shell gcloud config get-value project)
REGION ?= us-central1

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# Development Environment
up: ## Start development environment
	docker-compose -f docker-compose.dev.yml up -d

down: ## Stop development environment
	docker-compose -f docker-compose.dev.yml down

logs: ## View logs from all services
	docker-compose -f docker-compose.dev.yml logs -f

logs-scrapers: ## View scraper logs only
	docker-compose -f docker-compose.dev.yml logs -f scrapers

logs-processors: ## View processor logs only
	docker-compose -f docker-compose.dev.yml logs -f processors

logs-reportgen: ## View report generator logs only
	docker-compose -f docker-compose.dev.yml logs -f reportgen

restart: ## Restart all services
	docker-compose -f docker-compose.dev.yml restart

# Building
build: ## Build all development images
	docker-compose -f docker-compose.dev.yml build

build-base: ## Build base image only
	docker build -f docker/base.Dockerfile -t nba-base .

build-scrapers: ## Build scrapers image only
	docker build -f scrapers/Dockerfile --build-arg PROJECT_ID=$(PROJECT_ID) -t nba-scrapers .

build-processors: ## Build processors image only
	docker build -f processors/Dockerfile --build-arg PROJECT_ID=$(PROJECT_ID) -t nba-processors .

build-reportgen: ## Build report generator image only
	docker build -f reportgen/Dockerfile --build-arg PROJECT_ID=$(PROJECT_ID) -t nba-reportgen .

build-prod: ## Build production images using Cloud Build
	gcloud builds submit --config docker/cloudbuild.yaml .

# Testing
test: ## Run all tests
	pytest tests/ -v

test-unit: ## Run unit tests only
	pytest tests/unit/ -v

test-integration: ## Run integration tests
	pytest tests/integration/ -v

test-e2e: ## Run end-to-end tests
	pytest tests/e2e/ -v

test-scrapers: ## Test scrapers specifically
	pytest tests/ -k "scraper" -v

test-coverage: ## Run tests with coverage report
	pytest tests/ --cov=scrapers --cov=shared --cov-report=html --cov-report=term

# Code Quality
lint: ## Run linting
	black --check scrapers/ processors/ reportgen/ shared/
	flake8 scrapers/ processors/ reportgen/ shared/
	isort --check-only scrapers/ processors/ reportgen/ shared/

format: ## Format code
	black scrapers/ processors/ reportgen/ shared/
	isort scrapers/ processors/ reportgen/ shared/

type-check: ## Run type checking
	mypy scrapers/ processors/ reportgen/ shared/

quality: lint type-check ## Run all code quality checks

# Local Service Testing
test-scrapers-local: ## Test scrapers service locally
	curl -f http://localhost:8080/health || echo "Scrapers service not running"
	curl -X POST http://localhost:8080/scrape \
		-H "Content-Type: application/json" \
		-d '{"sport": "basketball_nba", "date": "2024-12-15T00:00:00Z", "debug": true}'

test-processors-local: ## Test processors service locally
	curl -f http://localhost:8081/health || echo "Processors service not running"

test-reportgen-local: ## Test report generator service locally
	curl -f http://localhost:8082/health || echo "Report generator service not running"

# Database Management
db-init: ## Initialize local database
	docker-compose -f docker-compose.dev.yml exec postgres psql -U postgres -d nba_dev -c "CREATE SCHEMA IF NOT EXISTS nba_analytics;"

db-reset: ## Reset local database
	docker-compose -f docker-compose.dev.yml exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS nba_dev; CREATE DATABASE nba_dev;"

db-shell: ## Connect to local database shell
	docker-compose -f docker-compose.dev.yml exec postgres psql -U postgres -d nba_dev

# Cloud Deployment
deploy-dev: ## Deploy to development environment
	./bin/deploy_all_services.sh $(PROJECT_ID)-dev $(REGION) true

deploy-staging: ## Deploy to staging environment
	./bin/deploy_all_services.sh $(PROJECT_ID)-staging $(REGION) true

deploy-prod: ## Deploy to production environment
	./bin/deploy_all_services.sh $(PROJECT_ID) $(REGION) true

# Infrastructure
infra-plan: ## Plan Terraform changes
	cd infra && terraform plan -var="project_id=$(PROJECT_ID)"

infra-apply: ## Apply Terraform changes
	cd infra && terraform apply -var="project_id=$(PROJECT_ID)" -auto-approve

infra-destroy: ## Destroy Terraform infrastructure (BE CAREFUL!)
	cd infra && terraform destroy -var="project_id=$(PROJECT_ID)"

# Monitoring
setup-monitoring: ## Set up monitoring and alerts
	chmod +x monitoring/scripts/setup_monitoring.sh
	./monitoring/scripts/setup_monitoring.sh $(PROJECT_ID)

# Utility Commands
clean: ## Clean up containers and images
	docker-compose -f docker-compose.dev.yml down -v
	docker system prune -f
	docker volume prune -f

clean-all: ## Clean everything including images
	docker-compose -f docker-compose.dev.yml down -v
	docker system prune -af
	docker volume prune -f

shell-scrapers: ## Get shell access to scrapers container
	docker-compose -f docker-compose.dev.yml exec scrapers bash

shell-processors: ## Get shell access to processors container
	docker-compose -f docker-compose.dev.yml exec processors bash

shell-reportgen: ## Get shell access to report generator container
	docker-compose -f docker-compose.dev.yml exec reportgen bash

# Requirements Management
freeze-requirements: ## Update all requirements.txt files
	pip freeze > requirements-dev.txt
	docker-compose -f docker-compose.dev.yml exec scrapers pip freeze > scrapers/requirements-frozen.txt
	docker-compose -f docker-compose.dev.yml exec processors pip freeze > processors/requirements-frozen.txt
	docker-compose -f docker-compose.dev.yml exec reportgen pip freeze > reportgen/requirements-frozen.txt

# Documentation
docs-serve: ## Serve documentation locally
	@echo "Documentation available in docs/ directory"
	@echo "Key files:"
	@echo "  - docs/development-workflow.md"
	@echo "  - docs/docker-strategy.md"
	@echo "  - docs/cloud-run-deployment.md"
	@echo "  - docs/service-architecture.md"
	@echo "  - docs/troubleshooting.md"

# Health Checks
health: ## Check health of all services
	@echo "Checking service health..."
	@curl -s http://localhost:8080/health | jq . || echo "❌ Scrapers service not responding"
	@curl -s http://localhost:8081/health | jq . || echo "❌ Processors service not responding"
	@curl -s http://localhost:8082/health | jq . || echo "❌ Report generator service not responding"

# Quick Development Workflow
dev-start: build up db-init ## Quick start for development (build, start services, init DB)
	@echo "🏀 NBA Platform development environment started!"
	@echo "📊 Services:"
	@echo "  - Scrapers: http://localhost:8080"
	@echo "  - Processors: http://localhost:8081" 
	@echo "  - Report Generator: http://localhost:8082"
	@echo "  - PostgreSQL: localhost:5432"
	@echo "  - Redis: localhost:6379"
	@echo "  - MinIO: http://localhost:9001"
	@echo ""
	@echo "🧪 Run 'make test' to run tests"
	@echo "📋 Run 'make logs' to view logs"
	@echo "🏥 Run 'make health' to check service health"

dev-stop: down clean ## Stop development environment and clean up
	@echo "🛑 NBA Platform development environment stopped and cleaned"

# Show current status
status: ## Show status of development environment
	@echo "🏀 NBA Platform Status"
	@echo "====================="
	@docker-compose -f docker-compose.dev.yml ps
	@echo ""
	@echo "🏥 Health Checks:"
	@make health

# Emergency procedures
emergency-stop: ## Emergency stop all services
	docker-compose -f docker-compose.dev.yml kill
	docker stop $$(docker ps -q) 2>/dev/null || true

emergency-reset: emergency-stop clean-all dev-start ## Emergency reset everything
	@echo "🚨 Emergency reset complete"

# Monitoring Commands
status: ## Complete system status check
	./monitoring/scripts/system_status.sh

debug: ## Debug scraper issues
	./monitoring/scripts/scraper_debug.sh

api-test: ## Test API connectivity
	./tools/health/api_connectivity.sh

dev-helpers: ## Load development helper functions
	@echo "Run: source tools/development/dev_helpers.sh"
	@echo "Then use: dev_start, dev_stop, dev_test, dev_debug, dev_logs"

aliases: ## Load monitoring aliases
	@echo "Run: source monitoring/scripts/aliases.sh"
	@echo "Then use: nba-status, nba-debug, nba-test, nba-restart"