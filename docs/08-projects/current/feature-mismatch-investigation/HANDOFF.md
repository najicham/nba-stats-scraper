# Feature Mismatch Investigation - Handoff for Next Session

**Date:** 2026-02-03
**Priority:** P0 - Critical
**Estimated Effort:** 2-4 hours investigation + fix

---

## Your Mission

Find and fix why the prediction worker is using **wrong feature values** that don't match the ML Feature Store. This is causing predictions to be 6-8 points too low.

---

## Quick Context (Read First)

1. **Read the problem definition:** `docs/08-projects/current/feature-mismatch-investigation/PROBLEM-DEFINITION.md`

2. **Key finding:** Predictions show `pts_avg_5 = 12.8` but feature store has `pts_avg_5 = 24.2`

3. **The 65.46 quality score in predictions doesn't exist in the feature store** - it came from somewhere else

---

## Investigation Steps

### Step 1: Trace the Feature Loading Path

Start from where predictions are made and trace backward:

```bash
# Find where features are loaded in worker
grep -n "load_features\|features.*=.*data_loader" predictions/worker/worker.py | head -20

# Check the load_features function
grep -A50 "def load_features" predictions/worker/data_loaders.py | head -60
```

**Key file:** `predictions/worker/worker.py` line ~794:
```python
features = data_loader.load_features(player_lookup, game_date)
```

### Step 2: Check for Alternative Feature Sources

The coordinator is 109KB and player_loader is 66KB - they might have feature computation:

```bash
# Check coordinator for feature handling
grep -rn "feature\|points_avg\|quality_score" predictions/coordinator/coordinator.py | head -40

# Check player_loader
grep -rn "feature\|points_avg" predictions/coordinator/player_loader.py | head -40
```

### Step 3: Search for Fallback Computation

Look for code that computes features when the store returns empty:

```bash
# Search for fallback patterns
grep -rn "fallback\|default.*feature\|compute.*feature" predictions/ --include="*.py" | head -30

# Search for quality score calculation
grep -rn "65\|quality.*score.*=" predictions/ --include="*.py" | head -30
```

### Step 4: Check Cache Behavior

The worker has a features cache - check if stale data could be served:

```bash
# Check cache implementation
grep -n "cache\|Cache\|TTL" predictions/worker/data_loaders.py | head -30
```

Key cache settings (line 46-49):
```python
FEATURES_CACHE_TTL_SAME_DAY = 300  # 5 minutes
FEATURES_CACHE_TTL_HISTORICAL = 3600  # 1 hour
```

### Step 5: Verify Query Parameters

Check if the worker uses the same `feature_version` as the store:

```bash
# Check what feature_version is used
grep -rn "feature_version\|v2_37features" predictions/worker/ --include="*.py" | head -20

# Check what's in the store
bq query --use_legacy_sql=false "
SELECT DISTINCT feature_version FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-03'"
```

---

## Key Files to Study

### 1. Data Loading
- `predictions/worker/data_loaders.py` - Feature loading from BigQuery
  - Line 137: `load_features()` function
  - Line 794: `load_features_batch_for_date()` - batch query
  - Line 839: SQL query for features

### 2. Worker Logic
- `predictions/worker/worker.py` - Main prediction logic
  - Line 794: Where features are loaded
  - Line 1761-1789: Where `critical_features` is built

### 3. Coordinator (Possibly)
- `predictions/coordinator/coordinator.py` - 109KB, might have feature logic
- `predictions/coordinator/player_loader.py` - 66KB, might pre-load data

### 4. Feature Store Processing
- `data_processors/precompute/ml_feature_store/feature_extractor.py` - How features are computed
- `data_processors/precompute/ml_feature_store/quality_scorer.py` - Quality score formula

---

## Related Handoffs

Read these for context on recent changes:

1. **Session 99** (`docs/09-handoff/2026-02-03-SESSION-99-HANDOFF.md`)
   - Fixed feature store quality from 65% to 85%
   - Added fallback queries for upcoming games
   - Key insight: Phase 4 data only exists for completed games

2. **Session 98** (`docs/09-handoff/2026-02-03-SESSION-98-HANDOFF.md`)
   - Phase 3 completion tracking issues
   - Pub/Sub trigger investigation

3. **Session 97** (`docs/09-handoff/2026-02-03-SESSION-97-HANDOFF.md`)
   - Model revert details
   - Added feature_quality_score to predictions

---

## Test Queries

### Verify Feature Store Has Correct Data
```sql
SELECT
    player_lookup,
    features[OFFSET(0)] as pts_avg_5,
    features[OFFSET(1)] as pts_avg_10,
    feature_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'laurimarkkanen' AND game_date = '2026-02-03'
```
Expected: pts_avg_5 = 24.2, quality = 87.59

### Check Prediction Critical Features
```sql
SELECT
    player_lookup,
    predicted_points,
    critical_features
FROM nba_predictions.player_prop_predictions
WHERE player_lookup = 'laurimarkkanen'
  AND game_date = '2026-02-03' AND system_id = 'catboost_v9'
```
Observed: pts_avg_last_5 = 12.8, quality = 65.46 (WRONG!)

### Check All Quality Scores in Feature Store
```sql
SELECT feature_quality_score, COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-03'
GROUP BY 1 ORDER BY 1
```
Note: 65.46 does NOT appear in this list!

---

## Hypotheses to Test

### Most Likely: Coordinator Pre-computes Features

The coordinator (109KB) might have its own feature computation that runs BEFORE the feature store is populated, and those computed values are used instead of fresh store data.

**Search:**
```bash
grep -rn "compute\|calculate\|rolling\|average" predictions/coordinator/*.py | head -40
```

### Alternative: Stale Cache

The feature cache might have served old data from before Session 99 fix.

**Check:**
```python
# In data_loaders.py, look for cache clearing logic
# The cache should be invalidated when new data is available
```

### Alternative: Different feature_version Parameter

Worker might query with `v2_33features` but store has `v2_37features`.

**Check:**
```bash
grep -rn "v2_33\|v2_37\|feature_version" predictions/worker/ --include="*.py"
```

---

## When You Find the Root Cause

### If it's a coordinator issue:
1. Update coordinator to use feature store instead of computing
2. Redeploy coordinator
3. Verify with new prediction run

### If it's a cache issue:
1. Add cache invalidation when feature store is updated
2. Consider clearing cache on worker startup
3. Redeploy worker

### If it's a query parameter issue:
1. Fix the `feature_version` parameter
2. Verify query returns correct data
3. Redeploy worker

---

## Immediate Workaround

If you need to re-run predictions for tonight's games:

```bash
# Trigger new predictions
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/trigger" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-03", "force_refresh": true}'
```

---

## Success Criteria

1. Predictions use feature values matching `ml_feature_store_v2`
2. `critical_features.feature_quality_score` matches feature store (87.59, not 65.46)
3. Predicted points within reasonable range of player averages
4. Root cause documented and prevention mechanism added

---

## Contact

If you need more context, the conversation that discovered this issue is documented in the PROBLEM-DEFINITION.md file.

Good luck!
