# Development Workflow

## Overview

This guide covers day-to-day development workflows for the NBA analytics platform, including local development, testing, and deployment procedures.

## Quick Start for New Developers

### 🚀 **Initial Setup**
```bash
# 1. Clone repository
git clone https://github.com/your-org/nba-stats-scraper.git
cd nba-stats-scraper

# 2. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 3. Build local development images
make build-dev

# 4. Start services locally
docker-compose up -d

# 5. Verify everything works
make test-local
```

### 📁 **Environment Setup**
```bash
# .env file (never commit this!)
ODDS_API_KEY=your_odds_api_key_here
BDL_API_KEY=your_ball_dont_lie_key
PROJECT_ID=your-gcp-project-dev
GOOGLE_APPLICATION_CREDENTIALS=./service-account-dev.json

# Optional for local development
DATABASE_URL=postgresql://localhost:5432/nba_dev
REDIS_URL=redis://localhost:6379
```

## Local Development

### 🐳 **Docker Compose Setup**
```yaml
# docker-compose.dev.yml
version: '3.8'
services:
  scrapers:
    build:
      context: .
      dockerfile: scrapers/Dockerfile
    ports:
      - "8080:8080"
    volumes:
      - ./scrapers:/app/scrapers
      - ./shared:/app/shared
    environment:
      - DEBUG=true
      - PORT=8080
    command: ["events", "--serve", "--debug"]

  processors:
    build:
      context: .
      dockerfile: processors/Dockerfile
    ports:
      - "8081:8080"
    volumes:
      - ./processors:/app/processors
      - ./shared:/app/shared
    environment:
      - DEBUG=true
      - PORT=8080
    command: ["events", "--serve", "--debug"]

  reportgen:
    build:
      context: .
      dockerfile: reportgen/Dockerfile
    ports:
      - "8082:8080"
    volumes:
      - ./reportgen:/app/reportgen
      - ./shared:/app/shared
    environment:
      - DEBUG=true
      - PORT=8080
    command: ["player-reports", "--serve", "--debug"]

  # Supporting services
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: nba_dev
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

### 🔧 **Development Commands**
```bash
# Start all services
docker-compose -f docker-compose.dev.yml up -d

# Start specific service
docker-compose -f docker-compose.dev.yml up scrapers

# View logs
docker-compose -f docker-compose.dev.yml logs -f scrapers

# Rebuild after code changes
docker-compose -f docker-compose.dev.yml build scrapers

# Run tests
docker-compose -f docker-compose.dev.yml exec scrapers pytest

# Stop all services
docker-compose -f docker-compose.dev.yml down
```

## Working with Individual Services

### 🕷️ **Scraper Development**

#### Running Scrapers Locally
```bash
# Method 1: Direct Python execution
cd scrapers/
python -m oddsapi.oddsa_events_his --sport basketball_nba --date 2024-12-15T00:00:00Z --debug

# Method 2: Container with live code mounting
docker run -v $(pwd):/app -p 8080:8080 nba-scrapers events --serve --debug

# Method 3: Docker Compose
docker-compose -f docker-compose.dev.yml up scrapers
```

#### Testing Scrapers
```bash
# Unit tests
pytest scrapers/tests/

# Integration tests with containers
pytest tests/cloud_run/

# Test specific scraper endpoint
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -d '{"sport": "basketball_nba", "date": "2024-12-15T00:00:00Z", "debug": true}'

# Test health endpoint
curl http://localhost:8080/health
```

#### Adding New Scrapers
```bash
# 1. Create new scraper module
touch scrapers/newsource/new_scraper.py

# 2. Add to docker-entrypoint.sh
# Add new case to the switch statement

# 3. Update requirements.txt if needed
echo "new-dependency==1.0.0" >> scrapers/requirements.txt

# 4. Test locally
docker-compose build scrapers
docker run nba-scrapers new-scraper --serve
```

### ⚙️ **Processor Development**

#### Running Processors Locally
```bash
# Direct execution
cd processors/
python -m events_processor --serve --debug

# With container
docker run -v $(pwd):/app -p 8081:8080 nba-processors events --serve --debug

# Test processing pipeline
python -m events_processor --input-file tests/samples/events.json --output-file /tmp/processed.json
```

#### Testing Data Processing
```bash
# Unit tests for processors
pytest processors/tests/

# Test with sample data
docker run -v $(pwd)/tests/samples:/data nba-processors events --input-file /data/events.json

# Test BigQuery integration (needs credentials)
export GOOGLE_APPLICATION_CREDENTIALS=./service-account-dev.json
python -m processors.events_processor --test-bigquery
```

### 📊 **Report Generator Development**

#### Running Report Generation
```bash
# Generate reports locally
cd reportgen/
python -m player_report_generator --player-id 123 --output-dir /tmp/reports

# With container
docker run -v $(pwd)/reports:/app/reports nba-reportgen player-reports --serve

# Test report templates
python -m reportgen.template_tester --template player_summary.html
```

## Testing Strategy

### 🧪 **Test Pyramid**

#### Unit Tests (Fast, Many)
```bash
# Test individual functions
pytest scrapers/tests/unit/
pytest processors/tests/unit/
pytest reportgen/tests/unit/

# Run with coverage
pytest --cov=scrapers --cov-report=html
```

#### Integration Tests (Medium, Some)
```bash
# Test service interactions
pytest tests/integration/

# Test with real APIs (use test keys)
pytest tests/integration/ --api-tests

# Test database operations
pytest tests/integration/test_database.py
```

#### End-to-End Tests (Slow, Few)
```bash
# Test complete workflows
pytest tests/e2e/

# Test deployed services
pytest tests/cloud_run/ --base-url https://your-service-url.run.app
```

### 🔍 **Testing Tools**
```bash
# Install testing dependencies
pip install pytest pytest-cov pytest-mock httpx

# Test configuration
# pytest.ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = --tb=short --strict-markers
markers = 
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    slow: Slow running tests
```

## Code Quality

### 📏 **Linting and Formatting**
```bash
# Install development tools
pip install black flake8 mypy isort

# Format code
black scrapers/ processors/ reportgen/ shared/

# Sort imports
isort scrapers/ processors/ reportgen/ shared/

# Lint code
flake8 scrapers/ processors/ reportgen/ shared/

# Type checking
mypy scrapers/ processors/ reportgen/
```

### 🔧 **Pre-commit Hooks**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.1
    hooks:
      - id: mypy
        additional_dependencies: [types-requests]
```

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Run on all files
pre-commit run --all-files
```

## Deployment Workflow

### 🚀 **Development to Production Pipeline**

#### 1. Feature Development
```bash
# Create feature branch
git checkout -b feature/new-scraper

# Develop and test locally
docker-compose -f docker-compose.dev.yml up
# Make changes, test, iterate

# Run full test suite
make test-all

# Commit changes
git add .
git commit -m "Add new scraper for XYZ API"
```

#### 2. Pull Request Process
```bash
# Push feature branch
git push origin feature/new-scraper

# Create PR (triggers CI/CD)
# - Automated tests run
# - Build validation
# - Security scanning
# - Code review required
```

#### 3. Staging Deployment
```bash
# After PR approval, merge to develop
git checkout develop
git merge feature/new-scraper

# Deploy to staging (automatic via CI/CD)
# Tests run against staging environment
```

#### 4. Production Deployment
```bash
# Merge develop to main
git checkout main
git merge develop

# Tag release
git tag v1.2.3
git push origin v1.2.3

# Production deployment (automatic via CI/CD)
```

### 🔄 **CI/CD Pipeline** (GitHub Actions Example)
```yaml
# .github/workflows/ci.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r shared/requirements.txt
          pip install -r scrapers/requirements.txt
          pip install -r processors/requirements.txt
          
      - name: Run tests
        run: |
          pytest tests/unit/
          pytest tests/integration/
          
      - name: Build containers
        run: |
          docker build -f scrapers/Dockerfile -t test-scrapers .
          docker build -f processors/Dockerfile -t test-processors .

  deploy-staging:
    if: github.ref == 'refs/heads/develop'
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: ./bin/deploy_all_services.sh $PROJECT_ID-staging us-central1 true

  deploy-production:
    if: github.ref == 'refs/heads/main'
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: ./bin/deploy_all_services.sh $PROJECT_ID us-central1 true
```

## Debugging

### 🐛 **Local Debugging**
```bash
# Debug with VS Code
# 1. Set breakpoints in code
# 2. Use debugpy in container
docker run -p 5678:5678 -v $(pwd):/app nba-scrapers events --debug --debugpy

# Debug with logs
docker-compose logs -f scrapers | grep ERROR

# Debug with shell access
docker-compose exec scrapers bash
```

### 🔍 **Production Debugging**
```bash
# View Cloud Run logs
gcloud logs read "resource.type=cloud_run_revision" --limit=100

# Debug specific service
gcloud logs read "resource.labels.service_name=nba-scraper-events" --limit=50

# Real-time log streaming
gcloud logs tail "resource.type=cloud_run_revision"

# Debug container locally with production image
docker run -it gcr.io/YOUR_PROJECT/nba-scrapers:latest bash
```

## Performance Optimization

### ⚡ **Local Performance Testing**
```bash
# Load test scrapers
hey -n 100 -c 10 http://localhost:8080/health

# Profile Python code
python -m cProfile -o profile.stats scrapers/oddsapi/oddsa_events_his.py
python -c "import pstats; pstats.Stats('profile.stats').sort_stats('cumulative').print_stats(10)"

# Memory profiling
pip install memory-profiler
python -m memory_profiler scrapers/oddsapi/oddsa_events_his.py
```

### 📊 **Production Monitoring**
```bash
# View metrics
gcloud monitoring metrics list --filter="resource.type=cloud_run_revision"

# Custom metrics query
gcloud monitoring metrics-descriptors list --filter="metric.type=custom.googleapis.com/nba/*"
```

## Makefile Commands

### 🛠️ **Development Makefile**
```makefile
# Makefile
.PHONY: help build test deploy clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

build:  ## Build all development images
	docker-compose -f docker-compose.dev.yml build

build-prod:  ## Build production images
	gcloud builds submit --config docker/cloudbuild.yaml .

test:  ## Run all tests
	pytest tests/

test-unit:  ## Run unit tests only
	pytest tests/unit/

test-integration:  ## Run integration tests
	pytest tests/integration/

test-e2e:  ## Run end-to-end tests
	pytest tests/e2e/

lint:  ## Run linting
	black --check .
	flake8 .
	isort --check-only .

format:  ## Format code
	black .
	isort .

up:  ## Start development environment
	docker-compose -f docker-compose.dev.yml up -d

down:  ## Stop development environment
	docker-compose -f docker-compose.dev.yml down

logs:  ## View logs
	docker-compose -f docker-compose.dev.yml logs -f

clean:  ## Clean up containers and images
	docker-compose -f docker-compose.dev.yml down -v
	docker system prune -f

deploy-dev:  ## Deploy to development
	./bin/deploy_all_services.sh $(PROJECT_ID)-dev us-central1 true

deploy-staging:  ## Deploy to staging
	./bin/deploy_all_services.sh $(PROJECT_ID)-staging us-central1 true

deploy-prod:  ## Deploy to production
	./bin/deploy_all_services.sh $(PROJECT_ID) us-central1 true
```

---

**Quick Reference:**
- `make up` - Start local development
- `make test` - Run all tests
- `make lint` - Check code quality
- `make deploy-dev` - Deploy to development
- `docker-compose logs -f scrapers` - View scraper logs
- `make clean` - Clean up containers

