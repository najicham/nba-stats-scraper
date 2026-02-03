# Session 102 Handoff: Model Bias Investigation

**Date:** 2026-02-03
**Priority:** P0 - Model producing systematically wrong predictions
**Status:** Infrastructure fixed, model bias needs resolution

---

## Executive Summary

We discovered that our CatBoost V9 model has **severe regression-to-mean bias**:
- Star players under-predicted by ~9 points
- Bench players over-predicted by ~6 points
- Feb 2 high-edge picks went **0/7 (0% hit rate)**
- "High edge" is actually model error, not genuine insight

### What Was Fixed (Session 102)
- ✅ Write-time edge filter removed (all predictions now stored)
- ✅ `is_actionable` filters added (low_edge, star_under_bias)
- ✅ Coordinator and Worker deployed with fixes

### What Still Needs Fixing
- ❌ The model itself still has tier bias
- ❌ Need V10 with debiasing features or recalibration

---

## Your Mission

1. **Verify the model bias** using the validation queries below
2. **Test a fix** using the experiment skill (`/model-experiment`)
3. **Regenerate Feb 2 predictions** with correct features to measure impact
4. **Deploy a fix** if results improve

---

## Key Project Documents

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md` | Full bias analysis |
| `docs/08-projects/current/feature-mismatch-investigation/LONG-TERM-SOLUTION.md` | Architecture proposal |
| `docs/08-projects/current/feature-mismatch-investigation/SESSION-101-FINDINGS.md` | Feature mismatch discovery |
| `docs/09-handoff/2026-02-03-SESSION-102-HANDOFF.md` | Session 102 summary |
| `docs/09-handoff/2026-02-03-SESSION-101-HANDOFF.md` | Session 101 summary |

---

## The Bias Problem

### Current Model Performance by Player Tier

```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as avg_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1
```

**Expected Results (current broken state):**

| Tier | Model Pred | Actual | Bias |
|------|------------|--------|------|
| Stars (25+) | 21.1 | 30.4 | **-9.3** |
| Starters (15-24) | 15.9 | 18.7 | **-2.8** |
| Role (5-14) | 11.0 | 9.5 | +1.5 |
| Bench (<5) | 7.8 | 2.2 | **+5.6** |

**Target after fix:** Bias < 2 pts for all tiers

---

## Training Data Quality Check

Before training new models, verify data quality:

```bash
# Check feature store completeness
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(feature_quality_score >= 80) as high_quality,
  COUNTIF(feature_quality_score < 50) as low_quality,
  MIN(game_date) as min_date,
  MAX(game_date) as max_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'"
```

**Current Status (as of Session 102):**
- 23,962 records
- Average quality: 81.9%
- Date range: 2025-11-04 to 2026-02-03

```bash
# Check actual points distribution for training
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN points >= 25 THEN 'Stars (25+)'
    WHEN points >= 15 THEN 'Starters (15-24)'
    WHEN points >= 5 THEN 'Role (5-14)'
    ELSE 'Bench (<5)'
  END as tier,
  COUNT(*) as games,
  ROUND(AVG(points), 1) as avg_points
FROM nba_analytics.player_game_summary
WHERE game_date >= '2025-11-01'
  AND minutes_played > 0
GROUP BY 1
ORDER BY 1"
```

---

## Fix Options

### Option A: Post-Prediction Recalibration (Quick, Temporary)

Add tier-based adjustment in `predictions/worker/worker.py`:

```python
def recalibrate_prediction(predicted_points: float, features: dict) -> float:
    """Adjust for regression-to-mean bias."""
    pts_avg_season = features.get('points_avg_season', predicted_points)

    if pts_avg_season >= 25:  # Star tier
        adjustment = 6.0
    elif pts_avg_season >= 15:  # Starter tier
        adjustment = 2.0
    elif pts_avg_season >= 8:  # Role tier
        adjustment = 0.0
    else:  # Bench tier
        adjustment = -4.0

    return predicted_points + adjustment
```

**Pros:** Quick to implement
**Cons:** Band-aid fix, doesn't address root cause

### Option B: Retrain V10 with Tier Features (Better)

Add explicit tier features to help model understand player scoring levels:

```python
NEW_FEATURES = [
    'player_tier',  # Categorical: 1=star, 2=starter, 3=role, 4=bench
    'scoring_percentile',  # Player's scoring rank (0-100)
    'distance_from_season_avg',  # How current form differs from season
]
```

**Command to test:**
```bash
# First, modify ml/experiments/quick_retrain.py to include tier features
# Then run:
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V10_TIER_DEBIAS" \
    --train-start 2025-11-02 \
    --train-end 2026-02-02 \
    --hypothesis "Add tier features to reduce regression-to-mean"
```

### Option C: Quantile Regression (Long-term Best)

Change loss function to predict median instead of mean:

```python
model = cb.CatBoostRegressor(
    loss_function='Quantile:alpha=0.5',  # Median regression
)
```

---

## Testing with Experiment Skill

### Run an Experiment

```bash
# Default experiment (baseline)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "BASELINE_CHECK" \
    --train-start 2025-11-02 \
    --train-end 2026-01-25 \
    --eval-start 2026-01-26 \
    --eval-end 2026-02-02

# With custom hypothesis
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V10_TEST" \
    --hypothesis "Testing tier debiasing features" \
    --train-days 90 \
    --eval-days 7
```

### What to Compare

| Metric | Current V9 | Target |
|--------|------------|--------|
| MAE | ~5.3 | < 5.0 |
| Star tier bias | -9.3 pts | < 2 pts |
| Bench tier bias | +5.6 pts | < 2 pts |
| High-edge hit rate | ~40% | > 65% |
| OVER/UNDER balance | 22% OVER | 40-60% OVER |

---

## Regenerate Feb 2 Predictions

To see if correct features improve predictions, regenerate Feb 2:

```bash
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

# Regenerate Feb 2 with correct features
curl -X POST "${COORDINATOR_URL}/regenerate-with-supersede" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-02", "reason": "model_bias_investigation"}'
```

Then compare hit rates:

```sql
-- Compare old (superseded) vs new predictions for Feb 2
SELECT
  CASE WHEN p.superseded IS TRUE THEN 'Old (superseded)' ELSE 'New' END as version,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(a.prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(p.feature_quality_score), 1) as avg_quality
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date
  AND p.system_id = a.system_id
WHERE p.game_date = '2026-02-02'
  AND p.system_id = 'catboost_v9'
GROUP BY 1
```

---

## Validation Queries

### Check Model Bias by Tier
```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars'
    WHEN actual_points >= 15 THEN '2_Starters'
    WHEN actual_points >= 5 THEN '3_Role'
    ELSE '4_Bench'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(predicted_points), 1) as model_pred,
  ROUND(AVG(actual_points), 1) as actual,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1 ORDER BY 1
```

### Check High-Edge Hit Rate
```sql
SELECT
  game_date,
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge_picks,
  ROUND(100.0 * COUNTIF(
    ABS(predicted_points - line_value) >= 5 AND prediction_correct
  ) / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 5), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC
```

### Check OVER/UNDER Balance
```sql
SELECT
  game_date,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND current_points_line IS NOT NULL
  AND superseded IS NOT TRUE
GROUP BY 1 ORDER BY 1 DESC
```

---

## Key Files to Modify

| File | Purpose |
|------|---------|
| `predictions/worker/worker.py` | Add recalibration (Option A) |
| `ml/experiments/quick_retrain.py` | Add tier features (Option B) |
| `ml/feature_engineering/feature_registry.py` | Define new features |
| `predictions/worker/prediction_systems/catboost_v9.py` | Model loading |

---

## Current State Summary

| Component | Status |
|-----------|--------|
| Edge filter in MERGE | ✅ Removed (all predictions stored) |
| is_actionable filters | ✅ Added (low_edge, star_under_bias) |
| Feature store quality | ✅ 81.9% average quality |
| Model bias | ❌ Stars under-predicted by 9 pts |
| High-edge hit rate | ❌ 0% on Feb 2, erratic overall |

---

## Recommended Approach

1. **First**: Run the bias validation queries to confirm the issue
2. **Quick win**: Add recalibration in worker.py (Option A)
3. **Regenerate Feb 2** and compare hit rates
4. **If improved**: Deploy and monitor for 2-3 days
5. **Long-term**: Train V10 with tier features (Option B)

---

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Star tier bias | -9.3 pts | < 2 pts |
| Bench tier bias | +5.6 pts | < 2 pts |
| High-edge hit rate | 0-40% | > 60% |
| OVER/UNDER balance | 22% OVER | 40-60% OVER |
| Feb 2 hit rate (regenerated) | TBD | > 55% |
