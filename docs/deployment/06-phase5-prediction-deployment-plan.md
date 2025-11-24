# Phase 5 Predictions - Deployment Plan

**Created:** 2025-11-23
**Status:** Ready to Execute
**Estimated Time:** 3-4 hours (without XGBoost model training)
**Current Phase:** Code Complete, Ready for Cloud Deployment

---

## Overview

Phase 5 brings the prediction engine to production, completing the end-to-end NBA analytics platform. All code is **100% complete** - we're deploying existing, tested code to Cloud Run.

**What Phase 5 Does:**
- Receives player/game requests from Phase 4
- Loads features from `ml_feature_store_v2`
- Runs 5 prediction systems (4 ready + 1 with mock model)
- Produces confidence-weighted predictions
- Writes to BigQuery for consumption

---

## Current Status

### ✅ Complete
- 5 prediction systems implemented and tested
- Coordinator service (fan-out orchestration)
- Worker service (prediction execution)
- Data loaders optimized for batch loading
- Confidence scoring framework
- Dockerfiles created
- Deployment scripts written
- BigQuery schema (`ml_feature_store_v2`) deployed

### ⚠️ Using Mock Model
- **XGBoost V1:** Code complete, using mock model
- **Impact:** XGBoost will return placeholder predictions
- **Training Time:** ~4 hours (can be done later)
- **Other Systems:** Moving Average, Zone Matchup, Similarity, Ensemble all fully functional

### ❌ Not Yet Done
- Cloud Run deployment (coordinator + worker)
- Pub/Sub topics (Phase 4→5 flow)
- Service accounts and IAM setup
- End-to-end testing in production

---

## Architecture

```
Phase 4: Precompute
  └─ ml_feature_store_v2 (BigQuery) ✅ DEPLOYED
      ↓
  Pub/Sub: prediction-request ❌ NOT CREATED
      ↓
┌──────────────────────────────────┐
│ Prediction Coordinator           │
│ (Cloud Run Service)              │ ❌ NOT DEPLOYED
│                                  │
│ - Loads players for game_date    │
│ - Fans out to workers via Pub/Sub│
│ - Tracks completion progress     │
└──────────────────────────────────┘
      ↓ Pub/Sub (450 messages)
┌──────────────────────────────────┐
│ Prediction Worker                │
│ (Cloud Run Service)              │ ❌ NOT DEPLOYED
│                                  │
│ - Loads features from BQ         │
│ - Runs 5 prediction systems:     │
│   • Moving Average ✅            │
│   • Zone Matchup ✅              │
│   • Similarity ✅                │
│   • XGBoost ⚠️ (mock)           │
│   • Ensemble ✅                  │
│ - Writes to BigQuery             │
└──────────────────────────────────┘
      ↓
  BigQuery: player_prop_predictions ✅ SCHEMA READY
```

---

## Deployment Steps

### Step 1: Pre-Deployment Checklist (5 min)

**Verify Prerequisites:**
- [ ] Current project: `nba-props-platform` ✓
- [ ] Region alignment: Use `us-west2` (matches Phase 1-4)
- [ ] Docker installed and running
- [ ] gcloud authenticated
- [ ] Artifact Registry repository exists

**Action:**
```bash
# Verify setup
gcloud config get-value project  # Should be: nba-props-platform
gcloud auth list                  # Verify authenticated

# Check Artifact Registry (should exist from Phase 1-4)
gcloud artifacts repositories describe nba-props \
  --location=us-west2 \
  --project=nba-props-platform 2>/dev/null || \
  gcloud artifacts repositories create nba-props \
    --repository-format=docker \
    --location=us-west2 \
    --project=nba-props-platform
```

---

### Step 2: Create Pub/Sub Topics & Subscriptions (15 min)

**Topics Needed:**
- `prediction-request` - Coordinator publishes player prediction jobs
- `prediction-ready` - Worker publishes completion events

**Create Topics:**
```bash
# Create prediction-request topic
gcloud pubsub topics create prediction-request \
  --project=nba-props-platform

# Create prediction-ready topic
gcloud pubsub topics create prediction-ready \
  --project=nba-props-platform

# Verify
gcloud pubsub topics list --project=nba-props-platform | grep prediction
```

**Subscriptions:**
- Created automatically by deployment scripts
- `prediction-request-sub` → pushes to Worker `/predict`
- `prediction-ready-sub` → pushes to Coordinator `/complete`

---

### Step 3: Create Service Accounts (10 min)

**Accounts Needed:**
- `prediction-worker` - Runs worker service
- `prediction-coordinator` - Runs coordinator service

**Create Accounts:**
```bash
# Create service accounts
gcloud iam service-accounts create prediction-worker \
  --display-name="Phase 5 Prediction Worker" \
  --project=nba-props-platform

gcloud iam service-accounts create prediction-coordinator \
  --display-name="Phase 5 Prediction Coordinator" \
  --project=nba-props-platform

# Grant BigQuery permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

# Grant Pub/Sub permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Grant Cloud Run invoker (for Pub/Sub push)
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

---

### Step 4: Deploy Prediction Worker (60 min)

**Update deployment script for region:**
```bash
# Edit bin/predictions/deploy/deploy_prediction_worker.sh
# Change REGION from "us-central1" to "us-west2"
```

**Deploy:**
```bash
cd /home/naji/code/nba-stats-scraper

# Run deployment script (builds Docker, pushes to registry, deploys to Cloud Run)
./bin/predictions/deploy/deploy_prediction_worker.sh prod

# This will:
# 1. Build Docker image (~5 min)
# 2. Push to Artifact Registry (~3 min)
# 3. Deploy to Cloud Run (~2 min)
# 4. Configure Pub/Sub subscription (~1 min)
# 5. Verify deployment (~1 min)
```

**Expected Output:**
```
[2025-11-23 19:30:00] Checking prerequisites...
[2025-11-23 19:30:01] Prerequisites OK
[2025-11-23 19:30:02] Building Docker image...
... (Docker build logs)
[2025-11-23 19:35:15] Pushing Docker image to Artifact Registry...
[2025-11-23 19:38:22] Image pushed: us-west2-docker.pkg.dev/nba-props-platform/nba-props/predictions-worker:prod-20251123-193000
[2025-11-23 19:38:23] Deploying to Cloud Run...
[2025-11-23 19:40:45] Cloud Run deployment complete
[2025-11-23 19:40:46] Configuring Pub/Sub subscription...
[2025-11-23 19:41:10] Subscription configured
[2025-11-23 19:41:11] Testing deployment...
[2025-11-23 19:41:15] Health check: OK
[2025-11-23 19:41:16] Deployment successful!
```

---

### Step 5: Deploy Prediction Coordinator (60 min)

**Update deployment script for region:**
```bash
# Edit bin/predictions/deploy/deploy_prediction_coordinator.sh
# Change REGION from "us-central1" to "us-west2"
```

**Deploy:**
```bash
# Run deployment script
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod

# This will:
# 1. Build Docker image (~5 min)
# 2. Push to Artifact Registry (~3 min)
# 3. Deploy to Cloud Run (~2 min)
# 4. Configure Pub/Sub subscription (~1 min)
# 5. Verify deployment (~1 min)
```

---

### Step 6: End-to-End Testing (30 min)

**Testing Strategy:** We're following a pragmatic E2E-first approach. See comprehensive testing plan: `/docs/deployment/07-phase5-testing-strategy.md`

**Approach:**
1. Deploy → E2E tests → Unit tests (based on findings)
2. Cloud Run allows instant rollback if issues found
3. 4/5 prediction systems production-ready (XGBoost using mock)

**Test 1: Health Checks**
```bash
# Get service URLs
WORKER_URL=$(gcloud run services describe prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --format="value(status.url)")

COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
  --project=nba-props-platform \
  --region=us-west2 \
  --format="value(status.url)")

# Test health endpoints
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "${WORKER_URL}/health"
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "${COORDINATOR_URL}/health"
```

**Test 2: Manual Prediction Request**
```bash
# Publish test message to prediction-request topic
gcloud pubsub topics publish prediction-request \
  --project=nba-props-platform \
  --message='{
    "player_lookup": "lebron-james",
    "game_date": "2025-11-23",
    "game_id": "20251123_LAL_GSW",
    "line_values": [25.5, 26.5, 27.5]
  }'

# Wait 30 seconds for processing

# Check BigQuery for prediction
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  player_lookup,
  game_date,
  prediction_points,
  confidence_score,
  systems_used
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE player_lookup = 'lebron-james'
  AND game_date = '2025-11-23'
ORDER BY created_at DESC
LIMIT 1;
"
```

**Test 3: Coordinator Batch**
```bash
# Trigger coordinator for a specific game date
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  "${COORDINATOR_URL}/start" \
  -d '{
    "game_date": "2025-11-23"
  }'

# Monitor progress
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${COORDINATOR_URL}/status?game_date=2025-11-23"

# Check Cloud Run logs
gcloud run services logs read prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=50
```

---

### Step 7: Monitoring Setup (30 min)

**Create Monitoring Dashboard:**
- Prediction latency (p50, p95, p99)
- Prediction accuracy by system
- Worker auto-scaling metrics
- Pub/Sub message backlog

**Add Alerting:**
- Prediction failures >5% in 1 hour
- Worker service down
- Pub/Sub message backlog >1000

**SQL Monitoring Queries:**
```sql
-- Recent Predictions
SELECT
  game_date,
  COUNT(*) as total_predictions,
  AVG(confidence_score) as avg_confidence,
  COUNTIF(ensemble_used) as ensemble_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC;

-- System Performance
SELECT
  system_name,
  COUNT(*) as predictions_made,
  AVG(confidence_score) as avg_confidence,
  AVG(prediction_points) as avg_prediction
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= CURRENT_DATE() - 7
  AND system_name IS NOT NULL
GROUP BY system_name
ORDER BY predictions_made DESC;
```

---

## Region Configuration Fix

**Files to Update:**
1. `bin/predictions/deploy/deploy_prediction_worker.sh`
   - Line 54: Change `REGION="us-central1"` to `REGION="us-west2"`

2. `bin/predictions/deploy/deploy_prediction_coordinator.sh`
   - Similar change for region

**Automated Fix:**
```bash
# Update worker deployment script
sed -i 's/REGION="us-central1"/REGION="us-west2"/' \
  bin/predictions/deploy/deploy_prediction_worker.sh

# Update coordinator deployment script
sed -i 's/REGION="us-central1"/REGION="us-west2"/' \
  bin/predictions/deploy/deploy_prediction_coordinator.sh

# Verify changes
grep "REGION=" bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## Deployment Timeline

| Step | Task | Time | Status |
|------|------|------|--------|
| 1 | Pre-deployment checklist | 5 min | ⏳ Ready |
| 2 | Create Pub/Sub topics | 15 min | ⏳ Ready |
| 3 | Create service accounts | 10 min | ⏳ Ready |
| 4 | Deploy prediction worker | 60 min | ⏳ Ready |
| 5 | Deploy prediction coordinator | 60 min | ⏳ Ready |
| 6 | End-to-end testing | 30 min | ⏳ Ready |
| 7 | Monitoring setup | 30 min | ⏳ Ready |

**Total Time:** ~3.5 hours (210 minutes)

---

## Post-Deployment

### Immediate (Within 1 Hour):
- Run end-to-end test with real game data
- Verify predictions in BigQuery
- Check Cloud Run auto-scaling
- Monitor Pub/Sub message flow

### Within 1 Week:
- Train XGBoost model with historical data (~4 hours)
- Replace mock model with trained model
- Backfill predictions for current season
- Tune auto-scaling parameters

### Within 1 Month:
- Integrate with Phase 6 (Web API)
- Add prediction accuracy tracking
- Optimize feature loading queries
- Add ML model retraining pipeline

---

## Rollback Plan

If deployment causes issues:

```bash
# List Cloud Run revisions
gcloud run revisions list \
  --service=prediction-worker \
  --project=nba-props-platform \
  --region=us-west2

# Rollback to previous revision
gcloud run services update-traffic prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --to-revisions=REVISION-NAME=100

# Or delete service entirely
gcloud run services delete prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --quiet
```

---

## Success Criteria

### ✅ Deployment Successful When:
- [ ] Both services deployed to Cloud Run (`prediction-worker`, `prediction-coordinator`)
- [ ] Health endpoints return 200 OK
- [ ] Pub/Sub topics created and subscriptions configured
- [ ] Test prediction request completes successfully
- [ ] Prediction appears in BigQuery within 30 seconds
- [ ] All 5 prediction systems execute (XGBoost with mock is OK)
- [ ] Cloud Run services auto-scale properly

### ✅ Production-Ready When:
- [ ] Predictions running for 3+ consecutive days
- [ ] No errors in Cloud Run logs
- [ ] Latency p95 <500ms
- [ ] Confidence scores reasonable (40-90 range)
- [ ] Ensemble predictions combining all systems

---

## Known Limitations (Temporary)

**XGBoost Mock Model:**
- XGBoost system returns placeholder predictions
- Confidence score fixed at 50
- Impact: Ensemble weights adjust automatically
- Fix: Train model with `/bin/ml/train_xgboost_model.py` (~4 hours)

**No Phase 4→5 Trigger:**
- Currently manual trigger only
- Phase 4 doesn't automatically trigger Phase 5
- Fix: Add Pub/Sub publishing to Phase 4 CASCADE schedulers

**No Accuracy Tracking:**
- Predictions written but not validated
- No feedback loop for model improvement
- Fix: Implement prediction accuracy processor

---

## Related Documentation

- Prediction Systems: `docs/predictions/tutorials/01-getting-started.md`
- Worker Architecture: `predictions/worker/ARCHITECTURE.md`
- Coordinator Architecture: `predictions/coordinator/coordinator.py`
- BigQuery Schema: `schemas/bigquery/predictions/`
- Deployment Scripts: `bin/predictions/deploy/`

---

**Document Status:** 🔄 In Progress - Redeploying with fixes
**Last Updated:** 2025-11-23 20:50 PT
**Next Action:** Wait for redeploy completion, then re-run E2E tests

## Deployment Update (2025-11-23 20:50 PT)

**Initial deployment completed** but E2E tests found issues:
- ❌ Services returned 404 (missing Docker dependencies)
- ✅ Fixed both Dockerfiles (worker: added deps, coordinator: package structure)
- 🔄 Redeploying now with corrections

**See detailed findings:** `/docs/deployment/08-phase5-deployment-lessons-learned.md`

**Dockerfile fixes:**
- Worker: Added `system_circuit_breaker.py`, `execution_logger.py`, `shared/`
- Coordinator: Restructured as proper Python package

**This validates our E2E-first testing strategy!**
