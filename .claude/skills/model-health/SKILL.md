# Skill: Model Health

Monitor model performance, detect drift, and diagnose issues.

## Trigger
- User asks about "model health", "how is the model doing", "model performance", "drift detection"
- User types `/model-health`

## Workflow

1. Run performance diagnostics via `PerformanceDiagnostics` class
2. Query rolling hit rates and metrics
3. Compare to baselines
4. Identify root cause if issues detected

## Quick Health Check Query

**IMPORTANT**: This query checks ALL active models to compare their health.

```sql
-- Health check for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  'Last 7 Days' as period,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id

UNION ALL

SELECT
  system_id,
  'Last 14 Days' as period,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id

UNION ALL

SELECT
  system_id,
  'Last 30 Days' as period,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id

ORDER BY system_id, period
```

**Model Version Notes**:
- **catboost_v9**: Current production model (Jan 31+)
- **catboost_v8**: Historical model (Jan 18-28, 2026)
- **ensemble models**: Active for comparison

## Vegas Sharpness Query

**IMPORTANT**: Compare ALL active models vs Vegas to see which performs best.

```sql
-- Vegas sharpness comparison for ALL models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(absolute_error), 2) as model_mae,
  ROUND(100.0 * COUNTIF(absolute_error < ABS(line_value - actual_points)) / COUNT(*), 1) as model_beats_vegas_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN (SELECT system_id FROM active_models)
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  AND line_value IS NOT NULL
GROUP BY system_id, month
ORDER BY system_id, month DESC
```

## Weekly Trend Query

**IMPORTANT**: Show weekly trends for ALL active models to compare drift patterns.

```sql
-- Weekly trend for ALL models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  CASE
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) >= 60 THEN 'EXCELLENT'
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) >= 55 THEN 'GOOD'
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) >= 52.4 THEN 'OK'
    ELSE 'BELOW_BREAKEVEN'
  END as status
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, week
ORDER BY system_id, week DESC
```

## Confidence Calibration Query

**IMPORTANT**: Check confidence calibration for ALL active models to see which is best calibrated.

```sql
-- Confidence calibration for ALL models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.90 THEN '90+'
    WHEN confidence_score >= 0.85 THEN '85-89'
    WHEN confidence_score >= 0.80 THEN '80-84'
    WHEN confidence_score >= 0.75 THEN '75-79'
    ELSE '<75'
  END as confidence_bucket,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as actual_hit_rate,
  ROUND(AVG(confidence_score) * 100, 0) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, confidence_bucket
ORDER BY system_id, confidence_bucket DESC
```

## Using Python Diagnostics

```python
from datetime import date
from shared.utils.performance_diagnostics import run_diagnostics, get_alert

# Full analysis
results = run_diagnostics(date.today())

# Quick alert check
alert = get_alert()
print(f"Status: {alert['level']}")
print(f"Message: {alert['message']}")
```

## Output Format

```
Model Health Report (2026-01-31)
================================

Overall Status: WARNING

Rolling Performance:
| Period   | Predictions | Hit Rate | MAE  | Bias  | Status |
|----------|-------------|----------|------|-------|--------|
| 7 days   | 284         | 54.2%    | 4.85 | -0.3  | OK     |
| 14 days  | 612         | 52.8%    | 4.92 | -0.5  | OK     |
| 30 days  | 1,245       | 56.1%    | 4.67 | -0.2  | GOOD   |

Vegas Sharpness:
| Month   | Vegas MAE | Model MAE | Model Beats Vegas |
|---------|-----------|-----------|-------------------|
| Jan '26 | 5.04      | 5.38      | 45.2%             |
| Dec '25 | 5.37      | 5.51      | 52.8%             |

Root Cause Analysis:
  Primary Cause: VEGAS_SHARP (72% confidence)
  Vegas is more accurate than usual in January.

Recommendations:
  1. Raise edge threshold to 5+ points
  2. Focus on rotation/bench tiers (softer lines)
  3. Consider reducing position sizes until Vegas softens
```

## Alert Levels

| Level | Meaning | Trigger |
|-------|---------|---------|
| OK | Normal operation | All metrics in range |
| INFO | Notable changes | Baseline deviation |
| WARNING | Attention needed | drift_score >= 40 OR model_beats_vegas < 45% |
| CRITICAL | Immediate action | model_beats_vegas < 42% AND hit_rate_7d < 50% |

## Root Cause Categories

| Cause | Meaning | Action |
|-------|---------|--------|
| VEGAS_SHARP | Market unusually efficient | Raise edge thresholds |
| MODEL_DRIFT | Model performance degrading | Retrain on recent data |
| DATA_QUALITY | Pipeline/feature issues | Check feature store |
| NORMAL_VARIANCE | Expected fluctuation | Monitor, no action |
