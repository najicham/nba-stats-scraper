# NBA Prediction Worker Deployment Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Owner**: NBA Prediction Infrastructure Team

---

## Overview

The Prediction Worker is the MOST CRITICAL service in the NBA prediction pipeline. It generates player prop predictions using the ML model (CatBoost V9) and writes them to BigQuery. Downtime directly impacts user-facing predictions.

**Service**: `prediction-worker`
**Region**: `us-west2`
**Repository**: `nba-stats-scraper`
**Dockerfile**: `predictions/worker/Dockerfile`

---

## Pre-Deployment Checklist

**CRITICAL**: Complete ALL checks before deployment:

- [ ] Code changes reviewed and approved
- [ ] All tests passing: `pytest tests/predictions/worker/ -v`
- [ ] Model version confirmed: Check `CATBOOST_VERSION` env var
- [ ] Feature schema compatibility verified
- [ ] Local is synced with remote: `git fetch && git status`
- [ ] Service currently healthy: Check `/health` endpoint
- [ ] Recent predictions verified: Last 2 hours should have data
- [ ] Rollback plan documented (see below)

---

## Deployment Process

### Step 1: Verify Current State

```bash
# Check current deployment
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha,status.url)"

# Check recent predictions
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as recent_predictions
   FROM nba_predictions.player_prop_predictions
   WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)"

# Check for recent errors
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="prediction-worker"
   AND severity>=ERROR' \
  --limit=10 --format="value(timestamp,textPayload)"
```

**Expected**:
- Current commit should match latest main
- Recent predictions > 0 (if games scheduled)
- No critical errors in logs

### Step 2: Deploy Using Automated Script

```bash
# From repository root
./bin/deploy-service.sh prediction-worker
```

**What the script does**:
1. Builds Docker image from repo root (ensures `shared/` modules available)
2. Tags with commit hash for traceability
3. Pushes to Container Registry
4. Deploys to Cloud Run with build metadata
5. Verifies service identity via `/health` endpoint
6. Checks heartbeat code (prevents Firestore proliferation)
7. **Post-deployment validation**:
   - Verifies recent predictions count
   - Checks for errors in last 10 minutes

**Deployment takes**: ~5-7 minutes

### Step 3: Post-Deployment Verification

The deploy script automatically runs these checks, but verify manually:

```bash
# 1. Check service is responding
SERVICE_URL=$(gcloud run services describe prediction-worker --region=us-west2 --format="value(status.url)")
curl -s $SERVICE_URL/health | jq '.'

# Expected response:
# {
#   "service": "prediction-worker",
#   "status": "healthy",
#   "build_commit": "abc1234",
#   "model_version": "v9"
# }

# 2. Verify model version
curl -s $SERVICE_URL/health | jq -r '.model_version'
# Should be: v9 (or v8 if intentional rollback)

# 3. Check predictions are being generated
# Wait 10 minutes, then:
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as new_predictions, MIN(created_at) as first_prediction
   FROM nba_predictions.player_prop_predictions
   WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)"

# Expected: If games scheduled, should see predictions

# 4. Check error rate
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="prediction-worker"
   AND severity>=ERROR
   AND timestamp>="'$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=20 --format="value(severity)"

# Expected: 0 errors
```

### Step 4: Validate Prediction Quality

```bash
# Check prediction quality (next day after grading)
bq query --use_legacy_sql=false \
  "SELECT
     COUNT(*) as predictions,
     ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v9'
     AND game_date = CURRENT_DATE() - 1
     AND confidence_score >= 0.92
     AND ABS(predicted_points - line_value) >= 3"

# Expected hit rate: 55-58% (Premium picks)
```

---

## Common Issues & Troubleshooting

### Issue 1: Service Identity Mismatch

**Symptom**: Deploy script reports "SERVICE IDENTITY MISMATCH"

**Cause**: Wrong code deployed (Dockerfile CMD points to wrong module)

**Fix**:
1. Check Dockerfile: `cat predictions/worker/Dockerfile | grep CMD`
2. Should be: `CMD ["python", "-m", "predictions.worker.main"]`
3. If wrong, fix Dockerfile and redeploy
4. If correct, check build cache: rebuild with `--no-cache`

### Issue 2: No Predictions Generated

**Symptom**: Predictions count = 0 after deployment

**Cause**: Multiple possible causes:
- No games scheduled today
- Feature store missing data
- Model loading failed

**Diagnosis**:
```bash
# Check if games scheduled
bq query --use_legacy_sql=false \
  "SELECT game_id, home_team_tricode, away_team_tricode
   FROM nba_reference.nba_schedule
   WHERE game_date = CURRENT_DATE()"

# Check feature store
bq query --use_legacy_sql=false \
  "SELECT COUNT(DISTINCT player_lookup) as players_with_features
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date = CURRENT_DATE()"

# Check logs for model loading errors
gcloud logging read \
  'resource.labels.service_name="prediction-worker"
   AND textPayload=~"model"' \
  --limit=20
```

**Fix**: See issue-specific fixes in logs

### Issue 3: High Error Rate

**Symptom**: Many ERROR logs after deployment

**Cause**: Code bug, schema mismatch, or dependency issue

**Fix**: Rollback immediately (see below), then investigate

### Issue 4: Feature Validation Errors

**Symptom**: Logs show "Feature validation failed" or "fatigue_score outside range"

**Cause**: Feature schema changed or validation too strict

**Fix**:
1. Check validation rules in `predictions/worker/data_loaders.py`
2. If sentinel values (-1) are expected, update validation
3. If real data issue, check feature store quality

---

## Rollback Procedure

**When to rollback**:
- Error rate >5% after deployment
- Predictions quality degraded significantly
- Critical functionality broken

**How to rollback**:

```bash
# 1. List recent revisions
gcloud run revisions list --service=prediction-worker --region=us-west2 --limit=5

# 2. Identify previous healthy revision (not the latest)
# Format: prediction-worker-00123-abc

# 3. Route 100% traffic to previous revision
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --to-revisions=prediction-worker-00122-xyz=100

# 4. Verify rollback successful
curl -s $(gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(status.url)")/health | jq '.'

# 5. Check predictions are working
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)"
```

**Post-rollback**:
- Document why rollback was needed
- Fix issue in code
- Test thoroughly before redeploying

---

## Canary Deployment (Optional for Risky Changes)

For high-risk changes (model updates, major refactors):

```bash
# 1. Deploy normally (creates new revision)
./bin/deploy-service.sh prediction-worker

# 2. Get new revision name
NEW_REVISION=$(gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(status.latestReadyRevisionName)")

# 3. Get previous revision name
OLD_REVISION=$(gcloud run revisions list --service=prediction-worker --region=us-west2 \
  --format="value(metadata.name)" --limit=2 | tail -1)

# 4. Split traffic 10% new / 90% old
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --to-revisions=$NEW_REVISION=10,$OLD_REVISION=90

# 5. Monitor for 15-30 minutes
gcloud logging read \
  'resource.labels.service_name="prediction-worker"
   AND resource.labels.revision_name="'$NEW_REVISION'"
   AND severity>=ERROR' \
  --limit=50

# 6a. If healthy, promote to 100%
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --to-latest

# 6b. If errors, rollback to 100% old
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --to-revisions=$OLD_REVISION=100
```

---

## Monitoring After Deployment

**First 24 hours** after deployment, monitor:

1. **Prediction volume**: Should match typical daily patterns
2. **Error rate**: Should be <1%
3. **Latency**: p95 should be <30s per prediction
4. **Hit rate**: Check next day after grading (55-58% for premium picks)

**Commands**:

```bash
# Run daily validation (includes prediction checks)
/validate-daily

# Check unified health (automated, runs every 6 hours)
gcloud scheduler jobs describe trigger-health-check --location=us-west2

# Manual health check
./bin/monitoring/unified-health-check.sh --verbose
```

---

## Environment Variables

Critical env vars for prediction-worker:

| Variable | Value | Purpose |
|----------|-------|---------|
| `GCP_PROJECT_ID` | `nba-props-platform` | GCP project |
| `BUILD_COMMIT` | Git commit hash | Deployment tracking |
| `BUILD_TIMESTAMP` | ISO timestamp | Deployment tracking |
| `CATBOOST_VERSION` | `v9` (or `v8`) | Model version control |

**To update model version**:

```bash
# Deploy with V8 model (rollback)
CATBOOST_VERSION=v8 ./bin/deploy-service.sh prediction-worker

# Deploy with V9 model (current)
CATBOOST_VERSION=v9 ./bin/deploy-service.sh prediction-worker
```

---

## Service Dependencies

Prediction worker depends on:

| Dependency | Purpose | Impact if Down |
|------------|---------|----------------|
| BigQuery `ml_feature_store_v2` | Feature data | No predictions generated |
| BigQuery `player_prop_predictions` | Write predictions | Predictions lost |
| BigQuery `bettingpros_player_points_props` | Vegas lines | Only NO_PROP_LINE predictions |
| Cloud Storage (model files) | Load CatBoost model | Service fails to start |

---

## Success Criteria

Deployment is successful when:

- ✅ Service responds to `/health` with correct identity
- ✅ Build commit matches expected commit
- ✅ Model version is correct
- ✅ No errors in logs (10 min window)
- ✅ Predictions generated for scheduled games (within 2 hours)
- ✅ Hit rate maintained at 55-58% (check next day)

---

## Related Runbooks

- [Deployment: Prediction Coordinator](./deployment-prediction-coordinator.md)
- [Deployment: Phase 4 Precompute Processors](./deployment-phase4-processors.md)
- [Troubleshooting: Prediction Pipeline Issues](../../DEPLOYMENT-TROUBLESHOOTING.md)

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-02 | 1.0 | Initial runbook | Claude + Session 79 |
