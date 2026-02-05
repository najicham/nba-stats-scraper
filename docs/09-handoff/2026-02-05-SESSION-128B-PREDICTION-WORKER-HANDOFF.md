# Session 128B - Prediction Worker Fix for Feature Version Mismatch

**Date:** 2026-02-05 12:00 PM ET
**Status:** 🔴 CRITICAL - No predictions for tonight's 8 games
**For:** New chat session to deploy fix and unblock predictions

---

## IMMEDIATE PROBLEM

**No predictions exist for tonight's 8 NBA games (Feb 5, 2026)**

All 125 prediction requests failed with `no_features` error because of feature version mismatch:
- Worker expects: `v2_37features` (hardcoded default)
- Table contains: `v2_39features` (upgraded in Session 126)
- Result: Query returns 0 rows → 100% prediction failures

---

## ROOT CAUSE

**Feature version mismatch after Session 126 upgrade:**

1. **Session 126 (Feb 5):** ML feature store upgraded to `v2_39features`
   - Added features 37-38 (breakout_risk_score, composite_breakout_signal)
   - 273 players successfully generated with new version

2. **Session 127 handoff:** Explicitly said "Deploy prediction-worker" but **deployment was skipped**

3. **Today (12:00 PM ET):** Coordinator published 125 prediction requests
   - All failed in 16 seconds
   - Worker queried for `v2_37features` which doesn't exist
   - No predictions generated for tonight

---

## SOLUTION IMPLEMENTED

**Auto-detection of feature version** (Commit: TBD)

Added `_detect_feature_version()` method that:
1. Queries which feature version actually exists for a game_date
2. Caches the result to avoid repeated queries
3. Defaults to 'auto' mode in all load_features methods
4. Tries v2_39features first (newer), falls back to v2_37features (legacy)

**Files Changed:**
- `predictions/worker/data_loaders.py`
  - Added `_detect_feature_version()` method
  - Changed default from `'v2_37features'` to `'auto'` in 3 methods
  - Added `_feature_version_cache` to __init__

**Benefits:**
- Works with both v2_37 and v2_39 feature versions
- Supports gradual rollout (some dates have v2_39, others have v2_37)
- No hard-coding needed when adding new features
- Backward compatible

---

## IMMEDIATE ACTIONS REQUIRED

### 1. Deploy prediction-worker (CRITICAL)

```bash
# Commit the auto-detection code (already done)
git push origin main

# Deploy prediction-worker
./bin/deploy-service.sh prediction-worker
```

**Expected deployment time:** 3-5 minutes

### 2. Trigger predictions for Feb 5

After deployment completes:

```bash
# Trigger predictions manually
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-05", "trigger_reason": "feature_version_fix_deployment"}'
```

### 3. Verify predictions are generating

```bash
# Check prediction count (should start increasing)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT system_id) as models
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-05'"

# Check worker logs for success
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"SUCCESS"' --limit=10 --freshness=5m
```

**Expected:** 130+ predictions across 8 models within 5-10 minutes

---

## CONTEXT FOR NEW CHAT

### Why This Happened

1. **Deployment drift:** Session 127 said to deploy prediction-worker but it wasn't done
2. **Feature version upgrade:** Session 126 added 2 new features (37-38) for breakout detection
3. **Hardcoded version:** Worker had v2_37features hardcoded instead of detecting

### Why Auto-Detection Matters

The user is adding features incrementally:
- **v2_37features:** 37 features (current prod for old dates)
- **v2_39features:** 39 features (new with breakout, rolling out now)
- **Future:** May have v2_41features, v2_43features, etc.

Hard-coding the version breaks whenever features are added. Auto-detection supports:
- Multiple versions coexisting (historical vs new dates)
- Gradual rollout (test on one date before full deployment)
- Future-proofing (no code changes needed for new features)

### Timeline

| Time (ET) | Event |
|-----------|-------|
| Feb 5, 12:00 AM | Session 126: ML features upgraded to v2_39 |
| Feb 5, 12:01 PM | Coordinator triggered 125 predictions |
| Feb 5, 12:01 PM | All 125 failed with "no_features" |
| Feb 5, 12:30 PM | Session 128B: Diagnosed + implemented auto-detection |
| **Now** | **Waiting for deployment + manual trigger** |

---

## VERIFICATION STEPS

After deploying and triggering:

### 1. Check feature version detection is working

```bash
# Should see logs like "Auto-detected feature version: v2_39features"
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"Auto-detected"' --limit=5 --freshness=10m
```

### 2. Check predictions are succeeding

```bash
# Should see SUCCESS logs, not PERMANENT failures
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND jsonPayload.status="SUCCESS"' --limit=10 --freshness=10m
```

### 3. Check final prediction count

```bash
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-05'
  AND is_active = TRUE
GROUP BY system_id
ORDER BY system_id"
```

**Expected:** 130-140 predictions per model (8 models total)

---

## IF PREDICTIONS STILL FAIL

If auto-detection doesn't work or predictions still fail:

### Fallback Plan: Force v2_39 for now

```python
# Edit data_loaders.py line 144
feature_version: str = 'v2_39features'  # Force v2_39 temporarily
```

Then redeploy. This will work for Feb 5+ but break historical dates that have v2_37.

---

## RELATED ISSUES FROM SESSION 128B

This is part of a larger Session 128B investigation that found:

1. ✅ **Edge filter bug** - Fixed in oddsapi_batch_processor
2. ✅ **DNP recency filter** - Fixed in player_daily_cache
3. ✅ **Missing games** - Reprocessed Feb 4 (7/7 games now complete)
4. 🔄 **Feature version mismatch** - THIS ISSUE (needs deployment)

**Commits:**
- `a7dc5d9d` - Edge filter + DNP recency fixes
- `b648907f` - Session 128B handoff doc
- `TBD` - Auto-detection feature (needs push + deploy)

---

## FOR THE NEW CHAT

**Your mission:**
1. Push the auto-detection commit (if not already pushed)
2. Deploy prediction-worker
3. Manually trigger predictions for Feb 5
4. Verify 130+ predictions generated successfully
5. Monitor tonight's games to ensure predictions are available

**Time sensitivity:** Games start at 7 PM ET (6.5 hours from now). Predictions should be live by 2 PM ET ideally.

Good luck! 🚀
