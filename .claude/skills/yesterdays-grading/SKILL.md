---
name: yesterdays-grading
description: View yesterday's prediction results with accuracy metrics
---

# Skill: Yesterday's Grading

View yesterday's prediction results with accuracy metrics.

## Trigger
- User asks about "yesterday's results", "how did we do yesterday", "grading", "yesterday's grading"
- User types `/yesterdays-grading`

## Workflow

1. Query yesterday's graded predictions from `nba_predictions.prediction_accuracy`
2. Calculate hit rate, MAE, bias
3. Break down by tier and direction
4. Show best bets performance separately
5. Display in readable format

## Summary Query

Shows results for ALL enabled models dynamically.

```sql
-- Yesterday's results for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  COUNT(*) as total_graded,
  COUNTIF(prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT model_id FROM enabled_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY system_id
```

## Best Bets Grading (Most Important)

The metric that matters most — how did the signal-filtered best bets do?

```sql
-- Yesterday's best bets results
SELECT
  bb.system_id,
  bb.player_lookup,
  bb.recommendation,
  ROUND(bb.edge, 1) as edge,
  bb.signal_count,
  bb.signal_rescued,
  bb.rescue_signal,
  pa.prediction_correct as hit,
  ROUND(pa.actual_points, 1) as actual,
  ROUND(pa.line_value, 1) as line
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
  AND pa.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
WHERE bb.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
ORDER BY pa.prediction_correct DESC, bb.edge DESC
```

**Note:** If `signal_rescued = TRUE`, highlight that pick — it bypassed edge floor via signal. Track rescued vs normal HR separately.

## By Direction

```sql
-- By direction for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  recommendation as direction,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT model_id FROM enabled_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, direction
ORDER BY system_id, direction
```

## By Tier Query

```sql
-- By tier for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  CASE
    WHEN line_value >= 22 THEN 'Star'
    WHEN line_value >= 14 THEN 'Starter'
    WHEN line_value >= 6 THEN 'Rotation'
    ELSE 'Bench'
  END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT model_id FROM enabled_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, tier
ORDER BY system_id, tier
```

## By Edge Band

```sql
-- By edge band (most relevant for best bets)
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  CASE
    WHEN ABS(predicted_points - line_value) >= 7 THEN 'Edge 7+'
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'Edge 5-7'
    WHEN ABS(predicted_points - line_value) >= 3 THEN 'Edge 3-5'
    ELSE 'Edge <3'
  END as edge_band,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT model_id FROM enabled_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, edge_band
ORDER BY system_id, edge_band
```

## Output Format

```
Yesterday's Results (2026-03-02)
================================

Best Bets: 5/7 (71.4%) -- THE KEY METRIC
  OVER: 3/4 (75.0%) | UNDER: 2/3 (66.7%)

Model Performance (all predictions):
| Model                          | Graded | HR    | MAE  | Bias  |
|--------------------------------|--------|-------|------|-------|
| catboost_v12_noveg_train0103.. | 68     | 54.4% | 4.21 | -0.3  |
| lgbm_v12_noveg_train0103..    | 65     | 52.3% | 4.45 | +0.2  |

By Tier (catboost_v12_noveg_train0103..):
| Tier     | Bets | HR    | Bias  |
|----------|------|-------|-------|
| Star     | 12   | 58.3% | -1.2  |
| Starter  | 24   | 54.2% | -0.5  |
| Rotation | 22   | 54.5% | -0.8  |
| Bench    | 10   | 50.0% | +0.3  |
```

## Parameters

- `date`: Specific date to check (default: yesterday)
- `model`: Filter to a specific model (default: all enabled)
