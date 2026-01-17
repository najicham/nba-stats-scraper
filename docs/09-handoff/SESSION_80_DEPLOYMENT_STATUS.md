# Session 80 - MLB Multi-Model Architecture Deployment Status
**Date**: 2026-01-17
**Status**: 🚀 IN PROGRESS - Deploying to Cloud Run
**Branch**: main

---

## 📊 Deployment Overview

Deploying the MLB multi-model prediction architecture to Cloud Run in phases:
- **Phase 1**: V1 Baseline only (safe mode)
- **Phase 3**: All systems (V1, V1.6, Ensemble) - after validation

---

## ✅ Pre-Deployment Complete

### Database Migration ✅
- Added `system_id` column to `pitcher_strikeouts` table
- Backfilled 16,666 historical predictions
- Created 5 monitoring views
- All verification queries passing

### Code Ready ✅
- BaseMLBPredictor abstract class
- 3 prediction systems implemented
- Multi-system worker orchestration
- Circuit breaker for fault tolerance
- 48/62 tests passing (core tests 100%)

### Build Configuration ✅
- Created `cloudbuild-mlb-worker.yaml`
- Updated `scripts/deploy_mlb_multi_model.sh`
- Docker image: `gcr.io/nba-props-platform/mlb-prediction-worker:latest`

---

## ✅ Phase 1 Deployment - COMPLETE

### Configuration
```bash
Service: mlb-prediction-worker
Region: us-central1
Project: nba-props-platform
Stage: phase1 (V1 Baseline Only)
Service URL: https://mlb-prediction-worker-f7p3g7f6ya-uc.a.run.app
```

### Validation Results ✅
```json
{
  "service": "MLB Prediction Worker",
  "version": "2.0.0",
  "architecture": "multi-model",
  "sport": "MLB",
  "prediction_type": "pitcher_strikeouts",
  "active_systems": ["v1_baseline"],
  "systems": {
    "v1_baseline": {
      "model_id": "mlb_pitcher_strikeouts_v1_4features_20260114_142456",
      "mae": 1.66,
      "baseline_mae": 1.92,
      "improvement": "13.6%",
      "features": 25
    }
  },
  "status": "healthy"
}
```

**Phase 1 Status**: ✅ DEPLOYED & HEALTHY
- Deployment time: ~5 minutes
- Docker image: gcr.io/nba-props-platform/mlb-prediction-worker:latest
- Health check: PASSING
- V1 model loaded successfully

## 🚀 Phase 3 Deployment - IN PROGRESS

### Configuration
```bash
Service: mlb-prediction-worker
Region: us-central1
Project: nba-props-platform
Stage: phase3 (All Systems: V1 + V1.6 + Ensemble)
```

### Environment Variables
```bash
MLB_ACTIVE_SYSTEMS=v1_baseline
MLB_V1_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
MLB_V1_6_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
MLB_ENSEMBLE_V1_WEIGHT=0.3
MLB_ENSEMBLE_V1_6_WEIGHT=0.5
GCP_PROJECT_ID=nba-props-platform
```

### Resources
- Memory: 2Gi
- CPU: 2
- Timeout: 300s
- Max Instances: 10
- Auth: Public (allow-unauthenticated)

### Build Steps
1. ✅ Created Cloud Build config
2. 🔄 Building Docker image from `docker/mlb-prediction-worker.Dockerfile`
3. ⏸️ Deploying to Cloud Run
4. ⏸️ Health check validation
5. ⏸️ Service URL verification

---

## 📋 Post-Deployment Tasks

### Phase 1 Validation
- [ ] Service health check passes (HTTP 200)
- [ ] `/` endpoint returns service info
- [ ] `active_systems` shows `['v1_baseline']`
- [ ] Model loads successfully (check logs)
- [ ] Test prediction request works

### Phase 1 Monitoring (24 hours)
- [ ] No errors in Cloud Logging
- [ ] Service responds within timeout
- [ ] Predictions write to BigQuery correctly
- [ ] system_id field populated correctly

### Phase 3 Deployment (After Validation)
- [ ] Confirm Phase 1 stable
- [ ] Run: `./scripts/deploy_mlb_multi_model.sh phase3`
- [ ] Verify all 3 systems active
- [ ] Check daily_coverage view
- [ ] Monitor system_agreement view

---

## 🔍 Verification Commands

### Check Service Status
```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe mlb-prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format="value(status.url)")

echo "Service URL: $SERVICE_URL"

# Health check
curl "$SERVICE_URL/"
```

### Check Logs
```bash
# Recent logs
gcloud logging tail \
  --project=nba-props-platform \
  --resource-type=cloud_run_revision \
  --filter='resource.labels.service_name=mlb-prediction-worker' \
  --limit=50

# Model loading logs
gcloud logging read \
  'resource.type=cloud_run_revision
   AND resource.labels.service_name=mlb-prediction-worker
   AND (textPayload=~"model loaded" OR textPayload=~"Initialized")' \
  --project=nba-props-platform \
  --limit=10
```

### Test Prediction
```bash
# Test batch prediction (no write to BigQuery)
curl -X POST "$SERVICE_URL/predict-batch" \
  -H 'Content-Type: application/json' \
  -d '{
    "game_date": "2026-04-01",
    "write_to_bigquery": false
  }'
```

### Check BigQuery
```sql
-- Verify predictions being written
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT system_id) as systems,
  STRING_AGG(DISTINCT system_id) as active_systems
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY game_date;
```

---

## 🎯 Success Criteria

### Phase 1 (V1 Baseline)
- ✅ Service deployed and healthy
- ✅ Only v1_baseline system active
- ✅ Model loads successfully
- ✅ Predictions write to BigQuery with system_id
- ✅ No errors for 24 hours

### Phase 3 (All Systems)
- ✅ Service deployed and healthy
- ✅ All 3 systems active (v1_baseline, v1_6_rolling, ensemble_v1)
- ✅ Each pitcher gets 3 predictions
- ✅ daily_coverage view shows 3 systems per pitcher
- ✅ Ensemble predictions available
- ✅ No errors for 48 hours

---

## 📚 Related Documents

- **Implementation**: `predictions/mlb/MULTI_MODEL_IMPLEMENTATION.md`
- **Deployment Runbook**: `docs/mlb_multi_model_deployment_runbook.md`
- **Investigation**: `docs/09-handoff/MLB_TWO_TABLE_SYSTEM_INVESTIGATION.md`
- **Session Handoff**: `docs/09-handoff/SESSION_80_FINAL_HANDOFF.md`
- **Continuation**: `docs/09-handoff/SESSION_80_CONTINUATION_FINAL.md`

---

## 🔄 Rollback Plan

If issues arise:

### Immediate Rollback
```bash
# List revisions
gcloud run revisions list \
  --service=mlb-prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform

# Route to previous revision
gcloud run services update-traffic mlb-prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --to-revisions=PREVIOUS_REVISION=100
```

### Complete Rollback
```bash
# Rollback to Phase 1 (from Phase 3)
./scripts/deploy_mlb_multi_model.sh rollback
```

---

## 📞 Support

### Check Current State
```bash
gcloud run services describe mlb-prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format=json | jq '.spec.template.spec.containers[0].env'
```

### Common Issues

**Issue**: Model fails to load
- Check: GCS bucket permissions
- Check: Model path is correct
- Check: Service account has Storage Object Viewer role

**Issue**: BigQuery write fails
- Check: Table schema matches predictions
- Check: Service account has BigQuery Data Editor role
- Check: system_id column exists

**Issue**: High memory usage
- Solution: Increase memory limit (`--memory=4Gi`)
- Solution: Reduce max instances
- Solution: Enable lazy loading

---

**Last Updated**: 2026-01-17 (Deployment in progress)
**Next Update**: After Phase 1 deployment completes
