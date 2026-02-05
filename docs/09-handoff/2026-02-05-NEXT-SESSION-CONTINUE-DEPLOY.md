# Continue Session 131 - Breakout Classifier Deployment

## Quick Context

Session 131 fixed the breakout classifier shadow mode. The model was not being loaded because it wasn't in the Docker image. We:
1. Uploaded models to GCS with proper naming (`breakout_v1_{start}_{end}.cbm`)
2. Added `BREAKOUT_CLASSIFIER_MODEL_PATH` env var
3. Updated code to load from GCS

**Deployment is in progress but slow.** Continue from here.

## P0: Complete Deployment

The prediction-worker deployment was started but is slow. Options:

### Option 1: Check if deployment completed
```bash
./bin/whats-deployed.sh

# Expected commit: 8886339c (or newer)
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
```

### Option 2: If stuck, restart deployment
```bash
# Kill old deployment if still running
ps aux | grep deploy-service | grep -v grep | awk '{print $2}' | xargs kill

# Deploy fresh
./bin/deploy-service.sh prediction-worker
```

### Option 3: Skip build (if image exists)
```bash
# Check if image exists
gcloud artifacts docker images list us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker --format="table(version)" | head -5

# Deploy existing image directly
gcloud run deploy prediction-worker \
  --region=us-west2 \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:8886339c \
  --quiet
```

## P1: Verify Shadow Mode Working

After deployment:

1. Check logs:
```bash
gcloud run services logs read prediction-worker --region=us-west2 --limit=30 | grep -i "breakout"
```

2. Should see model loading from GCS (not "model not found")

3. After next prediction run (~2:30 AM ET), verify shadow data:
```sql
SELECT game_date, COUNT(*) as total,
  COUNTIF(JSON_VALUE(features_snapshot, '$.breakout_shadow.risk_score') IS NOT NULL) as with_shadow
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-05'
GROUP BY game_date;
```

## P2: Speed Up Deployments (Investigation)

The deploy script does:
1. Docker build (slow - downloads all dependencies)
2. Docker push (slow - large images)
3. Cloud Run deploy

**Ideas to investigate:**
- Use Docker layer caching
- Pre-build and cache base images
- Use smaller base images
- Skip dependency reinstall when only code changes

## Key Files

- Handoff: `docs/09-handoff/2026-02-05-SESSION-131-BREAKOUT-SHADOW-HANDOFF.md`
- Classifier: `predictions/worker/prediction_systems/breakout_classifier_v1.py`
- Models in GCS: `gs://nba-props-platform-models/breakout/v1/`

## Commits This Session

| Commit | Description |
|--------|-------------|
| `2f8cc6ff` | fix: Include breakout classifier model in worker Docker image |
| `8886339c` | feat: Update breakout classifier naming and GCS model loading |
| `f3958c94` | docs: Add Session 131 handoff |
