# Session 78: CatBoost V8 Deployment Investigation & Rollback

**Date**: 2026-01-17 04:00-04:30 UTC
**Status**: ⚠️ CRITICAL - Predictions Working (50% Confidence) - CatBoost V8 Deployment Blocked
**Current Revision**: prediction-worker-00035-4xk (Jan 15 baseline)

---

## 🚨 EXECUTIVE SUMMARY

**Problem Discovered**: ALL Cloud Run revisions since Jan 15 are failing to start due to missing `shared` module.

**Root Cause**: The `predictions/worker/shared/` directory exists locally and in git, but Cloud Run buildpacks are NOT including it in deployments, causing `ModuleNotFoundError: No module named 'shared'`.

**Current State**:
- ✅ Rolled back to revision 00035 (Jan 15) - **predictions are working**
- ❌ CatBoost V8 model NOT deployed - predictions stuck at 50% confidence
- ❌ Cannot deploy any code changes until shared module deployment issue is resolved

---

## 📋 WHAT HAPPENED

### Timeline of Events

1. **Jan 16-17**: Session 77 attempted two separate initiatives:
   - Placeholder line remediation (validation gate)
   - CatBoost V8 model deployment

2. **Revisions Deployed** (all failing):
   - `00037-k6l`: Validation gate code → NameError: 'Tuple' not defined
   - `00042-wp5`: Added Tuple import → Still has validation gate issues
   - `00043-54v`: Unknown state
   - `00044-g7f`: Latest attempt → ModuleNotFoundError: No module named 'shared'
   - `00036-xhq`: Also has errors

3. **Session 78 Investigation**:
   - Discovered all recent revisions crash on startup
   - Attempted to roll back to working revisions
   - Found that ALL revisions after 00035 have errors
   - Identified root cause: shared module not being deployed

### Errors Found

**Revision 00037 & 00042**:
```python
NameError: name 'Tuple' is not defined
At: /app/worker.py:320
```

**Revisions 00043-00044**:
```python
ModuleNotFoundError: No module named 'shared'
At: /workspace/worker.py:48
from shared.utils.env_validation import validate_required_env_vars
```

---

## 🔍 ROOT CAUSE ANALYSIS

### The Shared Module Problem

**What exists locally**:
```bash
predictions/worker/shared/
├── alerts/
├── backfill/
├── change_detection/
├── config/
├── processors/
├── publishers/
├── utils/
│   ├── env_validation.py     # Required on line 48 of worker.py
│   ├── player_registry/      # Required for player lookups
│   └── slack_channels.py     # Required for alerting
└── validation/
```

**What gets deployed to Cloud Run**: ❌ Nothing - the directory is missing

**Why it fails**:
- Cloud Run buildpacks don't include the `shared/` directory
- Even though it's committed to git (commit 63cd71a)
- Even though it exists in the deployment source
- The Python imports fail immediately on startup

### Why Previous Deployments Worked

Revision 00035 (Jan 15) and earlier don't import from the `shared` module, so they work fine.

---

## 🎯 IMMEDIATE NEXT STEPS

### Option 1: Fix Shared Module Deployment (RECOMMENDED)

**Create a Dockerfile** to explicitly control what gets deployed:

```dockerfile
# predictions/worker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker code
COPY *.py ./
COPY prediction_systems/ ./prediction_systems/

# CRITICAL: Copy shared module
COPY shared/ ./shared/

# Set environment for gunicorn
ENV PORT=8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 540 worker:app
```

**Deploy with Dockerfile**:
```bash
cd /home/naji/code/nba-stats-scraper
gcloud run deploy prediction-worker \
  --source predictions/worker \
  --region us-west2 \
  --project nba-props-platform \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform,PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,PUBSUB_READY_TOPIC=prediction-ready-prod,CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm" \
  --allow-unauthenticated \
  --timeout=540 \
  --memory=2Gi \
  --cpu=2 \
  --max-instances=10
```

### Option 2: Remove Shared Module Dependencies (TEMPORARY)

Revert worker.py to use inline implementations instead of shared module imports. This is a temporary workaround to unblock CatBoost deployment.

**Files to modify**:
- `predictions/worker/worker.py`: Remove or inline shared imports
- Keep `quality_scorer.py` changes for CatBoost V8

---

## 📊 CURRENT SYSTEM STATUS

### Cloud Run Service
```
Service: prediction-worker
Region: us-west2
Revision: prediction-worker-00035-4xk
Traffic: 100%
Health: HEALTHY ✅
Deployed: 2026-01-15 04:46 UTC
Environment Variables: 3/3 (missing CATBOOST_V8_MODEL_PATH)
```

### Predictions Status
```
Last Run: Jan 15, 2026
Status: WORKING ✅
Issue: All predictions at 50% confidence ❌
Reason: Missing CatBoost V8 model (no CATBOOST_V8_MODEL_PATH)
```

### CatBoost V8 Model
```
Location: gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
Size: 1.1 MB
Uploaded: ✅ (Session 77)
Accessible: ✅
Deployed to Cloud Run: ❌ (blocked by shared module issue)
```

---

## 🛠️ CODE CHANGES READY TO DEPLOY

### 1. quality_scorer.py (CatBoost V8 Support)
**Location**: `data_processors/precompute/ml_feature_store/quality_scorer.py`
**Status**: ✅ Committed (63cd71a)
**Change**: Support variable feature counts (25 for v1, 33 for v8)

```python
# Before (hardcoded 25 features)
for feature_idx in range(25):

# After (dynamic feature count)
num_features = len(feature_sources)
for feature_idx in range(num_features):
```

### 2. shared/ Module
**Location**: `predictions/worker/shared/`
**Status**: ✅ Committed (63cd71a)
**Issue**: ❌ Not being deployed to Cloud Run

---

## 🎓 LESSONS LEARNED

1. **Cloud Run Buildpacks**: Don't assume all committed files will be deployed
2. **Testing**: Always verify new deployments start successfully before routing traffic
3. **Rollback Strategy**: Keep track of last known good revision
4. **Deployment Method**: Dockerfile gives explicit control vs buildpack auto-detection

---

## 📝 VERIFICATION CHECKLIST (After Fix)

Once the shared module deployment is fixed:

- [ ] New revision deploys successfully
- [ ] No startup errors in Cloud Run logs
- [ ] Environment variable `CATBOOST_V8_MODEL_PATH` is set
- [ ] Predictions generated with variable confidence (79-95%)
- [ ] High-confidence picks appear (>0 at 85%+)
- [ ] No "FALLBACK_PREDICTION" warnings
- [ ] Model loading logs show success

---

## 💡 RECOMMENDATIONS

1. **Immediate**: Create Dockerfile to fix shared module deployment
2. **Short-term**: Test deployment in staging before production
3. **Long-term**: Set up CI/CD pipeline with automated deployment tests

---

## 📞 FOR NEXT SESSION

**Start here**:
1. Read this document
2. Choose Option 1 (Dockerfile) or Option 2 (remove shared deps)
3. Test deployment creates revision without errors
4. Verify CatBoost V8 model loads successfully
5. Check predictions show variable confidence

**Key Files**:
- `/home/naji/code/nba-stats-scraper/predictions/worker/` - Worker code
- `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/quality_scorer.py` - CatBoost support
- `docs/08-projects/current/catboost-v8-jan-2026-incident/` - Full incident documentation

**Git Status**:
- Current branch: `main`
- HEAD: `63cd71a` - "fix(catboost): Deploy CatBoost V8 model support with shared module"
- Ready to deploy once shared module issue is resolved

---

**Good luck! The code changes are ready - we just need to fix the deployment process! 🚀**
