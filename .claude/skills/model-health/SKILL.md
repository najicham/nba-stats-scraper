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

**Quality Context**: For any health check query above, you can JOIN to `nba_predictions.ml_feature_store_v2` on `player_lookup` and `game_date` to understand whether poor performance correlates with low feature quality. Predictions where `matchup_quality_pct < 50` should be excluded from accuracy analysis since they were made with defaulted matchup features (see Session 132).

## Hit Rate by Feature Quality Tier

**IMPORTANT**: Stratify hit rate by feature quality to separate model issues from data quality issues. If `not_ready` predictions drag down overall metrics, the model may be fine -- the pipeline needs fixing.

```sql
-- Hit rate by feature quality tier
SELECT
  CASE WHEN fq.is_quality_ready THEN 'quality_ready' ELSE 'not_ready' END as quality_tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.hit = TRUE) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(pa.absolute_error), 2) as mae,
  ROUND(AVG(fq.feature_quality_score), 1) as avg_quality_score
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.ml_feature_store_v2 fq
  ON pa.player_lookup = fq.player_lookup AND pa.game_date = fq.game_date
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pa.system_id = 'catboost_v9'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

**Interpretation**:
- If `quality_ready` hit rate is significantly higher than `not_ready`, feature quality is a key driver of performance
- If both tiers perform similarly, the issue is model-level, not data-level
- Always exclude `matchup_quality_pct < 50` predictions when evaluating true model accuracy

```sql
-- Accurate model health: exclude low-quality matchup predictions
SELECT
  'Last 14 Days (quality filtered)' as period,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(pa.absolute_error), 2) as mae
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.ml_feature_store_v2 fq
  ON pa.player_lookup = fq.player_lookup AND pa.game_date = fq.game_date
WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pa.system_id = 'catboost_v9'
  AND pa.prediction_correct IS NOT NULL
  AND fq.matchup_quality_pct >= 50;
```

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

## Tier Bias Check (Session 101 - CRITICAL)

**IMPORTANT**: Check for regression-to-mean bias that causes systematic under/over-prediction by player scoring tier.

**Why this matters**: Session 101 discovered V9 was under-predicting stars by -9 points and over-predicting bench by +6 points. This caused 78% UNDER recommendations and consistent high-edge losses.

```sql
-- Tier Bias Check (Session 101)
-- Expected: Bias < ±3 for all tiers
SELECT
  system_id,
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as bias,
  CASE
    WHEN ABS(AVG(predicted_points - actual_points)) > 5 THEN '🔴 CRITICAL'
    WHEN ABS(AVG(predicted_points - actual_points)) > 3 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END as status
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND actual_points IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1, 2
ORDER BY 1, 2
```

**Alert Thresholds**:
| Tier | Healthy | Warning | Critical |
|------|---------|---------|----------|
| Stars (25+) | ±3 | ±3-5 | >±5 |
| All others | ±3 | ±3-5 | >±5 |

**If CRITICAL bias detected**: See `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`

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

## OVER/UNDER Weekly Breakdown (Session 175)

**IMPORTANT**: Directional performance can collapse while overall hit rate looks acceptable. Session 173 discovered OVER went from 76.8% to 44.1% over 4 weeks. Always check directional balance.

```sql
-- Weekly OVER/UNDER hit rate breakdown for edge 3+
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_pct,
  COUNTIF(recommendation = 'OVER') as over_picks,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
        NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 1) as over_hit_pct,
  COUNTIF(recommendation = 'UNDER') as under_picks,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
        NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 1) as under_hit_pct,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND ABS(predicted_points - line_value) >= 3
  AND prediction_correct IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY week_start
ORDER BY week_start DESC
```

**Alert Thresholds for Directional Drift**:

| Direction | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| OVER | >= 55% | 52.4-55% | < 52.4% (below breakeven) |
| UNDER | >= 55% | 52.4-55% | < 52.4% (below breakeven) |

**If directional drift detected**: Run the full diagnosis script (see below).

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

## Detailed Diagnosis Script (Session 175)

For comprehensive analysis beyond quick SQL queries, use `model_diagnose.py`:

```bash
# Full diagnosis: weekly trends, PVL drift, directional balance, period comparison
PYTHONPATH=. python ml/experiments/model_diagnose.py

# Custom parameters
PYTHONPATH=. python ml/experiments/model_diagnose.py --weeks 4 --system-id catboost_v9

# JSON output for automation
PYTHONPATH=. python ml/experiments/model_diagnose.py --json
```

**When to use the script vs quick SQL queries:**
- **Quick SQL**: Spot-check a single metric (e.g., last 7 days hit rate)
- **Diagnosis script**: Comprehensive analysis when you suspect drift, before deciding whether to retrain, or as part of weekly model review

The script outputs a `RETRAIN_NOW` / `MONITOR` / `HEALTHY` recommendation based on trailing 2-week edge 3+ hit rate and directional balance.

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
| DATA_QUALITY | Pipeline/feature issues | Check `ml_feature_store_v2` quality fields: `is_quality_ready`, `matchup_quality_pct`, `quality_alert_level` |
| NORMAL_VARIANCE | Expected fluctuation | Monitor, no action |
