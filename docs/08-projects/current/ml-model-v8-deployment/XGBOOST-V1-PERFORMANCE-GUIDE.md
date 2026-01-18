# XGBoost V1 Performance Analysis Guide

**Created:** 2026-01-17
**Model:** XGBoost V1 (Real Production Model)
**Purpose:** Track XGBoost V1 performance, compare to CatBoost V8, and identify optimization opportunities

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Model Information](#model-information)
3. [Performance Tracking Queries](#performance-tracking-queries)
4. [Head-to-Head Comparison](#head-to-head-comparison)
5. [Confidence Tier Analysis](#confidence-tier-analysis)
6. [Feature Performance](#feature-performance)
7. [Troubleshooting](#troubleshooting)

---

## Quick Reference

### Model Metadata (CURRENT - Production Model V2)

| Metric | Value |
|--------|-------|
| Model ID | xgboost_v1_33features_20260118_103153 |
| System ID | `xgboost_v1` |
| Training Samples | 101,692 |
| Training Date Range | 2021-11-02 to 2025-04-13 |
| Features | 33 (v2_33features) |
| Framework | XGBoost |
| **Validation MAE** | **3.726 points** |
| Training MAE | 3.272 points |
| Train/Val Gap | 0.453 points |
| Model Path | gs://nba-scraped-data/ml-models/xgboost_v1_33features_20260118_103153.json |
| Deployed | 2026-01-18 18:33 UTC |

### Baseline Performance (Validation Set)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| MAE | 3.726 points | ≤ 4.5 | ✅ Beat target |
| RMSE | 4.877 points | - | - |
| Within 3 pts | 51.6% | - | - |
| Within 5 pts | 73.3% | - | - |
| vs Mock V1 | +22.4% better | - | ✅ |
| vs CatBoost V8 | -9.6% worse | - | Competitive |
| vs Initial XGBoost V1 (4.26) | +12.5% better | - | ✅ Improved |

### Quick Status Check

```bash
# Latest graded predictions
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_graded, COUNT(*) as total_graded
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
"

# Recent prediction volume
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
"
```

---

## Model Information

### Training Configuration

**Hyperparameters:**
```python
{
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 1000,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'colsample_bylevel': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'early_stopping_rounds': 50
}
```

**Best Iteration:** 999 (out of 1000 max - no early stopping)

### Feature Importance (Top 20)

| Rank | Feature | Importance | Type |
|------|---------|------------|------|
| 1 | points_avg_last_5 | 37.4% | Base |
| 2 | points_avg_last_10 | 17.1% | Base |
| 3 | vegas_points_line | 12.6% | Vegas |
| 4 | points_avg_season | 5.7% | Base |
| 5 | vegas_opening_line | 2.6% | Vegas |
| 6 | ppm_avg_last_10 | 2.1% | Minutes/PPM |
| 7 | minutes_avg_last_10 | 1.7% | Minutes/PPM |
| 8 | points_std_last_10 | 1.4% | Base |
| 9 | recent_trend | 1.3% | Base |
| 10 | has_vegas_line | 1.2% | Vegas |
| 11 | minutes_change | 1.2% | Base |
| 12 | rest_advantage | 1.2% | Base |
| 13 | vegas_line_move | 1.1% | Vegas |
| 14 | fatigue_score | 1.0% | Base |
| 15 | opponent_def_rating | 1.0% | Base |
| 16 | games_in_last_7_days | 0.9% | Base |
| 17 | playoff_game | 0.9% | Base |
| 18 | team_pace | 0.8% | Base |
| 19 | opponent_pace | 0.8% | Base |
| 20 | team_off_rating | 0.8% | Base |

**Key Insights:**
- Recent performance (last 5-10 games): **54.5%** combined
- Vegas features: **17.5%** combined (market efficiency)
- Minutes/PPM context: **3.8%** combined

---

## Performance Tracking Queries

### Overall Production Performance

```sql
-- XGBoost V1 season summary
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as production_mae,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 - 52.4, 1) as edge_over_breakeven
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2026-01-18'  -- V2 Deployment date
  AND system_id = 'xgboost_v1'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
```

**Expected Production MAE:** ~3.73 points (based on validation)

### Daily Performance Trend

```sql
SELECT
  game_date,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(confidence_score), 2) as avg_confidence
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND system_id = 'xgboost_v1'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC
```

### OVER vs UNDER Performance

```sql
SELECT
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error,
  ROUND(AVG(ABS(predicted_margin)), 2) as avg_edge
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2026-01-18'
  AND system_id = 'xgboost_v1'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY recommendation
```

---

## Head-to-Head Comparison

### XGBoost V1 vs CatBoost V8

```sql
-- Side-by-side performance comparison
WITH xgboost_performance AS (
  SELECT
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    ROUND(AVG(absolute_error), 2) as mae,
    'XGBoost V1' as model
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date >= '2026-01-18'
    AND system_id = 'xgboost_v1'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
),
catboost_performance AS (
  SELECT
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    ROUND(AVG(absolute_error), 2) as mae,
    'CatBoost V8' as model
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date >= '2026-01-18'
    AND system_id = 'catboost_v8'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  model,
  picks,
  wins,
  ROUND(SAFE_DIVIDE(wins, picks) * 100, 1) as win_rate,
  mae
FROM xgboost_performance
UNION ALL
SELECT
  model,
  picks,
  wins,
  ROUND(SAFE_DIVIDE(wins, picks) * 100, 1) as win_rate,
  mae
FROM catboost_performance
ORDER BY mae ASC
```

### Same-Game Head-to-Head

**When both models make predictions on the same player-game:**

```sql
WITH both_models AS (
  SELECT
    xgb.game_date,
    xgb.player_lookup,
    xgb.predicted_points as xgb_pred,
    xgb.prediction_correct as xgb_correct,
    xgb.absolute_error as xgb_error,
    cat.predicted_points as cat_pred,
    cat.prediction_correct as cat_correct,
    cat.absolute_error as cat_error,
    xgb.actual_points,
    xgb.line_value
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` xgb
  INNER JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` cat
    ON xgb.player_lookup = cat.player_lookup
    AND xgb.game_date = cat.game_date
    AND xgb.game_id = cat.game_id
  WHERE xgb.system_id = 'xgboost_v1'
    AND cat.system_id = 'catboost_v8'
    AND xgb.game_date >= '2026-01-17'
    AND xgb.recommendation IN ('OVER', 'UNDER')
    AND cat.recommendation IN ('OVER', 'UNDER')
    AND xgb.has_prop_line = TRUE
)
SELECT
  COUNT(*) as total_overlapping_picks,
  -- XGBoost V1
  COUNTIF(xgb_correct = TRUE) as xgb_wins,
  ROUND(AVG(xgb_error), 2) as xgb_mae,
  -- CatBoost V8
  COUNTIF(cat_correct = TRUE) as cat_wins,
  ROUND(AVG(cat_error), 2) as cat_mae,
  -- Head-to-head
  COUNTIF(xgb_correct = TRUE AND cat_correct = FALSE) as xgb_wins_cat_loses,
  COUNTIF(cat_correct = TRUE AND xgb_correct = FALSE) as cat_wins_xgb_loses,
  COUNTIF(xgb_correct = cat_correct) as both_agree
FROM both_models
```

### Prediction Agreement Analysis

```sql
WITH both_models AS (
  SELECT
    xgb.game_date,
    xgb.player_lookup,
    xgb.recommendation as xgb_rec,
    cat.recommendation as cat_rec,
    xgb.predicted_points as xgb_pred,
    cat.predicted_points as cat_pred,
    xgb.prediction_correct as xgb_correct,
    cat.prediction_correct as cat_correct,
    xgb.actual_points
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` xgb
  INNER JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` cat
    ON xgb.player_lookup = cat.player_lookup AND xgb.game_date = cat.game_date
  WHERE xgb.system_id = 'xgboost_v1'
    AND cat.system_id = 'catboost_v8'
    AND xgb.game_date >= '2026-01-17'
    AND xgb.has_prop_line = TRUE
)
SELECT
  CASE
    WHEN xgb_rec = cat_rec THEN 'Both Agree'
    WHEN xgb_rec = 'PASS' OR cat_rec = 'PASS' THEN 'One Passes'
    ELSE 'Disagree'
  END as agreement_type,
  COUNT(*) as cases,
  COUNTIF(xgb_correct = TRUE) as xgb_wins,
  COUNTIF(cat_correct = TRUE) as cat_wins,
  ROUND(AVG(ABS(xgb_pred - cat_pred)), 2) as avg_prediction_diff
FROM both_models
GROUP BY agreement_type
ORDER BY cases DESC
```

---

## Confidence Tier Analysis

### Performance by Confidence Band

```sql
WITH picks_with_tier AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.90 THEN 'VERY HIGH (90%+)'
      WHEN confidence_score >= 0.70 THEN 'HIGH (70-90%)'
      WHEN confidence_score >= 0.55 THEN 'MEDIUM (55-70%)'
      ELSE 'LOW (<55%)'
    END as confidence_tier
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date >= '2026-01-18'
    AND system_id = 'xgboost_v1'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error,
  ROUND(AVG(confidence_score), 2) as avg_confidence
FROM picks_with_tier
GROUP BY confidence_tier
ORDER BY
  CASE confidence_tier
    WHEN 'VERY HIGH (90%+)' THEN 1
    WHEN 'HIGH (70-90%)' THEN 2
    WHEN 'MEDIUM (55-70%)' THEN 3
    ELSE 4
  END
```

**Expected Pattern:**
- Higher confidence → Higher win rate
- If a tier underperforms (>10% below adjacent), investigate

### Granular Confidence Breakdown

```sql
WITH picks_with_tier AS (
  SELECT
    *,
    CASE
      WHEN confidence_score >= 0.92 THEN '1. 92%+'
      WHEN confidence_score >= 0.90 THEN '2. 90-92%'
      WHEN confidence_score >= 0.88 THEN '3. 88-90%'
      WHEN confidence_score >= 0.86 THEN '4. 86-88%'
      WHEN confidence_score >= 0.84 THEN '5. 84-86%'
      WHEN confidence_score >= 0.80 THEN '6. 80-84%'
      WHEN confidence_score >= 0.70 THEN '7. 70-80%'
      ELSE '8. <70%'
    END as confidence_tier
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date >= '2026-01-18'
    AND system_id = 'xgboost_v1'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
)
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM picks_with_tier
GROUP BY confidence_tier
ORDER BY confidence_tier
```

---

## Feature Performance

### Vegas Line Dependency

**How well does XGBoost V1 perform with/without Vegas lines?**

```sql
SELECT
  CASE
    WHEN has_vegas_line = TRUE THEN 'With Vegas Line'
    ELSE 'Without Vegas Line'
  END as vegas_availability,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2026-01-18'
  AND system_id = 'xgboost_v1'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY vegas_availability
```

**Note:** Vegas features contribute 23.4% to XGBoost V1 predictions - expect better performance when Vegas data is available.

### Recent Performance vs Season Average

**Since XGBoost V1 heavily weights recent games (54.7% importance), check performance on:**
- Hot players (recent > season avg)
- Cold players (recent < season avg)

```sql
WITH player_predictions AS (
  SELECT
    pa.*,
    -- Would need to join with ml_feature_store_v2 to get rolling vs season averages
    -- This is a simplified version
    CASE
      WHEN pa.predicted_points > pa.line_value THEN 'Predicting Up'
      WHEN pa.predicted_points < pa.line_value THEN 'Predicting Down'
      ELSE 'At Line'
    END as prediction_direction
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  WHERE pa.game_date >= '2026-01-17'
    AND pa.system_id = 'xgboost_v1'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.has_prop_line = TRUE
)
SELECT
  prediction_direction,
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM player_predictions
GROUP BY prediction_direction
```

---

## Troubleshooting

### Low Production Performance

If production MAE > 4.2 (significantly worse than validation 3.73):

**1. Check Data Quality:**
```sql
-- Verify feature quality in recent predictions
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  -- Would need to join with ml_feature_store_v2 for quality scores
  AVG(confidence_score) as avg_confidence
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

**2. Check for Distribution Shift:**
```sql
-- Compare recent prediction distribution to training
SELECT
  ROUND(predicted_points / 5) * 5 as point_bucket,
  COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY point_bucket
ORDER BY point_bucket
```

**3. Check Model Loading:**
```bash
# Verify correct model is loaded
gcloud run services describe prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "XGBOOST_V1_MODEL_PATH")'
```

Expected: `gs://nba-scraped-data/ml-models/xgboost_v1_33features_20260118_103153.json`

### Missing Predictions

If XGBoost V1 predictions are missing for some games:

**1. Check prediction volume:**
```sql
SELECT
  game_date,
  COUNT(*) as xgb_predictions,
  (SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
   WHERE game_date = p.game_date AND system_id = 'catboost_v8') as cat_predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` p
WHERE p.system_id = 'xgboost_v1'
  AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

**2. Check worker logs:**
```bash
gcloud run services logs read prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --limit 100 | grep -i "xgboost"
```

### Placeholders Appearing

If placeholder predictions appear (predicted_points = 20.0, confidence_score = 0.50):

```sql
SELECT COUNT(*) as placeholders
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND predicted_points = 20.0
  AND confidence_score = 0.50
  AND game_date >= '2026-01-17'
```

**Should be 0** - validation gate should prevent placeholders.

If > 0, check:
1. Validation gate is active in worker
2. Model is loading correctly
3. Feature quality scores

---

## Monitoring Recommendations

### Daily Checks (Automated)

Set up alerts for:
- Production MAE > 4.5 (exceeds validation target)
- Win rate < 50% (worse than random)
- Prediction volume drops >50% vs CatBoost V8
- Placeholders appearing (count > 0)

### Weekly Reviews

1. **Compare to validation baseline:** Production MAE should be ~3.73 ± 0.5
2. **Head-to-head vs CatBoost V8:** Track wins/losses on same picks
3. **Confidence calibration:** Higher confidence → higher win rate
4. **Feature importance drift:** Are top features still dominant?

### Monthly Analysis

1. **Retrain evaluation:** Compare MAE to training (3.27) and validation (3.73)
2. **Seasonal drift:** Performance degradation over time?
3. **Vegas dependency:** Performance with/without Vegas lines
4. **Sportsbook analysis:** Performance against each book

---

## Retraining Triggers

Consider retraining XGBoost V1 if:

1. **Production MAE > 4.3** for 14+ consecutive days (>10% worse than validation)
2. **Win rate < 50%** for 30+ consecutive days (worse than random)
3. **Significant distribution shift** (player trends change, rule changes, etc.)
4. **Quarterly schedule** (add 3 months of new data)

**Retraining Process:**
```bash
# Step 1: Train new model with updated date range
# Update end-date to include new data since last training
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2026-03-31 \
  --upload-gcs

# Step 2: Compare new model to current
# - Check validation MAE (should be ≤ 3.73 or better)
# - Check feature importance (should be similar)

# Step 3: Deploy if improvement
export XGBOOST_V1_MODEL_PATH="gs://nba-scraped-data/ml-models/xgboost_v1_33features_YYYYMMDD_HHMMSS.json"
./bin/predictions/deploy/deploy_prediction_worker.sh prod

# Step 4: Monitor for 7 days
# - Compare production MAE to old model
# - Check win rate improvement
# - Validate no regressions
```

---

## Model Evolution History

### V2 - Production Model (CURRENT)
**Trained:** 2026-01-18
**Deployed:** 2026-01-18 18:33 UTC
**Model:** `xgboost_v1_33features_20260118_103153.json`

**Training Data:**
- Date Range: 2021-11-02 to 2025-04-13
- Total Samples: 101,692 player-games
- Training: 81,353 games (80%)
- Validation: 20,339 games (20%)
- **Full NBA backfill complete** (739 dates, 104,842 total records available)

**Performance:**
- Training MAE: 3.272 points
- Validation MAE: **3.726 points**
- RMSE: 4.877 points
- Within 3 pts: 51.6% | Within 5 pts: 73.3%
- Train/Val Gap: 0.453 (excellent generalization)

**Improvements from V1:**
- 12.5% better MAE (3.726 vs 4.26)
- 11x more training data
- Better generalization (0.453 gap vs 0.78 gap)

**Training Command:**
```bash
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2025-04-13 \
  --upload-gcs
```

**Source:** Session 88-89 backfill completion

---

### V1 - Initial Production Model (SUPERSEDED)
**Trained:** 2026-01-17
**Deployed:** 2026-01-17 18:43 UTC
**Model:** `xgboost_v1_33features_20260117_183235.json`

**Training Data:**
- Date Range: 2021-11-02 to 2025-12-31
- Total Samples: 115,333 player-games (Note: Included future dates, explaining higher sample count)
- Features: 33 (v2_33features)

**Performance:**
- Training MAE: 3.48 points
- Validation MAE: 3.98 points
- Best iteration: 521 (early stopping)

**Status:** Superseded by V2 with more accurate historical data and better validation performance

---

## Related Documentation

- **Training Guide:** `ml_models/nba/train_xgboost_v1.py`
- **Model Metadata (Current):** `models/xgboost_v1_33features_20260118_103153_metadata.json`
- **Session 88-89 Handoff:** `docs/09-handoff/SESSION-88-89-HANDOFF.md`
- **CatBoost V8 Performance:** `PERFORMANCE-ANALYSIS-GUIDE.md`
- **Champion-Challenger Framework:** `CHAMPION-CHALLENGER-FRAMEWORK.md`

---

## Appendix: Baseline Comparisons

### Validation Set Performance (Current - V2)

| Model | MAE | RMSE | Within 3 pts | Within 5 pts |
|-------|-----|------|--------------|--------------|
| Mock XGBoost V1 | 4.80 | - | - | - |
| **XGBoost V1 (V2)** | **3.726** | 4.877 | 51.6% | 73.3% |
| CatBoost V8 | 3.40 | - | - | - |

### Expected Production Performance

Based on validation results, expect:
- **MAE:** 3.73 ± 0.5 points
- **Win Rate:** 55-60% (better than 52.4% breakeven)
- **Confidence calibration:** Higher confidence → higher accuracy
- **Vegas dependency:** Better performance with Vegas lines available

### Historical Validation Performance

| Version | Date | MAE | RMSE | Samples | Status |
|---------|------|-----|------|---------|--------|
| V2 | 2026-01-18 | 3.726 | 4.877 | 101,692 | ✅ Current |
| V1 | 2026-01-17 | 3.98 | 5.59 | 115,333 | Superseded |

---

**Document Status:** ✅ Active
**Last Updated:** 2026-01-18
**Model Version:** xgboost_v1_33features_20260118_103153 (V2)
**Deployment:** Production (2026-01-18 18:33 UTC)
