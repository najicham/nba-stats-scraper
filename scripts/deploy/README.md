# Quick Deploy Scripts

This directory contains simplified deployment scripts for common deployment tasks.

## Available Scripts

### `deploy-analytics.sh`

Quick deployment for Phase 3 Analytics Processor.

```bash
# Deploy current commit
./scripts/deploy/deploy-analytics.sh

# Deploy with custom tag
./scripts/deploy/deploy-analytics.sh v1.2.3
```

**What it does:**
- Pre-flight checks (auth, project, files)
- Deploys to `nba-phase3-analytics-processors`
- Tags with git commit SHA
- Provides verification commands

**Configuration:**
- Memory: 8 GiB
- CPU: 4 vCPUs
- Timeout: 3600s
- Concurrency: 1

---

### `deploy-predictions.sh`

Quick deployment for Phase 5 Prediction Coordinator.

```bash
# Deploy to production
./scripts/deploy/deploy-predictions.sh prod

# Deploy to dev/staging
./scripts/deploy/deploy-predictions.sh dev
```

**What it does:**
- Environment-aware deployment (prod/dev)
- Deploys to `prediction-coordinator` or `prediction-coordinator-dev`
- Confirmation prompt for production
- Provides verification commands

**Configuration (prod):**
- Memory: 2 GiB
- CPU: 2 vCPUs
- Timeout: 1800s
- Concurrency: 8

---

## When to Use These Scripts

**Use quick-deploy scripts when:**
- Deploying routine updates
- You understand what you're deploying
- No special configuration needed

**Use full deployment scripts when:**
- First-time deployment
- Complex configuration changes
- Need pre-deployment tests
- Deploying multiple services

## Full Deployment Scripts

Located in `bin/` directory:

```bash
# Analytics (with smoke tests)
./bin/analytics/deploy/deploy_analytics_processors.sh

# Predictions (with environment selection)
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod

# Prediction Worker
./bin/predictions/deploy/deploy_prediction_worker.sh

# Reference Service
./bin/reference/deploy/deploy_reference_processors.sh
```

## Troubleshooting

### Script can't find Dockerfile

Make sure you're in the project root:
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/deploy/deploy-analytics.sh
```

### Not authenticated

```bash
gcloud auth login
gcloud config set project nba-props-platform
```

### Permission denied

```bash
chmod +x scripts/deploy/*.sh
```

### Deployment fails

1. Check logs:
   ```bash
   gcloud builds list --limit=5
   gcloud builds log <BUILD_ID>
   ```

2. Review full documentation:
   ```bash
   cat docs/02-operations/DEPLOYMENT.md
   ```

## Additional Resources

- **Main Runbook:** `/docs/02-operations/DEPLOYMENT.md`
- **Troubleshooting:** `/docs/02-operations/troubleshooting.md`
- **Architecture:** `/docs/01-system-design/ARCHITECTURE-OVERVIEW.md`

---

**Last Updated:** 2026-01-27
