# Dockerfile Organization

This document explains the Dockerfile organization conventions for the NBA Stats Scraper repository.

## 🎯 Core Principles

1. **Service Dockerfiles stay with service code** (industry standard)
2. **Utility/validator Dockerfiles go in deployment/dockerfiles/{sport}/**
3. **No Dockerfiles at repository root**
4. **All builds happen from repository root** (for access to `shared/` module)

## 📁 Directory Structure

```
nba-stats-scraper/
├── predictions/
│   ├── coordinator/
│   │   └── Dockerfile              # Prediction coordinator service
│   ├── worker/
│   │   └── Dockerfile              # NBA prediction worker service
│   └── mlb/
│       └── Dockerfile              # MLB prediction worker service
├── data_processors/
│   ├── analytics/
│   │   └── Dockerfile              # Analytics processors service
│   ├── precompute/
│   │   └── Dockerfile              # Precompute processors service
│   └── raw/
│       └── Dockerfile              # Raw data processors service
├── scrapers/
│   └── Dockerfile                  # NBA scrapers service
└── deployment/
    └── dockerfiles/
        ├── mlb/                    # MLB utility/validator Dockerfiles
        │   ├── Dockerfile.freshness-checker
        │   ├── Dockerfile.gap-detection
        │   ├── Dockerfile.pitcher-props-validator
        │   ├── Dockerfile.prediction-coverage
        │   ├── Dockerfile.prediction-coverage-validator
        │   ├── Dockerfile.schedule-validator
        │   └── Dockerfile.stall-detector
        └── nba/                    # NBA utility/validator Dockerfiles
            ├── Dockerfile.odds-api-backfill
            └── Dockerfile.odds-api-test
```

## 🏗️ Build Patterns

### Service Dockerfiles

Service Dockerfiles are located with their service code and follow this pattern:

```dockerfile
# predictions/worker/Dockerfile
# NBA Prediction Worker - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f predictions/worker/Dockerfile -t worker .

FROM python:3.11-slim
WORKDIR /app

# Copy shared module from repository root
COPY shared/ ./shared/

# Copy service-specific code
COPY predictions/worker/ ./predictions/worker/

# Set working directory to service location
WORKDIR /app/predictions/worker

# Install dependencies from service requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Run the service
CMD exec gunicorn --bind :${PORT:-8080} worker:app
```

**Key characteristics:**
- Comment header with build instructions
- Build context is repository root (for `shared/` access)
- Uses `-f` flag to specify Dockerfile location
- Sets `PYTHONPATH=/app` for shared module imports
- Working directory changes to service location after copying

### Utility Dockerfiles

Utility Dockerfiles (validators, backfill jobs, monitors) are in `deployment/dockerfiles/{sport}/`:

```dockerfile
# deployment/dockerfiles/mlb/Dockerfile.pitcher-props-validator
# MLB Pitcher Props Validator
# Cloud Run Job for validating MLB prediction coverage

FROM python:3.11-slim
WORKDIR /app

# Copy minimal dependencies
COPY shared/ ./shared/
COPY monitoring/mlb/validators/ ./validators/

# Install dependencies
RUN pip install --no-cache-dir -r validators/requirements.txt

# Set Python path
ENV PYTHONPATH=/app

# Run validator
CMD ["python", "validators/pitcher_props_validator.py"]
```

**Key characteristics:**
- Named with `.Dockerfile.{purpose}` convention
- Build context is still repository root
- Minimal dependency copying (only what's needed)
- Often used for Cloud Run Jobs rather than services

## 🚀 Deployment Patterns

### Using deploy-service.sh

The standard deployment script handles service-specific Dockerfiles:

```bash
./bin/deploy-service.sh prediction-worker
```

This script:
1. Builds from repo root with correct Dockerfile path
2. Tags with commit hash for traceability
3. Sets BUILD_COMMIT and BUILD_TIMESTAMP env vars
4. Deploys to Cloud Run
5. Shows recent logs for verification

### Service-to-Dockerfile Mapping

| Service | Dockerfile |
|---------|------------|
| `prediction-coordinator` | `predictions/coordinator/Dockerfile` |
| `prediction-worker` | `predictions/worker/Dockerfile` |
| `mlb-prediction-worker` | `predictions/mlb/Dockerfile` |
| `nba-phase3-analytics-processors` | `data_processors/analytics/Dockerfile` |
| `nba-phase4-precompute-processors` | `data_processors/precompute/Dockerfile` |
| `nba-phase2-processors` | `data_processors/raw/Dockerfile` |
| `nba-scrapers` | `scrapers/Dockerfile` |

### Manual Deployment

For utility Dockerfiles (validators, jobs):

```bash
# Build from repo root
cd /home/naji/code/nba-stats-scraper

# Build with explicit Dockerfile path
docker build -f deployment/dockerfiles/nba/Dockerfile.odds-api-backfill \
  -t odds-api-backfill .

# Or use gcloud builds
gcloud builds submit --config deployment/dockerfiles/nba/cloudbuild-odds-backfill.yaml
```

## ⚠️ CRITICAL: Repository Root Build Context

**ALL Dockerfiles MUST be built from the repository root.**

This is required because services depend on the `shared/` module:

```bash
# ✅ CORRECT
cd /home/naji/code/nba-stats-scraper
docker build -f predictions/worker/Dockerfile -t worker .

# ❌ WRONG - will fail with "no such file or directory: shared/"
cd predictions/worker
docker build -t worker .
```

The `shared/` module contains utilities used by all services:
- BigQuery clients
- GCS utilities
- Firestore helpers
- Logging configuration
- Email alerting
- Common data models

## 🔍 Finding Dockerfiles

### Service Dockerfiles

Service Dockerfiles are always at `{service_directory}/Dockerfile`:

```bash
# Find all service Dockerfiles
find . -type f -name "Dockerfile" \
  -not -path "./deployment/*" \
  -not -path "./.git/*"
```

### Utility Dockerfiles

Utility Dockerfiles are in `deployment/dockerfiles/` with descriptive names:

```bash
# List all utility Dockerfiles
ls -la deployment/dockerfiles/nba/
ls -la deployment/dockerfiles/mlb/
```

## 📝 Naming Conventions

### Service Dockerfiles
- Name: `Dockerfile` (standard name)
- Location: With service code
- Example: `predictions/worker/Dockerfile`

### Utility Dockerfiles
- Name: `Dockerfile.{purpose-with-dashes}`
- Location: `deployment/dockerfiles/{sport}/`
- Example: `deployment/dockerfiles/mlb/Dockerfile.pitcher-props-validator`

Use dashes (not underscores) in utility Dockerfile names for consistency with Cloud Run naming conventions.

## 🔧 Best Practices

### 1. Build from Repository Root
Always build from repo root, even for service-specific Dockerfiles:
```bash
docker build -f service/Dockerfile -t image .
```

### 2. Set PYTHONPATH
All Dockerfiles should set `PYTHONPATH=/app` for shared imports:
```dockerfile
ENV PYTHONPATH=/app:$PYTHONPATH
```

### 3. Health Checks
Service Dockerfiles should include health checks:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"
```

### 4. Build Metadata
Include build metadata for debugging:
```dockerfile
ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
LABEL build.commit="${BUILD_COMMIT}"
LABEL build.timestamp="${BUILD_TIMESTAMP}"
```

### 5. Multi-stage Builds
For larger services, use multi-stage builds to reduce image size:
```dockerfile
# Build stage
FROM python:3.11 AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH
CMD ["python", "main.py"]
```

## 🚨 Common Mistakes

### ❌ Building from Service Directory
```bash
# WRONG - missing shared/ module
cd predictions/worker
docker build -t worker .
```

### ❌ Hardcoded Paths
```dockerfile
# WRONG - not portable
COPY /home/user/code/shared/ ./shared/
```

### ❌ Missing PYTHONPATH
```dockerfile
# WRONG - imports will fail
# Missing: ENV PYTHONPATH=/app
```

### ❌ Dockerfiles at Repo Root
```bash
# WRONG - violates organization conventions
./Dockerfile
./Dockerfile.some-service
```

## 📚 References

- Main deployment script: `bin/deploy-service.sh`
- Deployment documentation: `docs/02-operations/deployment.md`
- Cloud Run best practices: `docs/05-development/cloud-run.md`
- Project conventions: `CLAUDE.md`

## 🤝 Contributing

When adding a new service:

1. Create service directory structure
2. Add `Dockerfile` in service directory
3. Update `bin/deploy-service.sh` mapping
4. Add health check endpoint
5. Test deployment from repo root
6. Update this README with service mapping

When adding a new utility:

1. Create Dockerfile in `deployment/dockerfiles/{sport}/`
2. Use naming: `Dockerfile.{purpose-with-dashes}`
3. Build from repo root
4. Document in this README
5. Add deployment script in `bin/` if needed
