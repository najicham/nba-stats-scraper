# Session 130 Handoff - Grading Service Double Bug Fix

**Date:** 2026-02-05
**Session:** 130 (Continuation of Session 129)
**Focus:** Fixed two critical bugs preventing grading service from working

---

## What Was Fixed

### 1. ✅ Wrong Method Name Bug
**Issue:** Grading service called `process_game_date()` instead of `process_date()`
**Location:** `data_processors/grading/nba/main_nba_grading_service.py`
**Fix:** Changed both `/process` and `/grade-date` endpoints to call `process_date(target_date)`
**Impact:** Service appeared healthy but returned `AttributeError` when actually grading

### 2. ✅ Missing db-dtypes Dependency
**Issue:** BigQuery couldn't convert query results to pandas DataFrames
**Error:** `ModuleNotFoundError: No module named 'db_dtypes'`
**Location:** `data_processors/grading/nba/requirements.txt`
**Fix:** Added `db-dtypes==1.2.0`
**Impact:** Service started fine but crashed when querying BigQuery

### 3. ✅ Regrading Completed
Successfully regraded Feb 3-4 predictions:
- **Feb 3:** 843 records written, 65 graded for catboost_v9
- **Feb 4:** 471 records written, 46 graded for catboost_v9

---

## Key Learning: Silent Failure Pattern

**Both bugs passed basic health checks but failed during execution.**

This is the EXACT scenario Session 129's deep health checks were designed to catch:
1. Service deploys successfully ✓
2. Basic `/health` endpoint works ✓
3. Service crashes when actually processing requests ✗

**Pattern:**
- Session 129: Missing `predictions/` module → fixed with Dockerfile + deep health checks
- Session 130: Missing `db-dtypes` → same class of bug, different dependency

**Root Cause:** Dependency testing only validates imports at startup, not imports triggered during request processing.

---

## Why Grading Coverage Appears "Low"

**This is correct behavior!**

| Date | Total Predictions | OVER/UNDER (Graded) | PASS/HOLD (Not Graded) | Grading % |
|------|-------------------|---------------------|------------------------|-----------|
| Feb 3 | 106 | 65 | 41 | 61.3% |
| Feb 2 | 62 | 53 | 9 | 85.5% |
| Feb 1 | 118 | 89 | 29 | 75.4% |

**Why PASS/HOLD aren't graded:**
- PASS = "Low confidence, don't bet"
- HOLD = "Edge too small, don't bet"
- These are NOT actionable predictions
- Grading processor correctly skips them (by design)

**Feb 3 had more PASS/HOLD predictions** (38.7% vs ~15-25% typical), indicating the model was more conservative that day - this is expected behavior when confidence is lower.

---

## Commits

- `105502c4` - fix: Fix grading service with correct method name and missing dependency

---

## Outstanding Issues

### 1. ⚠️ Missing Slack Webhook Secret (from Session 129)
```
Error: 404 Secret [projects/756957797294/secrets/SLACK_WEBHOOK_URL] not found
```
- **Impact:** Drift monitoring function runs but can't send Slack alerts
- **Fix:** Create secret in Secret Manager or update function to use correct secret name
- **Priority:** Medium (monitoring works, just can't alert)

### 2. ⚠️ Smoke Tests Require Auth
- Smoke tests fail with 403 on `/health` and `/health/deep` endpoints
- Service requires authentication for all endpoints
- **Options:**
  1. Update smoke tests to use auth tokens
  2. Make health endpoints publicly accessible (remove auth requirement)
- **Priority:** Medium (doesn't affect functionality, just deployment verification)

### 3. 🔍 Deep Health Check Not Testing BigQuery
**Current deep health check:**
- ✅ Tests imports (predictions, shared modules)
- ✅ Tests BigQuery connectivity (simple `SELECT 1`)
- ✅ Tests Firestore connectivity

**Missing:**
- ❌ Doesn't test BigQuery → pandas conversion (which requires db-dtypes)
- ❌ Would not have caught the db-dtypes bug

**Recommendation:** Add a test that actually converts BigQuery results to DataFrame:
```python
result_df = client.query("SELECT 1 as test").to_dataframe()
```

---

## Recommended Next Steps

### High Priority

1. **Enhance Deep Health Checks**
   - Add BigQuery → pandas conversion test
   - Catches dependency issues like db-dtypes
   - Apply to all services that use BigQuery

2. **Audit Other Services for Missing Dependencies**
   - Check prediction-worker, analytics, precompute
   - Look for imports that happen during request processing
   - Add missing dependencies before issues arise

3. **Fix Slack Webhook Secret**
   - Drift monitoring is working but can't alert
   - Either create secret or update function to use existing one

### Medium Priority

4. **Update Smoke Tests with Auth**
   - Current smoke tests fail due to 403
   - Either add auth tokens or make health endpoints public
   - Consider making `/health` public but `/health/deep` authenticated

5. **Document "PASS/HOLD Not Graded" Behavior**
   - Add to troubleshooting docs
   - Prevents confusion about "low" grading coverage
   - Explain expected behavior and why it's correct

---

## Defense-in-Depth Improvements

**Current Layers (Session 129):**
1. Build-time: Dockerfile dependency testing
2. Deploy-time: Smoke tests (basic health check)
3. Runtime: Deep health checks
4. Monitoring: Drift detection

**Gaps Exposed by Session 130:**
- **Build-time testing** caught the imports, but not runtime imports
- **Smoke tests** didn't test actual functionality (just health endpoint)
- **Deep health check** tested BigQuery but not pandas conversion

**Proposed Enhancement:**
```python
# In /health/deep endpoint
try:
    # Test BigQuery → pandas (catches db-dtypes)
    df = client.query("SELECT 1 as test").to_dataframe()
    checks['bigquery_pandas'] = {'status': 'ok'}
except ImportError as e:
    checks['bigquery_pandas'] = {'status': 'failed', 'error': str(e)}
    all_healthy = False
```

---

## Quick Reference

### Check Grading Coverage
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct IS NOT NULL) / COUNT(*), 1) as pct
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 3 AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1 DESC
"
```

### Manual Regrade
```bash
SERVICE_URL=$(gcloud run services describe nba-grading-service --region=us-west2 --format="value(status.url)")
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" -X POST "$SERVICE_URL/grade-date?date=2026-02-05"
```

### Check Drift Monitoring
```bash
gcloud functions logs read deployment-drift-monitor --region=us-west2 --limit=10
```

---

## Files Modified

- `data_processors/grading/nba/main_nba_grading_service.py` - Fixed method name
- `data_processors/grading/nba/requirements.txt` - Added db-dtypes

---

## Testing Performed

1. ✅ Deployed grading service with fixes
2. ✅ Manually triggered regrading for Feb 3-4
3. ✅ Verified 843 records written for Feb 3
4. ✅ Verified 471 records written for Feb 4
5. ✅ Confirmed PASS/HOLD not graded (by design)
6. ✅ Verified actual game stats exist
7. ✅ Confirmed grading coverage is expected behavior

---

## Related Sessions

- **Session 129:** Implemented deep health checks, drift monitoring
- **Session 128:** Found deployment drift pattern, Vegas line threshold issue
- **Session 122:** Dockerfile dependency inconsistency (similar issue)

---

## Key Takeaway

**Two bugs, same root cause:** Service dependencies not fully tested until actual use.

**Solution:** Enhance deep health checks to test END-TO-END functionality, not just connectivity.

**Pattern to Watch:** Any service using BigQuery + pandas needs db-dtypes tested in deep health check.
