# Session 36 Handoff - Pipeline Bug Fixes & Prediction Issues

**Date:** 2026-01-30
**Focus:** Fix grading failures, investigate prediction pipeline blockers

---

## Executive Summary

Session 36 fixed **8 critical bugs** blocking the pipeline. Jan 29 grading is now working (90 predictions graded). However, Jan 30 predictions are still blocked - the worker is processing players but predictions aren't appearing in BigQuery.

**Current Status:**
- ✅ Jan 29 grading: Fixed and working (90 graded)
- ❌ Jan 30 predictions: 0 predictions despite 319 features available
- 🔴 Model drift: Hit rate at 48.3% (CRITICAL)

---

## Bugs Fixed & Deployed

### 1. Grading Function - Missing google-cloud-storage
**File:** `orchestration/cloud_functions/grading/requirements.txt`
**Issue:** ImportError when importing shared.clients (storage_pool.py)
**Fix:** Added `google-cloud-storage==2.*`
**Deploy:** Used `./bin/deploy/deploy_grading_function.sh`

### 2. Grading Function - Module Import Error
**File:** `orchestration/cloud_functions/grading/main.py`
**Issue:** `ModuleNotFoundError: No module named 'shared'`
**Fix:** Inlined project_id logic instead of importing from shared.config
**Note:** Cloud Functions need the deployment script that bundles shared/

### 3. Grading Query - FLOAT64 Partition Error
**File:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
**Issue:** `Partitioning by expressions of type FLOAT64 is not allowed`
**Fix:** Cast line_value to STRING in ROW_NUMBER() PARTITION BY clause
```python
PARTITION BY player_lookup, game_id, system_id, CAST(line_value AS STRING)
```

### 4. Prediction Worker - Missing psutil
**File:** `predictions/worker/requirements.txt`
**Issue:** `ModuleNotFoundError: No module named 'psutil'`
**Fix:** Added `psutil==5.9.7`

### 5. Phase 4 ML Feature Store - Undefined fallback_line
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
**Issue:** `NameError: name 'fallback_line' is not defined`
**Fix:** Use season_avg_fallback instead:
```python
season_avg_fallback = phase4_data.get('points_avg_season') or phase3_data.get('points_avg_season') or 10.0
```

### 6. Execution Logger - NULL Array Error
**File:** `predictions/worker/execution_logger.py`
**Issue:** `JSON parsing error: Only optional fields can be set to NULL. Field: line_values_requested`
**Fix:** Ensure never None for REPEATED field:
```python
'line_values_requested': line_values_requested or [],
```

### 7. Pub/Sub OIDC Audience
**Subscription:** `prediction-request-prod`
**Issue:** Missing audience in OIDC token causing 403 auth errors
**Fix:**
```bash
gcloud pubsub subscriptions update prediction-request-prod \
  --push-auth-token-audience="https://prediction-worker-f7p3g7f6ya-wl.a.run.app" \
  --project=nba-props-platform
```

### 8. Feature Version Mismatch
**File:** `predictions/worker/data_loaders.py`
**Issue:** Worker looks for `v2_33features` but data has `v2_37features`
**Fix:** Updated default to `v2_37features`

---

## Still Broken - Jan 30 Predictions

### Symptoms
- 319 features exist in ml_feature_store_v2
- ~100 players have betting lines in odds_api
- Worker is receiving requests and processing players
- Execution logger failing to write logs
- **0 predictions in player_prop_predictions table**

### Logs Show
```
Worker processing: dennisschroder, shaedonsharpe, etc.
Execution logger ERROR: line_values_requested NULL
Authentication errors from some Pub/Sub messages
```

### Investigation Needed
1. **Why aren't predictions being written to BigQuery?**
   - Check if worker write_predictions() is being called
   - Check for errors in prediction write path

2. **Execution logger NULL issue persists**
   - The `or []` fix may not be reaching all code paths
   - Need to trace where line_values comes from

3. **Some Pub/Sub messages still getting 403**
   - May be old messages in queue with wrong auth
   - Or audience fix didn't propagate to all subscriptions

### Quick Debug Commands
```bash
# Check predictions for today
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = DATE('2026-01-30')"

# Check worker logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker"' --limit=50 --format="value(textPayload)" --project=nba-props-platform | grep -v "169.254"

# Check features exist
bq query --use_legacy_sql=false "SELECT COUNT(*), feature_version FROM nba_predictions.ml_feature_store_v2 WHERE game_date = DATE('2026-01-30') GROUP BY 2"

# Trigger predictions manually
gcloud scheduler jobs run morning-predictions --location=us-west2 --project=nba-props-platform
```

---

## Model Drift Alert (Separate Issue)

Weekly hit rate has dropped significantly:

| Week | Hit Rate | Status |
|------|----------|--------|
| Jan 25 | 48.3% | 🔴 CRITICAL |
| Jan 18 | 51.6% | 🔴 CRITICAL |
| Jan 11 | 56.3% | 🟡 WARNING |
| Jan 4 | 62.7% | ✅ OK |

**Query:**
```sql
SELECT DATE_TRUNC(game_date, WEEK) as week,
       ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1 ORDER BY 1 DESC
```

**Root Cause:** Unknown - needs investigation. May require model retraining.

---

## Commits This Session

```
b97971e5 fix: Multiple pipeline bug fixes from Session 36
9070627d fix: Update feature_version to v2_37features in prediction worker
```

---

## Deployments This Session

| Service | Fix | Method |
|---------|-----|--------|
| phase5b-grading | Dependencies, query fix | `./bin/deploy/deploy_grading_function.sh` |
| nba-phase4-precompute-processors | fallback_line | `./bin/deploy-service.sh` |
| prediction-worker | psutil, feature_version, logger | Manual docker push + gcloud deploy |

---

## Next Session Priority Checklist

### Priority 1: Fix Jan 30 Predictions
1. [ ] Trace prediction write path in worker.py
2. [ ] Check for errors after feature loading succeeds
3. [ ] Verify predictions are being generated (not just logged)
4. [ ] Check if there's a BigQuery write error being swallowed

### Priority 2: Clean Up Execution Logger
1. [ ] Find where line_values is passed as None
2. [ ] Add defensive handling at caller level
3. [ ] Consider making field nullable in BigQuery schema

### Priority 3: Verify All Systems
1. [ ] Run `/validate-daily` after fixes
2. [ ] Confirm Jan 30 predictions are generated
3. [ ] Check grading runs for Jan 30

### Priority 4: Model Drift Investigation
1. [ ] Review CatBoost V8 performance analysis docs
2. [ ] Check player tier breakdown
3. [ ] Consider recency-weighted retraining

---

## Key Files Changed

| File | Lines Changed |
|------|--------------|
| `orchestration/cloud_functions/grading/requirements.txt` | +1 |
| `orchestration/cloud_functions/grading/main.py` | +5 -2 |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | +2 -1 |
| `predictions/worker/requirements.txt` | +1 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | +3 -2 |
| `predictions/worker/execution_logger.py` | +1 -1 |
| `predictions/worker/data_loaders.py` | +3 -3 |

---

## Important Context

### Grading Deployment
The grading function MUST be deployed using `./bin/deploy/deploy_grading_function.sh` because it:
- Bundles `shared/`, `data_processors/`, and `predictions/` directories
- The Cloud Function source doesn't include these by default

### Feature Version
The ML feature store uses `v2_37features` (37 features). If Phase 4 processor is updated with new features, the worker's data_loaders.py must also be updated to match.

### Betting Data
Only ~100 players had betting lines for Jan 30. This limits how many predictions can be generated. The system correctly skips players without lines.

---

*Session 36 complete. Critical blockers partially resolved, predictions still need debugging.*
