# NBA Prediction Coordinator Deployment Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Owner**: NBA Prediction Infrastructure Team

---

## Overview

The Prediction Coordinator orchestrates batch prediction generation across multiple workers. It loads game/player data, sends batch requests to the prediction-worker service, and manages the execution flow. Critical for scheduled prediction runs (2:30 AM, 7 AM, 11:30 AM ET).

**Service**: `prediction-coordinator`
**Region**: `us-west2`
**Repository**: `nba-stats-scraper`
**Dockerfile**: `predictions/coordinator/Dockerfile`

---

## Pre-Deployment Checklist

- [ ] Code changes reviewed and approved
- [ ] Tests passing: `pytest tests/predictions/coordinator/ -v`
- [ ] Scheduler compatibility verified (REAL_LINES_ONLY mode, etc.)
- [ ] BigQuery query optimization reviewed (player_loader.py)
- [ ] Local synced with remote: `git fetch && git status`
- [ ] Current service healthy: Check logs for recent batch executions
- [ ] Rollback plan documented

---

## Deployment Process

### Step 1: Verify Current State

```bash
# Check current deployment
gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(metadata.labels.commit-sha,status.url)"

# Check recent batch executions
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator"
   AND textPayload=~"Batch prediction" OR textPayload=~"Starting prediction"' \
  --limit=10 --format="value(timestamp,textPayload)"

# Check for recent errors
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator"
   AND severity>=ERROR' \
  --limit=10 --format="value(timestamp,textPayload)"
```

**Expected**:
- Recent batch executions at scheduled times
- No critical errors
- Coordinator responding to /health

### Step 2: Deploy Using Automated Script

```bash
# From repository root
./bin/deploy-service.sh prediction-coordinator
```

**Deployment takes**: ~5-7 minutes

### Step 3: Post-Deployment Verification

```bash
# 1. Check service health
SERVICE_URL=$(gcloud run services describe prediction-coordinator --region=us-west2 --format="value(status.url)")
curl -s $SERVICE_URL/health | jq '.'

# Expected:
# {
#   "service": "prediction-coordinator",
#   "status": "healthy",
#   "build_commit": "abc1234"
# }

# 2. Trigger test batch (optional, only if safe)
curl -X POST $SERVICE_URL/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "force": false, "require_real_lines": true}'

# 3. Monitor batch execution
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator"
   AND timestamp>="'$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=50 --format="value(timestamp,textPayload)"

# 4. Verify predictions created by batch
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as recent_predictions
   FROM nba_predictions.player_prop_predictions
   WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)"
```

---

## Common Issues & Troubleshooting

### Issue 1: Batch Requests Timing Out

**Symptom**: Logs show "Request timeout" when calling prediction-worker

**Cause**:
- Batch size too large
- Worker service slow/overloaded
- Network issues

**Fix**:
```bash
# Check worker service health
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(status.conditions)"

# Check worker logs for slow predictions
gcloud logging read \
  'resource.labels.service_name="prediction-worker"
   AND textPayload=~"prediction took"' \
  --limit=20

# Reduce batch size in coordinator config if needed
# See predictions/coordinator/config.py
```

### Issue 2: No Players Loaded

**Symptom**: Logs show "Loaded 0 players" for scheduled batch

**Cause**:
- No games scheduled for target date
- Feature store missing data
- Query filter too restrictive (REAL_LINES_ONLY mode)

**Diagnosis**:
```bash
# Check games scheduled
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM nba_reference.nba_schedule
   WHERE game_date = CURRENT_DATE()"

# Check feature store
bq query --use_legacy_sql=false \
  "SELECT COUNT(DISTINCT player_lookup)
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date = CURRENT_DATE()"

# Check lines availability (for REAL_LINES_ONLY mode)
bq query --use_legacy_sql=false \
  "SELECT COUNT(DISTINCT player_lookup)
   FROM nba_raw.bettingpros_player_points_props
   WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL"
```

### Issue 3: Duplicate Predictions

**Symptom**: Same player has multiple active predictions

**Cause**: Prediction deactivation bug (Session 78 fix should prevent this)

**Fix**:
```sql
-- Check for duplicates
SELECT player_lookup, game_id, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
GROUP BY player_lookup, game_id
HAVING cnt > 1;

-- If found, verify deactivation logic in batch_staging_writer.py
-- Should partition by (game_id, player_lookup, system_id)
```

---

## Rollback Procedure

```bash
# 1. List recent revisions
gcloud run revisions list --service=prediction-coordinator --region=us-west2 --limit=5

# 2. Route to previous revision
gcloud run services update-traffic prediction-coordinator \
  --region=us-west2 \
  --to-revisions=prediction-coordinator-00122-xyz=100

# 3. Verify rollback
curl -s $(gcloud run services describe prediction-coordinator --region=us-west2 \
  --format="value(status.url)")/health | jq '.'

# 4. Test batch execution
# Wait for next scheduled run or trigger manually
```

---

## Scheduler Integration

Coordinator is invoked by Cloud Scheduler jobs:

| Scheduler Job | Time (ET) | Mode | Purpose |
|---------------|-----------|------|---------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | Early predictions with real lines |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | Comprehensive predictions |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch stragglers |

**Verify schedulers after deployment**:

```bash
# List prediction schedulers
gcloud scheduler jobs list --location=us-west2 | grep predictions

# Check recent executions
gcloud scheduler jobs describe predictions-early --location=us-west2 \
  --format="value(schedule,state,lastAttemptTime)"

# Test scheduler (triggers coordinator)
gcloud scheduler jobs run predictions-early --location=us-west2
```

---

## Service Dependencies

| Dependency | Purpose | Impact if Down |
|------------|---------|----------------|
| `prediction-worker` | Generate predictions | Batch fails completely |
| BigQuery `ml_feature_store_v2` | Player eligibility | No players loaded |
| BigQuery `nba_schedule` | Game data | No games found |
| BigQuery `bettingpros_player_points_props` | Lines (REAL_LINES_ONLY) | Smaller batch size |

---

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `GCP_PROJECT_ID` | `nba-props-platform` | GCP project |
| `BUILD_COMMIT` | Git commit hash | Deployment tracking |
| `PREDICTION_WORKER_URL` | Auto-discovered | Worker service URL |

---

## Success Criteria

Deployment is successful when:

- ✅ Service responds to `/health`
- ✅ No errors in logs (10 min window)
- ✅ Test batch completes successfully (optional)
- ✅ Scheduled batch executes correctly (wait for next run)
- ✅ Predictions generated match expected volume

---

## Related Runbooks

- [Deployment: Prediction Worker](./deployment-prediction-worker.md)
- [Troubleshooting: Prediction Pipeline Issues](../../DEPLOYMENT-TROUBLESHOOTING.md)
- [Early Prediction Timing (Session 74)](../../../08-projects/current/prediction-timing-improvement/)

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-02 | 1.0 | Initial runbook | Claude + Session 79 |
