# Feature Mismatch Investigation

**Created:** 2026-02-03
**Priority:** P0 - Critical (affects prediction accuracy)
**Status:** Investigation In Progress

---

## Executive Summary

Predictions are using **wrong feature values** that don't match what's stored in the ML Feature Store. This caused Feb 2-3 predictions to have severely under-predicted values (6-8 points below Vegas lines), resulting in 0/7 high-edge hit rate on Feb 2.

---

## The Problem

### Observed Symptoms

For player `laurimarkkanen` on Feb 3, 2026:

| Source | pts_avg_5 | pts_avg_10 | quality_score |
|--------|-----------|------------|---------------|
| **Feature Store** (`ml_feature_store_v2`) | 24.2 | 25.9 | 87.59 |
| **Prediction Used** (from `critical_features`) | 12.8 | 6.4 | 65.46 |
| **Difference** | -11.4 | -19.5 | -22.13 |

The prediction used feature values that are **roughly half** of what's in the feature store.

### Impact

1. **Model predicted 15.3 points** instead of ~22-23 points
2. **Vegas line was 26.5** - model recommended UNDER
3. **All 7 high-edge picks on Feb 2 failed** (0% hit rate)
4. **100% UNDER bias** - all predictions recommending UNDER

### Timeline

```
2026-02-02 22:30:18 UTC - Feature store populated for Feb 3 (quality 87.59)
2026-02-02 23:12:42 UTC - Predictions created (quality 65.46 in critical_features)
2026-02-03 09:15:00 UTC - Session 97 model revert deployed
2026-02-03 17:45:00 UTC - Issue discovered
```

**Key Observation:** The feature store had correct data 43 minutes BEFORE predictions were made, but the predictions used completely different values.

---

## What We Know

### 1. Feature Store is Correct

Query confirms `ml_feature_store_v2` has correct data:

```sql
SELECT player_lookup, game_date, feature_quality_score,
       features[OFFSET(0)] as pts_avg_5
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'laurimarkkanen' AND game_date = '2026-02-03'
-- Returns: pts_avg_5 = 24.2, quality = 87.59
```

### 2. The 65.46 Quality Score Doesn't Exist in Feature Store

```sql
SELECT DISTINCT feature_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-03'
-- Returns: 71.38, 75.19, 82.73, 87.59 (NO 65.46!)
```

### 3. Data Loader Code Looks Correct

`predictions/worker/data_loaders.py` (line 839-860):
- Queries `ml_feature_store_v2` directly
- No fallback feature computation
- Returns None if query fails

### 4. Quality Score 65.46 Calculation

Based on `quality_scorer.py`, a 65.46 score means approximately:
- ~17 features used 'default' (40 points each)
- ~20 features used 'phase3' (87 points each)
- Formula: (17*40 + 20*87) / 37 = 65.4

This suggests the prediction worker computed features using a **fallback path** that doesn't use the feature store.

---

## What We Don't Know

### Critical Questions

1. **Where does the prediction worker get features when feature store returns None?**
   - Is there a fallback computation somewhere?
   - Is there a coordinator-level feature loading?

2. **Why did the feature store query return None/empty?**
   - Cache issue?
   - Race condition?
   - Query parameter mismatch (e.g., different `feature_version`)?

3. **Is there a separate code path for UPCOMING games vs HISTORICAL?**
   - Session 99 handoff mentions upcoming games had 65% quality before fixes
   - Maybe worker code wasn't updated to use new feature store data?

4. **Is there a caching layer that served stale data?**
   - `FEATURES_CACHE_TTL_SAME_DAY = 300` (5 minutes)
   - Could old cached data have been used?

---

## Files to Investigate

### Primary Files

| File | Why |
|------|-----|
| `predictions/worker/worker.py` | Main prediction logic, feature loading |
| `predictions/worker/data_loaders.py` | Feature loading from BigQuery |
| `predictions/coordinator/coordinator.py` | Coordinator might pre-load features |
| `predictions/coordinator/player_loader.py` | 65KB file - might have feature logic |

### Supporting Files

| File | Why |
|------|-----|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | How features are computed |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | How quality scores are calculated |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature store processing |

### Relevant Handoffs

| Document | Relevance |
|----------|-----------|
| `docs/09-handoff/2026-02-03-SESSION-99-HANDOFF.md` | Fixed feature store quality from 65% to 85% |
| `docs/09-handoff/2026-02-03-SESSION-98-HANDOFF.md` | Phase 3 completion tracking issues |
| `docs/09-handoff/2026-02-03-SESSION-97-HANDOFF.md` | Model revert and quality fields |

---

## Verification Queries

### Check Feature Store Values
```sql
SELECT player_lookup, features[OFFSET(0)] as pts_avg_5,
       features[OFFSET(1)] as pts_avg_10, feature_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'laurimarkkanen' AND game_date = '2026-02-03'
```

### Check Prediction Critical Features
```sql
SELECT player_lookup, predicted_points,
       JSON_EXTRACT(critical_features, '$.features_snapshot') as snapshot
FROM nba_predictions.player_prop_predictions
WHERE player_lookup = 'laurimarkkanen'
  AND game_date = '2026-02-03' AND system_id = 'catboost_v9'
```

### Check All Quality Scores in Feature Store
```sql
SELECT feature_quality_score, COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-03'
GROUP BY 1 ORDER BY 1
```

---

## Hypotheses to Test

### Hypothesis 1: Coordinator Pre-loads Features Differently
The coordinator might have its own feature loading that doesn't use `ml_feature_store_v2`.

**Test:** Search coordinator code for feature computation:
```bash
grep -rn "feature\|points_avg\|quality" predictions/coordinator/ --include="*.py"
```

### Hypothesis 2: Worker Has Fallback Feature Computation
When feature store query returns empty, worker computes features from raw data.

**Test:** Search for fallback computation:
```bash
grep -rn "fallback\|compute.*feature\|calculate.*feature" predictions/worker/ --include="*.py"
```

### Hypothesis 3: Cache Served Stale Data
An old cache entry with 65.46 quality was used instead of fresh data.

**Test:** Check cache invalidation logic in `data_loaders.py`

### Hypothesis 4: Query Parameter Mismatch
Worker queries with different `feature_version` than what's in the store.

**Test:** Check what `feature_version` the worker uses vs what's in the store

---

## Related Issues

1. **Model Issue (FIXED):** Feb 2 retrained model was broken - already reverted
2. **Deployment Drift (FIXED):** Services deployed with latest code
3. **Feature Store Quality (FIXED in Session 99):** Improved from 65% to 85%

This feature mismatch is a **separate issue** from the above - the feature store has correct data, but predictions aren't using it.

---

## Immediate Workaround

Re-run predictions for today's games to use correct features:

```bash
# Trigger new predictions with force refresh
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/trigger" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-03", "force_refresh": true}'
```

---

## Success Criteria

1. Predictions use features matching `ml_feature_store_v2` values
2. `critical_features.feature_quality_score` matches feature store quality
3. No more 65.46 quality scores appearing in predictions
4. Predicted points are within reasonable range of player averages (not 50% below)
