# Session 131 Handoff - Feb 5 Prediction Blocker Investigation

**Date:** 2026-02-05
**Duration:** ~3 hours
**Status:** ⚠️ PARTIAL - Root causes fixed, regeneration in progress

## Executive Summary

Identified and fixed TWO critical bugs blocking Feb 5 predictions, but feature regeneration is experiencing Phase 4 service issues. Predictions blocked since Feb 4 deployment.

**Impact:**
- 0 predictions generated for Feb 5 (8 games, 136 expected players)
- Root causes: Worker feature cache bug + Model/feature version mismatch
- Both root causes FIXED, but Phase 4 regeneration incomplete

## Root Causes Identified & Fixed

### 1. Worker Feature Version Cache Bug ✅ FIXED

**Problem:**
- Worker's singleton `PredictionDataLoader` caches feature_version detection
- Cached `v2_37features` from historical dates
- When Phase 4 generated `v2_39features` for Feb 5, worker kept querying for `v2_37features`
- **Result:** All 125 workers failed with "No features available" despite data existing

**Evidence:**
```
# Data exists
bq: SELECT feature_version, COUNT(*) WHERE game_date='2026-02-05'
v2_39features | 273

# Worker queried wrong version
Worker logs: "Batch loading features for 273 players, feature_version=v2_37features"
Worker logs: "Batch loaded features for 0/273 players"
```

**Root Cause:**
`data_loaders.py:152-154` - Feature version cache never invalidated:
```python
if game_date in self._feature_version_cache:
    return self._feature_version_cache[game_date]  # Stale forever!
```

**Fix:**
- Restarted `prediction-worker` service to clear singleton cache
- **TODO:** Add TTL or cache invalidation for feature_version_cache

**Code Location:** `predictions/worker/data_loaders.py:139-186`

---

### 2. Model/Feature Version Incompatibility ✅ FIXED

**Problem:**
- CatBoost V8/V9 models trained on 33 features (v2_37features)
- Session 128B added 2 breakout classifier features = 39 features (v2_39features)
- Models explicitly check feature_version and reject v2_39features:
  ```
  ERROR: CatBoost V8 requires feature_version='v2_37features', got 'v2_39features'
  ```

**Evidence:**
```
Worker logs (18:27):
- "Invalid feature count: 39"
- "Monthly model catboost_v9_2026_02 failed: requires v2_37features, got v2_39features"
```

**Root Cause:**
- `ml_feature_store_processor.py:90` set to `FEATURE_VERSION = 'v2_39features'`
- Models not retrained on 39 features
- No backward compatibility layer

**Fix:**
Temporarily reverted Phase 4 to v2_37features (commit `c20da233`):
- Changed `FEATURE_VERSION = 'v2_37features'`
- Changed `FEATURE_COUNT = 37`
- Commented out breakout features:
  - `breakout_risk_score` (feature 37)
  - `composite_breakout_signal` (feature 38)

**Files Modified:**
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Deployed:**
- `nba-phase4-precompute-processors` (revision 00134-zvr, commit c20da233)

---

### 3. Coordinator Performance Issue (NOT FIXED - Separate Issue)

**Problem:**
- Coordinator loads betting lines SEQUENTIALLY (1-2 sec per player)
- 136 players × 1.5 sec average = 6-9 minutes just for line loading
- Times out or takes excessive time

**Evidence:**
```
Coordinator logs:
18:19:15 - Started loading players
18:20:03 - Still loading lines (48 seconds in)
18:22:39 - Still loading lines (3+ minutes in)
18:25:12 - Published 125 requests (6 minutes total)
```

**Impact:** Delays prediction generation by 6-9 minutes

**Recommendation:** Parallelize betting line loading in `player_loader.py`

## Actions Taken

### Deployments
1. ✅ Restarted `prediction-worker` (cleared feature cache)
2. ✅ Deployed `nba-phase4-precompute-processors` with v2_37features

### Data Operations
1. ✅ Deleted 273 v2_39features records for Feb 5
2. ⏳ Triggered Phase 4 regeneration (experiencing issues - see below)

### Code Changes
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
  - Lines 86-91: Changed FEATURE_VERSION to v2_37features
  - Lines 125-138: Commented out breakout features in FEATURE_NAMES
  - Lines 1718-1731: Commented out breakout feature calculations
  - Lines 207-211: Commented out validation ranges
- Commit: `c20da233`

## Current Status - Phase 4 Regeneration Issues

### Problem
Phase 4 service experiencing worker timeouts and crashes:

```
Logs (18:39:56):
[CRITICAL] WORKER TIMEOUT (pid:2)
[ERROR] Worker (pid:2) was sent SIGKILL! Perhaps out of memory?
POST /process returns 400 errors
```

### Attempted
1. Published to `nba-phase3-analytics-complete` topic (message ID: 18371462858021355)
2. Service received POST /process requests but returned 400 errors
3. Worker crashed with possible OOM

### Next Steps Required

**IMMEDIATE (to complete Feb 5 predictions):**

1. **Debug Phase 4 400 errors:**
   ```bash
   gcloud run services logs read nba-phase4-precompute-processors \
     --region=us-west2 --limit=200 | grep -B5 -A5 "400\|ERROR"
   ```

2. **Check orchestrator configuration:**
   ```bash
   gcloud run services logs read nba-phase3-to-phase4-orchestrator \
     --region=us-west2 --limit=100
   ```

3. **Alternative: Manual Phase 4 trigger via Cloud Functions:**
   ```bash
   # If orchestrator isn't working, trigger Phase 4 processors directly
   # Check: bin/manual-phase4-trigger.sh (if exists)
   ```

4. **Once Phase 4 completes, verify v2_37features:**
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT feature_version, COUNT(*) FROM nba_predictions.ml_feature_store_v2
      WHERE game_date = '2026-02-05' GROUP BY feature_version"
   # Expected: v2_37features | 273
   ```

5. **Trigger predictions:**
   ```bash
   gcloud pubsub topics publish nba-phase4-precompute-complete \
     --message='{"game_date": "2026-02-05", "trigger_source": "session_131_final"}'
   ```

6. **Verify predictions generated:**
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
      WHERE game_date = '2026-02-05'"
   # Expected: ~200-300 predictions
   ```

## Long-Term Recommendations

### 1. Feature Version Compatibility Layer
**Problem:** Model/feature version mismatches cause hard failures

**Solution:**
- Maintain both v2_37features and v2_39features in parallel
- Workers auto-select based on model requirements
- Or: Retrain models on 39 features

### 2. Feature Version Cache TTL
**Problem:** Stale cache causes "No features" errors

**Solution:**
```python
# In data_loaders.py _detect_feature_version()
FEATURE_VERSION_CACHE_TTL = 300  # 5 minutes
if game_date in self._feature_version_cache:
    if time.time() - self._cache_timestamp < FEATURE_VERSION_CACHE_TTL:
        return self._feature_version_cache[game_date]
```

### 3. Coordinator Performance
**Problem:** Sequential line loading takes 6-9 minutes

**Solution:**
- Batch/parallel betting line fetches
- Or: Pre-cache lines in Phase 4

### 4. Phase 4 Memory Issues
**Problem:** Worker timeouts suggest OOM

**Investigation Needed:**
- Check Phase 4 memory limits
- Profile memory usage during ml_features processing
- Consider batch processing instead of all 273 players at once

## Testing & Validation

### How to Test Worker Fix
```bash
# Clear cache and verify feature loading
1. Restart worker
2. Check logs for "Auto-detected feature version"
3. Verify "Batch loaded features for N/N players" (not 0/N)
```

### How to Test Phase 4 Fix
```bash
# Verify v2_37features generation
1. Trigger Phase 4 for a test date
2. Check feature_version in ml_feature_store_v2
3. Verify feature_count = 37 (not 39)
```

## References

### Related Sessions
- Session 128B: Added breakout classifier (v2_39features)
- Session 130: Deployment drift investigation

### Key Files
- `predictions/worker/data_loaders.py` (feature cache)
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (feature generation)
- `predictions/coordinator/player_loader.py` (line loading performance issue)

### Useful Queries
```sql
-- Check feature versions by date
SELECT game_date, feature_version, COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-04'
GROUP BY game_date, feature_version
ORDER BY game_date DESC;

-- Check prediction counts
SELECT game_date, COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-04'
GROUP BY game_date
ORDER BY game_date DESC;
```

## Lessons Learned

1. **Singleton caches need invalidation** - Feature version cache persisted stale data
2. **Feature evolution needs migration plan** - Adding features broke models
3. **Deploy after code changes** - Session 130 had fixes but not deployed
4. **Test with representative data** - v2_39features worked in dev but broke in prod

---

**Session End:** Phase 4 regeneration incomplete due to service issues
**Next Session:** Debug Phase 4 timeouts and complete Feb 5 predictions
**Urgency:** HIGH - 0 predictions for Feb 5 games
