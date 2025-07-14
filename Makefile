# NBA Analytics Platform - Simplified Makefile
.PHONY: help deploy test logs clean

# Default target
.DEFAULT_GOAL := help

# Configuration
PROJECT_ID ?= $(shell gcloud config get-value project)

help: ## Show available commands
	@echo "NBA Analytics Platform Commands:"
	@echo ""
	@echo "🚀 Cloud Deployment (Primary):"
	@echo "  make deploy      - Deploy scrapers to Cloud Run"
	@echo "  make test        - Test Cloud Run deployment"
	@echo "  make logs        - View Cloud Run logs"
	@echo "  make deploy-test - Deploy and test"
	@echo ""
	@echo "🏠 Local Development:"
	@echo "  make dev-up      - Start local dev environment"
	@echo "  make dev-down    - Stop local dev environment"
	@echo "  make dev-logs    - View local dev logs"
	@echo "  make dev-test    - Test local services"
	@echo ""
	@echo "🛠️  Utilities:"
	@echo "  make clean       - Clean up local containers"
	@echo "  make help        - Show this help"

# === CLOUD DEPLOYMENT (Primary workflow) ===
deploy: ## Deploy scrapers to Cloud Run
	@./bin/deploy_scrapers.sh

test: ## Test Cloud Run deployment
	@./bin/test_scrapers.sh

logs: ## View Cloud Run logs
	@gcloud run services logs tail nba-scrapers --region us-west2

deploy-test: deploy test ## Deploy and test in one command

# === LOCAL DEVELOPMENT ===
dev-up: ## Start local development environment
	docker-compose -f docker-compose.dev.yml up -d

dev-down: ## Stop local development environment
	docker-compose -f docker-compose.dev.yml down

dev-logs: ## View local development logs
	docker-compose -f docker-compose.dev.yml logs -f

dev-test: ## Test local services
	@echo "Testing local services..."
	@curl -f http://localhost:8080/health || echo "❌ Local scrapers not running"

dev-build: ## Build local development images
	docker-compose -f docker-compose.dev.yml build

# === UTILITIES ===
clean: ## Clean up local containers
	docker-compose -f docker-compose.dev.yml down -v
	docker system prune -f

# === INFRASTRUCTURE (when you need it later) ===
infra-plan: ## Plan Terraform changes
	cd infra && terraform plan -var="project_id=$(PROJECT_ID)"

infra-apply: ## Apply Terraform changes
	cd infra && terraform apply -var="project_id=$(PROJECT_ID)" -auto-approve

# Keep your existing advanced targets in a separate section if needed
include Makefile.advanced  # Optional: move complex targets to separate file

# Deploy from parent directory (preserves module imports)
deploy-parent: ## Deploy from parent directory (fixes imports)
	@./bin/deploy_parent.sh

# === SOPHISTICATED BASE IMAGE APPROACH (30-second deployments!) ===
build-base: ## Build base image with shared dependencies (5 min, one-time)
	@./bin/build_base.sh

build-service: ## Build service image using base (2 min)
	@./bin/build_service.sh

deploy-fast: ## Deploy using pre-built service image (30 seconds!)
	@./bin/deploy_fast.sh

# === SOPHISTICATED WORKFLOWS ===
setup-sophisticated: build-base build-service deploy-fast ## Complete setup (7-8 min one-time)
	@echo "🎉 Sophisticated setup complete!"
	@echo "🚀 Going forward: make code-deploy-fast (30 seconds!)"

# Active development workflow (30 seconds!)
code-deploy-fast: build-service deploy-fast ## Fast code deployment for development

# When shared dependencies change (rebuild base)
rebuild-base: build-base build-service deploy-fast ## Rebuild base image and deploy

# === DEPLOYMENT SPEED COMPARISON ===
speed-help: ## Show deployment speed comparison
	@echo "🚀 NBA Scrapers Deployment Speed Comparison:"
	@echo ""
	@echo "BEFORE (current):"
	@echo "  make deploy           2-3 minutes"
	@echo ""
	@echo "AFTER (sophisticated):"
	@echo "  make setup-sophisticated    7-8 minutes (ONE TIME)"
	@echo "  make code-deploy-fast       30 seconds! (ONGOING)"
	@echo ""
	@echo "💡 Time savings after 10 deployments: ~20 minutes saved"
	@echo "💡 Time savings after 20 deployments: ~40 minutes saved"

# Show complete workflow
workflow-help: ## Show complete development workflow
	@echo "🏗️ NBA Scrapers Sophisticated Workflow:"
	@echo ""
	@echo "🔧 INITIAL SETUP (one-time):"
	@echo "  make setup-sophisticated     # 7-8 minutes"
	@echo ""
	@echo "⚡ ACTIVE DEVELOPMENT:"
	@echo "  [edit code]"
	@echo "  make code-deploy-fast        # 30 seconds!"
	@echo "  make test                   # Test changes"
	@echo "  [repeat rapidly]"
	@echo ""
	@echo "🔄 WHEN REQUIREMENTS CHANGE:"
	@echo "  Edit scrapers/requirements.txt"
	@echo "  make code-deploy-fast        # Rebuilds with new deps"
	@echo ""
	@echo "🔄 WHEN SHARED DEPS CHANGE:"
	@echo "  Edit shared/requirements.txt"
	@echo "  make rebuild-base           # Rebuilds base + service"
	@echo ""
	@echo "📊 SPEED COMPARISON:"
	@echo "  make speed-help"
