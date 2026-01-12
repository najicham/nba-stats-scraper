# Prediction Services Deployment Guide

**Created:** January 12, 2026
**Services:** prediction-coordinator, prediction-worker
**Region:** us-west2

---

## Overview

The prediction system has two Cloud Run services:
- **prediction-coordinator**: Orchestrates prediction generation, loads players, publishes work
- **prediction-worker**: Generates predictions using ML models (CatBoost v8)

Both services require access to `shared/` modules, so they must be deployed from the project root.

---

## Deployment Methods

### Method 1: Source Deploy with GOOGLE_ENTRYPOINT (Recommended)

Deploy from project root with explicit entrypoint:

```bash
# Coordinator
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform \
  --set-env-vars="GOOGLE_ENTRYPOINT=gunicorn --config predictions/coordinator/gunicorn_config.py predictions.coordinator.coordinator:app" \
  --allow-unauthenticated

# Worker
gcloud run deploy prediction-worker \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform \
  --set-env-vars="GOOGLE_ENTRYPOINT=gunicorn --bind :8080 --workers 1 --threads 5 --timeout 300 predictions.worker.worker:app" \
  --allow-unauthenticated
```

### Method 2: Pre-built Docker Image

If source deploy fails, use a pre-built image:

```bash
# Build and push
docker build -t gcr.io/nba-props-platform/prediction-coordinator:latest -f predictions/coordinator/Dockerfile .
docker push gcr.io/nba-props-platform/prediction-coordinator:latest

# Deploy
gcloud run deploy prediction-coordinator \
  --image=gcr.io/nba-props-platform/prediction-coordinator:latest \
  --region=us-west2 \
  --platform=managed \
  --allow-unauthenticated
```

---

## Key Files

| File | Purpose |
|------|---------|
| `predictions/coordinator/coordinator.py` | Flask app, `/start` endpoint |
| `predictions/coordinator/player_loader.py` | Loads players, betting lines |
| `predictions/coordinator/gunicorn_config.py` | Gunicorn server config |
| `predictions/worker/worker.py` | Flask app, `/predict` endpoint |
| `predictions/worker/data_loaders.py` | Loads ML features |

---

## Environment Variables

### Coordinator
- `GCP_PROJECT_ID`: nba-props-platform
- `GOOGLE_ENTRYPOINT`: gunicorn command (if using source deploy)

### Worker
- `GCP_PROJECT_ID`: nba-props-platform
- `GOOGLE_ENTRYPOINT`: gunicorn command (if using source deploy)

---

## Verification

After deployment, verify:

```bash
# Check revision
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Check health
curl https://prediction-coordinator-756957797294.us-west2.run.app/health

# Check logs
gcloud run services logs read prediction-coordinator --limit=20 --region=us-west2
```

---

## Troubleshooting

### Build Failed: Missing Entrypoint

**Error:** "provide a main.py or app.py file or set GOOGLE_ENTRYPOINT"

**Solution:** Use `--set-env-vars="GOOGLE_ENTRYPOINT=..."` when deploying

### Import Errors

**Error:** "ModuleNotFoundError: No module named 'shared'"

**Solution:** Deploy from project root (`--source=.`), not subdirectory

### Timeout During Build

Cloud Run source deploy can take 5-10 minutes. If timeout, check Cloud Build logs:

```bash
gcloud builds list --limit=5 --region=us-west2 --project=nba-props-platform
gcloud builds log <BUILD_ID> --region=us-west2
```

---

## Current Production Revisions

Track current revisions here:

| Service | Revision | Deployed | Notes |
|---------|----------|----------|-------|
| prediction-coordinator | 00032-2wj | 2026-01-11 | Gunicorn logging fix |
| prediction-worker | 00030-cxv | 2026-01-11 | CatBoost v8 |

---

## Related Documentation

- [Pipeline Health Assessment](../08-projects/current/pipeline-reliability-improvements/2026-01-12-PIPELINE-HEALTH-ASSESSMENT.md)
- [Phase 5 Architecture](../03-phases/phase5-predictions/architecture/)
- [Coordinator/Worker README](../predictions/coordinator/README.md)
