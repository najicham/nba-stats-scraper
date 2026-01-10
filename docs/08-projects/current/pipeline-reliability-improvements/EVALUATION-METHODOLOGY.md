# Prediction Evaluation Methodology

**Created:** 2026-01-09
**Last Updated:** 2026-01-09

## Overview

This document defines the correct methodology for evaluating NBA points prediction performance. There are TWO fundamentally different metrics that must be evaluated separately.

## Two Evaluation Frameworks

### Framework A: Points Prediction Accuracy (ALL Games)

**Question:** How well does the model predict actual points scored?

**Use Case:** ML model quality assessment, model comparison, feature engineering feedback

**Data Filter:** ALL predictions (regardless of `has_prop_line`)

```sql
-- Points Prediction Accuracy Query
SELECT
  system_id,
  COUNT(*) as total_predictions,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(SQRT(AVG(POWER(predicted_points - actual_points, 2))), 2) as rmse,
  ROUND(AVG(predicted_points - actual_points), 2) as bias,
  ROUND(COUNTIF(ABS(predicted_points - actual_points) <= 3) / COUNT(*) * 100, 1) as within_3_pct,
  ROUND(COUNTIF(ABS(predicted_points - actual_points) <= 5) / COUNT(*) * 100, 1) as within_5_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE actual_points IS NOT NULL
-- NO FILTER on has_prop_line - use ALL predictions
GROUP BY 1
```

### Framework B: Betting Performance (ONLY Real Prop Lines)

**Question:** How often does the OVER/UNDER recommendation beat Vegas?

**Use Case:** Betting ROI evaluation, actual betting performance

**Data Filter:** ONLY predictions with `has_prop_line = true` AND `recommendation IN ('OVER', 'UNDER')`

```sql
-- Betting Performance Query (CORRECT)
SELECT
  system_id,
  COUNT(*) as total_bets,
  COUNTIF(prediction_correct = true) as wins,
  COUNTIF(prediction_correct = false) as losses,
  ROUND(COUNTIF(prediction_correct = true) /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0) * 100, 1) as hit_rate,
  -- ROI assuming -110 juice
  ROUND((COUNTIF(prediction_correct = true) * 91.0 -
         COUNTIF(prediction_correct = false) * 100.0) /
        NULLIF(COUNT(*) * 110.0, 0) * 100, 1) as roi_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE has_prop_line = true                    -- CRITICAL: Only real Vegas lines
  AND recommendation IN ('OVER', 'UNDER')     -- Only actionable bets
  AND prediction_correct IS NOT NULL          -- Game completed
GROUP BY 1
```

## Critical Data Quality Notes

### The `has_prop_line` Flag

| Value | Meaning | Use in Training | Use in Betting Eval |
|-------|---------|-----------------|---------------------|
| `true` | Real Vegas prop line available | YES | YES |
| `false` | Estimated line (player average) | YES | NO |

### The `recommendation` Field

| Value | Meaning | Evaluable for Betting? |
|-------|---------|----------------------|
| `OVER` | Predicted points > line | YES |
| `UNDER` | Predicted points < line | YES |
| `PASS` | Prediction within threshold | NO |
| `NO_LINE` | No real prop line available | NO |

### Line Source Tracking

| Field | Description |
|-------|-------------|
| `line_source` | `'ACTUAL_PROP'` or `'ESTIMATED_AVG'` |
| `estimated_line_value` | The estimated line when no real prop |
| `current_points_line` | The actual prop line (NULL when no line) |

## Historical Data Warning

**IMPORTANT:** Historical predictions (2021-2024) in some systems were backfilled with default line values (e.g., line=20). These should NOT be used for betting performance evaluation.

To identify valid data:
```sql
-- Check for default line values
SELECT
  COUNT(*) as total,
  COUNTIF(line_value = 20) as default_lines,
  COUNTIF(line_value != 20 AND line_value IS NOT NULL) as real_lines
FROM prediction_accuracy
```

## Verified Performance Numbers (CatBoost V8)

As of 2026-01-09, verified with REAL Vegas prop lines:

| Season | Picks | Wins | Losses | Hit Rate | ROI |
|--------|-------|------|--------|----------|-----|
| 2021-22 | 10,643 | 8,137 | 2,500 | **76.5%** | +46.1% |
| 2022-23 | 10,613 | 8,051 | 2,550 | **75.9%** | +45.1% |
| 2023-24 | 11,415 | 8,327 | 3,063 | **73.1%** | +39.6% |
| 2024-25 | 13,373 | 9,893 | 3,428 | **74.3%** | +41.8% |
| 2025-26 | 1,626 | 1,167 | 454 | **72.0%** | +37.5% |

**Data Verification:**
- Line values range from 0.5-39 (realistic distribution)
- Features computed using only pre-game data (`game_date < prediction_date`)
- No data leakage detected (actual points not in features)

## Training Data Policy

### For Points Prediction Models (e.g., CatBoost)

**USE ALL GAMES** regardless of `has_prop_line`

Rationale:
- Model predicts POINTS, not over/under
- Target is `actual_points` - independent of betting line availability
- More training data = better model

### For Confidence Calibration

**USE ONLY `has_prop_line = true`**

Rationale:
- Need real lines to evaluate "does 70% confidence = 70% hit rate"
- Estimated lines don't reflect market efficiency

## Query Templates

### Recent Performance (Last N Days)
```sql
WITH predictions_with_actuals AS (
  SELECT
    p.game_date,
    p.recommendation,
    a.points as actual_points,
    CASE
      WHEN a.points > p.current_points_line THEN 'OVER'
      WHEN a.points < p.current_points_line THEN 'UNDER'
      ELSE 'PUSH'
    END as actual_outcome
  FROM `nba_predictions.player_prop_predictions` p
  JOIN `nba_analytics.player_game_summary` a
    ON p.player_lookup = a.player_lookup
    AND p.game_date = a.game_date
  WHERE p.system_id = 'catboost_v8'
    AND p.has_prop_line = true
    AND p.recommendation IN ('OVER', 'UNDER')
    AND p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
)
SELECT
  COUNT(*) as picks,
  COUNTIF(recommendation = actual_outcome) as wins,
  ROUND(COUNTIF(recommendation = actual_outcome) /
        COUNTIF(actual_outcome != 'PUSH') * 100, 1) as hit_rate
FROM predictions_with_actuals
```

### Performance by Confidence Tier
```sql
-- Group by confidence and compare hit rates
SELECT
  CASE
    WHEN confidence_score >= 0.90 THEN '90+ (Very High)'
    WHEN confidence_score >= 0.85 THEN '85-90 (High)'
    ELSE '< 85 (Medium)'
  END as confidence_tier,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_correct) /
        COUNTIF(prediction_correct IS NOT NULL) * 100, 1) as hit_rate
FROM prediction_accuracy
WHERE has_prop_line = true
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
ORDER BY 1 DESC
```

## Summary

1. **Points accuracy** → Use ALL data
2. **Betting performance** → Use ONLY `has_prop_line = true` AND `recommendation IN ('OVER', 'UNDER')`
3. **Training data** → Use ALL games for points models
4. **Always verify** → Check for default line values (line=20) in historical data
