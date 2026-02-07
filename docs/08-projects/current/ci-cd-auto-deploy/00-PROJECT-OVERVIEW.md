# CI/CD Auto-Deploy (Session 147)

## Problem

Deployment drift was the #1 recurring issue across 140+ sessions. Code was committed but not deployed because:
1. **WSL2 TLS timeouts** -- `docker push` to Artifact Registry failed ~30% of the time
2. **Manual process** -- Developers had to remember to deploy after each commit
3. **No automated verification** -- Drift detection ran every 6 hours but didn't fix anything

## Solution

### Cloud Build Triggers (Primary - Session 147)

Six Cloud Build triggers connected directly to GitHub via 2nd-gen connection. Each trigger:
- Watches specific service paths + `shared/` for changes on `main`
- Clones repo directly from GitHub (no WSL2 network issues)
- Builds with the correct Dockerfile using `cloudbuild.yaml`
- Deploys with `--update-env-vars` (preserves existing config)
- Labels with commit SHA for drift detection

| Trigger | Service | Path Filters |
|---------|---------|-------------|
| `deploy-nba-scrapers` | nba-scrapers | `scrapers/**`, `shared/**` |
| `deploy-nba-phase2-raw-processors` | nba-phase2-raw-processors | `data_processors/raw/**`, `shared/**` |
| `deploy-nba-phase3-analytics-processors` | nba-phase3-analytics-processors | `data_processors/analytics/**`, `shared/**` |
| `deploy-nba-phase4-precompute-processors` | nba-phase4-precompute-processors | `data_processors/precompute/**`, `shared/**` |
| `deploy-prediction-coordinator` | prediction-coordinator | `predictions/coordinator/**`, `predictions/shared/**`, `shared/**` |
| `deploy-prediction-worker` | prediction-worker | `predictions/worker/**`, `predictions/shared/**`, `shared/**` |

### GitHub Actions (Fallback - Session 147)

`.github/workflows/auto-deploy.yml` provides a fallback with:
- Manual dispatch with service picker dropdown
- "Deploy all" option
- Same change detection logic
- Uses `cloudbuild.yaml` via `gcloud builds submit`

### Local Deploy (Emergency)

`bin/hot-deploy.sh` and `bin/deploy-service.sh` still work for:
- Debugging build issues locally
- Deploying when GitHub/Cloud Build is down
- Testing Dockerfile changes before pushing

## Architecture

```
Push to main (GitHub)
    |
    v
Cloud Build Trigger (watches paths)
    |
    v
Cloud Build (clones repo, builds Docker image)
    |
    v
Cloud Run Deploy (--update-env-vars, --update-labels)
    |
    v
Health check + drift detection (existing monitoring)
```

## Infrastructure Setup

### GitHub Connection (2nd Gen)
- **Connection:** `nba-github-connection` (us-west2)
- **Repository:** `projects/nba-props-platform/locations/us-west2/connections/nba-github-connection/repositories/nba-stats-scraper`
- **GitHub App Installation:** `108550949` (installed on all repos for `najicham`)

### IAM Permissions

**Trigger service account** (user-managed, required for 2nd gen triggers):
- SA: `github-actions-deploy@nba-props-platform.iam.gserviceaccount.com`
- Roles: `cloudbuild.builds.builder`, `iam.serviceAccountUser`, `run.admin`, `storage.admin`, `logging.logWriter`
- **Note:** 2nd gen triggers require a user-managed SA, not the default `PROJECT_NUMBER@cloudbuild.gserviceaccount.com`

**Cloud Build P4SA** (Google-managed, for GitHub connection):
- SA: `service-756957797294@gcp-sa-cloudbuild.iam.gserviceaccount.com`
- Role: `secretmanager.admin` (stores GitHub OAuth token)

### Shared Config
- `cloudbuild.yaml` -- Generic build config supporting all services via substitution variables
- Substitutions: `_SERVICE`, `_DOCKERFILE`, `_BUILD_TIMESTAMP`, `SHORT_SHA` (auto-populated)

## Operations

### Monitor Triggers
```bash
# List all triggers
gcloud builds triggers list --region=us-west2 --project=nba-props-platform

# Check recent builds
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=10

# View specific build logs
gcloud builds log BUILD_ID --region=us-west2 --project=nba-props-platform
```

### Manually Run a Trigger
```bash
# Via Cloud Build
gcloud builds triggers run deploy-prediction-coordinator \
  --branch=main \
  --region=us-west2 \
  --project=nba-props-platform

# Via GitHub Actions
gh workflow run "CD - Auto Deploy on Main" -f service=prediction-coordinator
```

### Disable/Enable Triggers
```bash
# Disable (e.g., during maintenance)
gcloud builds triggers update deploy-prediction-coordinator \
  --disabled \
  --region=us-west2 \
  --project=nba-props-platform

# Re-enable
gcloud builds triggers update deploy-prediction-coordinator \
  --no-disabled \
  --region=us-west2 \
  --project=nba-props-platform
```

## Previous Approaches (Deprecated)

| Approach | Issue | Status |
|----------|-------|--------|
| Manual `deploy-service.sh` | Forgotten after sessions | Still works as fallback |
| Manual `hot-deploy.sh` | WSL2 TLS timeouts ~30% | Still works as fallback |
| `cloud-deploy.sh` (Session 146) | WSL2 source upload also stalled | Superseded by triggers |
| GitHub Actions auto-deploy (Session 147 early) | Extra hop (GH runner -> Cloud Build) | Kept as fallback |

## Files

| File | Purpose |
|------|---------|
| `cloudbuild.yaml` | Generic Cloud Build config (all services) |
| `.github/workflows/auto-deploy.yml` | GitHub Actions fallback auto-deploy |
| `.github/workflows/deploy-service.yml` | Reusable workflow for single service deploy |
| `bin/deploy-service.sh` | Local standard deploy (full validation) |
| `bin/hot-deploy.sh` | Local hot-deploy (quick) |
| `bin/cloud-deploy.sh` | Local Cloud Build deploy (deprecated) |

## What's Next

- Monitor trigger reliability over the next few days
- Consider adding Slack notifications for build failures
- Consider adding build caching to speed up Docker builds
- Potentially consolidate deployment-drift-detection.yml (less critical now that auto-deploy exists)
