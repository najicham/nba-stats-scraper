# Session 107 Handoff - 2026-02-03

## Session Summary

Fixed critical prediction-worker health check failure by adding missing environment variable `GCP_PROJECT_ID`. The worker was crashing at startup, causing `/health/deep` to return 503.

## Critical Fix Applied

| Fix | Status | Details |
|-----|--------|---------|
| Added GCP_PROJECT_ID env var | ✅ Deployed | Worker now boots correctly |
| Health check now returns 200 | ✅ Verified | All 4 checks passing |
| Uptime checks show 200s | ✅ Verified | Since 23:56 UTC |

### Root Cause

Session 106's deployment set CATBOOST_V8_MODEL_PATH but didn't include other required env vars. Worker crashes when GCP_PROJECT_ID is missing (required by env_validation.py).

### Fix Applied

```bash
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform,CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm,PUBSUB_READY_TOPIC=prediction-ready-prod,BUILD_COMMIT=14395e15,BUILD_TIMESTAMP=2026-02-03T23:36:01Z"
```

## Current State

### Deployment Status

| Service | Commit | Revision | Health |
|---------|--------|----------|--------|
| prediction-worker | 14395e15 | 00106-4qz | ✅ 200 OK |
| prediction-coordinator | 5357001e | 00134 | ✅ Healthy |

### Worker Environment Variables

```yaml
- GCP_PROJECT_ID: nba-props-platform ✅ (was missing!)
- CATBOOST_V8_MODEL_PATH: gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm ✅
- CATBOOST_V9_MODEL_PATH: gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm ✅
- PUBSUB_READY_TOPIC: prediction-ready-prod ✅
- BUILD_COMMIT: 14395e15 ✅
- BUILD_TIMESTAMP: 2026-02-03T23:36:01Z ✅
- SENTRY_DSN: (from secret) ✅
```

### Health Check Results

```json
{
  "status": "healthy",
  "checks_passed": 4,
  "checks_failed": 0,
  "checks": [
    {"check": "model_loading", "status": "pass"},
    {"check": "configuration", "status": "pass"},
    {"check": "gcs_access", "status": "pass"},
    {"check": "bigquery_access", "status": "pass"}
  ]
}
```

### Uptime Check Status

| Check | Auth | Status | Notes |
|-------|------|--------|-------|
| prediction-worker-health | OIDC_TOKEN | ✅ 200 | New check, working correctly |
| nba-prediction-worker-deep-health-prod | None | ❌ 403 | **Needs manual deletion** |

## Feb 3 Predictions

| System | Predictions | % OVER | Signal |
|--------|-------------|--------|--------|
| catboost_v9 | 84 | 33.3% | YELLOW |
| catboost_v9_2026_02 | 74 | 40.5% | GREEN |
| catboost_v8 | 82 | 48.8% | GREEN |

Games: 10 scheduled (all at 7-10 PM ET)

## Remaining Tasks

### P1: Delete Old Uptime Check (Manual)

The old uptime check lacks auth and causes 403s:

1. Go to: https://console.cloud.google.com/monitoring/uptime
2. Find: "nba-prediction-worker-deep-health-prod"
3. Delete it

**Why manual:** `gcloud monitoring uptime delete` command returns INVALID_ARGUMENT error.

### P2: Monitor Feb 3 Hit Rates (After ~11 PM PT)

```sql
-- Overall hit rate by system
SELECT
  system_id,
  COUNT(*) as bets,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v9_2026_02')
  AND game_date = '2026-02-03'
  AND recommendation IN ('OVER', 'UNDER')
  AND prediction_correct IS NOT NULL
GROUP BY 1;
```

```sql
-- Hit rate by edge tier (CatBoost V9)
SELECT
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High (5+)'
    WHEN ABS(predicted_points - line_value) >= 3 THEN 'Medium (3-5)'
    ELSE 'Low (<3)'
  END as tier,
  COUNT(*) as bets,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = '2026-02-03'
  AND recommendation IN ('OVER', 'UNDER')
  AND prediction_correct IS NOT NULL
GROUP BY tier
ORDER BY tier;
```

## Key Learnings

1. **Env var drift is still happening** - Session 81 added env var preservation to deploy script, but Session 106 bypassed it
2. **Always check health endpoints after deployment** - Would have caught this immediately
3. **Model file confusion** - Session 81 referenced `catboost_v8_33features_20260201.cbm` but that file was never uploaded
4. **Uptime checks need auth** - Old check without OIDC auth causes constant 403s

## Prevention Mechanisms

### Always Run After Deployment

```bash
# 1. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 2. Test health endpoint
curl -s https://prediction-worker-*.run.app/health/deep \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.status'

# 3. Check for errors in logs
gcloud logging read 'resource.labels.service_name="prediction-worker" AND severity>=ERROR' \
  --limit=10 --freshness=5m
```

## Verification Commands

### Health Check
```bash
# Should return 200 with status: "healthy"
curl -s "https://prediction-worker-756957797294.us-west2.run.app/health/deep" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Uptime Check Logs
```bash
# Should see only 200s after fix
gcloud logging read 'resource.labels.service_name="prediction-worker" AND httpRequest.requestUrl:"/health/deep" AND httpRequest.userAgent:"GoogleStackdriverMonitoring"' \
  --limit=5 --freshness=15m --format='table(timestamp,httpRequest.status)'
```

### Environment Variables
```bash
gcloud run services describe prediction-worker --region=us-west2 \
  --format='yaml(spec.template.spec.containers[0].env)' | grep -E "name:|value:"
```

## Next Session Checklist

1. [ ] **Delete old uptime check** - Via console (gcloud command fails)
2. [ ] **Monitor Feb 3 hit rates** - After games complete (~11 PM PT)
3. [ ] **Verify edge filter working** - After next prediction run (Feb 4 AM)
4. [ ] **Check for recurring env var drift** - Why did Session 106 not preserve env vars?

---

**End of Session 107** - 2026-02-03 ~4:00 PM PT
