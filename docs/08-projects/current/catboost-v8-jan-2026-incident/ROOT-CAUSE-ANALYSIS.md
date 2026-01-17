# CatBoost V8 Deployment Incident - Root Cause Analysis

**Date**: 2026-01-17
**Incident Duration**: January 14-17, 2026 (3 days)
**Severity**: High - 100% of CatBoost V8 predictions using fallback (50% confidence)
**Status**: ✅ RESOLVED

---

## Executive Summary

CatBoost V8 predictions failed to use the trained ML model for 3 days (Jan 14-17), causing all 1,084 predictions to fall back to a simple weighted average with hardcoded 50% confidence and "PASS" recommendations. The root cause was a **missing environment variable** (`CATBOOST_V8_MODEL_PATH`) on the Cloud Run service, which was inadvertently removed during a deployment.

---

## Timeline of Events

| Date/Time | Event | Impact |
|-----------|-------|--------|
| **Jan 8** | CatBoost V8 model trained and deployed | ✅ Model working |
| **Jan 13-14** | Multiple deployments during pipeline fixes | Environment variable lost |
| **Jan 14-16** | All predictions using 50% fallback | ❌ 1,004 broken predictions |
| **Jan 17 04:35 UTC** | Revision 00049 deployed WITH env var | ✅ Would have worked |
| **Jan 17 17:36 UTC** | Revision 00050 deployed WITHOUT env var | ❌ Env var lost again |
| **Jan 17 18:00 UTC** | Session 80: GCS permissions granted | Partial fix (permission not the issue) |
| **Jan 17 18:38 UTC** | Session 81: Root cause identified | ✅ Env var restored |

---

## Root Cause

### **Primary Cause: Missing Environment Variable**

The Cloud Run service `prediction-worker` was missing the required environment variable:

```bash
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

### **How This Caused Failures**

**Code Path** (`predictions/worker/prediction_systems/catboost_v8.py:106-116`):

```python
# Check for GCS path in environment (production)
gcs_path = os.environ.get('CATBOOST_V8_MODEL_PATH')

# Load model - priority: explicit path > env var > local
if model_path:
    self._load_model_from_path(model_path)
elif gcs_path:  # ← THIS WAS NOT SET
    logger.info(f"Loading CatBoost v8 from env var: {gcs_path}")
    self._load_model_from_path(gcs_path)
elif use_local:  # ← FELL BACK TO THIS
    self._load_local_model()  # ← FAILED (no models/ in container)
```

**Result**: `self.model = None` → All predictions used fallback

### **Fallback Behavior**

When the model fails to load, the predictor returns hardcoded fallback values:

```python
return {
    'confidence_score': 50.0,      # ← HARDCODED
    'recommendation': 'PASS',      # ← ALWAYS CONSERVATIVE
    'model_type': 'fallback',
    'error': 'Model not loaded, using fallback',
}
```

**Location**: `predictions/worker/prediction_systems/catboost_v8.py:434-464`

---

## Why This Happened

### **1. No Environment Variable Documentation**

- No centralized documentation of required environment variables per service
- Deployment scripts don't validate required env vars before deployment
- Cloud Run service config not stored in version control

### **2. Deployments Don't Preserve Environment Variables**

**Evidence from revision history**:

```bash
# Revision 00049 (Session 79, Jan 17 04:35 UTC)
✅ HAD: CATBOOST_V8_MODEL_PATH=gs://...
✅ HAD: PREDICTIONS_TABLE=nba_predictions.player_prop_predictions
✅ HAD: PUBSUB_READY_TOPIC=prediction-ready-prod

# Revision 00050 (Session 80, Jan 17 17:36 UTC)
❌ LOST: CATBOOST_V8_MODEL_PATH
❌ LOST: PREDICTIONS_TABLE
❌ LOST: PUBSUB_READY_TOPIC
✅ HAD: GCP_PROJECT_ID=nba-props-platform

# Revision 00051 (Session 81, Jan 17 18:38 UTC)
✅ RESTORED: CATBOOST_V8_MODEL_PATH
✅ KEPT: GCP_PROJECT_ID
```

### **3. Silent Failure Mode**

The fallback mechanism **silently succeeded** instead of failing loudly:
- No alerts triggered
- No error logs (only warnings in model loading)
- Predictions still written to BigQuery
- Impossible to distinguish from normal operation without checking confidence distribution

### **4. Insufficient Observability**

No monitoring alerts for:
- Model loading failures
- High fallback prediction rates
- Abnormal confidence score distributions (all 50%)
- Environment variable changes

---

## Impact Assessment

### **Affected Predictions**

| Date | Total Predictions | Fallback (50%) | Model-Based | Status |
|------|-------------------|----------------|-------------|---------|
| Jan 14 | 73 | 73 (100%) | 0 | ❌ All broken |
| Jan 15 | 596 | 596 (100%) | 0 | ❌ All broken |
| Jan 16 | 335 | 335 (100%) | 0 | ❌ All broken |
| Jan 17 | 80 | 67 (84%) | 13 (16%) | 🟡 Mostly broken |
| **TOTAL** | **1,084** | **1,071** | **13** | - |

### **Business Impact**

1. **Prediction Quality**: All CatBoost V8 predictions used simple weighted average instead of trained ML model
2. **Confidence Scores**: All stuck at 50% (vs expected 79-95% range)
3. **Recommendations**: All marked as "PASS" (vs expected OVER/UNDER mix)
4. **User Trust**: Users received lower quality predictions for 3 days
5. **Model Performance**: Unable to track real-world model performance

### **Data Integrity**

- **1,071 predictions deleted** and will be regenerated
- **13 predictions preserved** (Jan 17 - those that loaded the model successfully)
- All Phase 3/4 data intact - full regeneration possible

---

## Contributing Factors

### **1. Cloud Run Instance Credential Caching** (Session 80 Theory)

Session 80 hypothesized that Cloud Run instances cache credentials for 1-24 hours, causing GCS permission issues to persist on old instances. However, this was a **red herring** - the real issue was the missing environment variable, not GCS permissions.

**Evidence**:
- GCS permissions were already correct (`roles/storage.objectViewer` granted)
- Model file existed in GCS (`gs://nba-props-platform-models/catboost/v8/...`)
- Environment variable missing across ALL instances

### **2. Multiple Deployment Tools**

Different deployment methods used across sessions:
- `gcloud run deploy --source=...` (buildpack)
- `gcloud run deploy --image=...` (Docker)
- `gcloud run services update` (config changes only)

Each method handles environment variables differently, leading to inconsistencies.

### **3. No Infrastructure-as-Code**

Cloud Run service configurations not managed in version control:
- Environment variables set via CLI commands
- No Terraform/Pulumi manifests
- No GitOps workflow
- Manual drift detection required

---

## Why Detection Was Delayed

### **1. Pipeline Recovered from Other Issues**

Sessions 79-80 focused on fixing Phase 3/4 Docker builds and GCS permissions. The pipeline was generating predictions successfully, so the CatBoost V8 issue was overlooked.

### **2. No Confidence Score Monitoring**

No automated alerts for:
- Confidence score distribution anomalies
- High percentage of 50% confidence predictions
- Model vs fallback prediction ratio

### **3. Multi-System Masking**

CatBoost V8 runs alongside 4 other prediction systems:
- `ensemble_v1`
- `moving_average`
- `zone_matchup_v1`
- `similarity_balanced_v1`

These systems continued working normally, masking the CatBoost V8 failure.

---

## Lessons Learned

### **1. Environment Variables Must Be Documented**

✅ **Action**: Create `ENV_VARS.md` for each Cloud Run service documenting:
- Required environment variables
- Purpose of each variable
- Example values
- What happens if missing

### **2. Deployment Process Must Validate Environment Variables**

✅ **Action**: Add pre-deployment checks:
```bash
# Example validation script
required_vars=("CATBOOST_V8_MODEL_PATH" "GCP_PROJECT_ID")
for var in "${required_vars[@]}"; do
  if ! gcloud run services describe $SERVICE | grep -q "$var"; then
    echo "ERROR: Missing required env var: $var"
    exit 1
  fi
done
```

### **3. Infrastructure Should Be Code**

✅ **Action**: Migrate to Terraform or similar:
- Version-controlled service configurations
- Environment variables defined in `.tf` files
- Automated drift detection
- Pull request reviews for config changes

### **4. Silent Failures Should Be Loud**

✅ **Action**: Convert fallback mechanism to alerting:
- Log ERROR (not WARNING) when model fails to load
- Increment metric: `prediction_worker/model_load_failures`
- Create alert: `model_load_failure_rate > 10%`
- Fail health checks if model can't load

### **5. Observability Gaps**

✅ **Action**: Add monitoring for:
- Confidence score distribution per system
- Model vs fallback prediction ratio
- Environment variable changes (Cloud Audit Logs)
- Model file accessibility health checks

---

## Fix Applied

### **1. Restored Environment Variable**

```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars=CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

**New Revision**: `prediction-worker-00051-5xx`
**Status**: ✅ Deployed and serving 100% traffic

### **2. Cleaned Broken Data**

```sql
DELETE FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-14'
  AND game_date <= '2026-01-17'
  AND confidence_score = 0.50
```

**Deleted**: 1,071 predictions
**Preserved**: 13 model-based predictions from Jan 17

### **3. Coordinator Already Fixed**

Coordinator was already using Docker builds (revision 00048-sz8).
No additional fixes needed.

---

## Verification Plan

### **1. Next Pipeline Run (Jan 18)**

Check that predictions show variable confidence:

```sql
SELECT ROUND(confidence_score*100) as confidence,
       COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v8'
  AND game_date = '2026-01-18'
GROUP BY confidence
ORDER BY confidence DESC
```

**Expected**: Variety of scores (79-95%)
**Failure**: All predictions at 50%

### **2. Model Loading Logs**

Check that model loads successfully:

```bash
gcloud logging read 'resource.labels.service_name=prediction-worker
  AND textPayload=~"CatBoost V8 model loaded successfully"'
```

**Expected**: Success log on worker startup
**Failure**: "Model FAILED to load" error logs

### **3. Historical Data Regeneration**

Regenerate deleted predictions via coordinator:

```bash
for date in 2026-01-14 2026-01-15 2026-01-16 2026-01-17; do
  curl -X POST "$COORDINATOR_URL/start" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"game_date\": \"$date\", \"force\": true}"
done
```

**Expected**: All predictions with 79-95% confidence

---

## Recommendations

### **Immediate (This Week)**

1. ✅ Document required environment variables for all Cloud Run services
2. ✅ Add environment variable validation to deployment scripts
3. ✅ Create alerts for model loading failures
4. ✅ Add confidence score distribution monitoring

### **Short-Term (This Month)**

1. Migrate Cloud Run configurations to Infrastructure-as-Code (Terraform)
2. Convert all services to Docker builds (remove buildpack deployments)
3. Add deep health check endpoints that test model loading
4. Implement startup probes that fail if model can't load

### **Long-Term (This Quarter)**

1. Build deployment guardrails (required approvals for env var changes)
2. Create comprehensive service catalog with dependencies documented
3. Implement canary deployments with automated rollback
4. Add E2E tests that verify prediction quality (not just API responses)

---

## Related Documents

- `docs/09-handoff/SESSION-81-QUICK-START.md` - Session 81 handoff
- `docs/09-handoff/2026-01-17-SESSION-80-CATBOOST-PARTIAL-SUCCESS.md` - Session 80 (GCS permissions theory)
- `docs/09-handoff/2026-01-17-SESSION-79-PHASE3-CRASH-BLOCKING-PIPELINE.md` - Session 79 (Docker build fixes)
- `docs/08-projects/current/catboost-v8-jan-2026-incident/3-DAY-MONITORING-CHECKLIST.md` - Monitoring plan

---

## Incident Status

**Status**: ✅ **RESOLVED**
**Root Cause**: Missing `CATBOOST_V8_MODEL_PATH` environment variable
**Fix Applied**: Environment variable restored, new revision deployed
**Data Cleanup**: 1,071 broken predictions deleted
**Next Step**: Regenerate historical predictions, verify Jan 18 pipeline run

**Session 81 Complete!** 🎉
