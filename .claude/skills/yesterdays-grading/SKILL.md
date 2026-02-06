# Skill: Yesterday's Grading

View yesterday's prediction results with accuracy metrics.

## Trigger
- User asks about "yesterday's results", "how did we do yesterday", "grading", "yesterday's grading"
- User types `/yesterdays-grading`

## Workflow

1. Query yesterday's graded predictions from `nba_predictions.prediction_accuracy`
2. Calculate hit rate, MAE, bias
3. Break down by tier and confidence
4. Display in readable format

## Summary Query

**IMPORTANT**: This query shows results for ALL active models to compare performance.

```sql
-- Yesterday's results for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  COUNT(*) as total_graded,
  COUNTIF(prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias,
  COUNTIF(signed_error > 0) as over_predictions,
  COUNTIF(signed_error < 0) as under_predictions
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY system_id
```

**Model Version Notes**:
- Results will show all models that had predictions for yesterday
- Compare catboost_v9 vs ensemble_v1_1 vs others
- If checking historical dates (before Jan 31), will show catboost_v8

## By Confidence Query

**IMPORTANT**: Breaks down by confidence for ALL active models.

```sql
-- By confidence for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.90 THEN '90+'
    WHEN confidence_score >= 0.85 THEN '85-89'
    WHEN confidence_score >= 0.80 THEN '80-84'
    ELSE '<80'
  END as confidence,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, confidence
ORDER BY system_id, confidence
```

## By Tier Query

**IMPORTANT**: Breaks down by player tier for ALL active models.

```sql
-- By tier for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  CASE
    WHEN actual_points >= 22 THEN 'Star'
    WHEN actual_points >= 14 THEN 'Starter'
    WHEN actual_points >= 6 THEN 'Rotation'
    ELSE 'Bench'
  END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, tier
ORDER BY system_id, tier
```

**⚠️ Tier Bias Interpretation (Session 101)**:

Look for these red flags in the tier breakdown:

| Tier | Healthy Bias | Warning Sign | Action |
|------|--------------|--------------|--------|
| Star | ±2 | < -5 (under-predicting) | Check `/model-health` |
| Starter | ±2 | < -3 (under-predicting) | Monitor |
| Bench | ±3 | > +5 (over-predicting) | Check model |

**If Star bias < -5**: Model has regression-to-mean issue, UNDERs on stars will lose.
**If Bench bias > +5**: Model over-predicting low scorers, OVERs on bench unreliable.

See `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md` for fix options.

## Trading Filter Query (90+ conf, 3+ edge)

**IMPORTANT**: Shows trading picks for ALL active models to compare.

```sql
-- Trading filter results for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(actual_points, 1) as actual,
  ROUND(line_value, 1) as line,
  prediction_correct as hit,
  ROUND(confidence_score * 100, 0) as conf,
  recommendation
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 3
ORDER BY system_id, prediction_correct DESC, confidence_score DESC
```

## Best/Worst Predictions Query

**IMPORTANT**: Shows best/worst for ALL active models.

```sql
-- Best predictions (closest to actual) for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(actual_points, 1) as actual,
  ROUND(absolute_error, 1) as error,
  prediction_correct as hit
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
ORDER BY system_id, absolute_error ASC
LIMIT 20;

-- Worst predictions (furthest from actual) for ALL active models
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(actual_points, 1) as actual,
  ROUND(absolute_error, 1) as error,
  prediction_correct as hit
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND system_id IN (SELECT system_id FROM active_models)
ORDER BY system_id, absolute_error DESC
LIMIT 20
```

## Output Format

```
Yesterday's Results (2026-01-30)
================================

Overall Performance:
  Total Graded: 142 predictions
  Hit Rate: 58.5% (83/142)
  MAE: 4.32 points
  Bias: -0.8 (slight underprediction)

By Confidence:
| Confidence | Bets | Hit Rate | MAE  |
|------------|------|----------|------|
| 90+        | 28   | 71.4%    | 3.21 |
| 85-89      | 45   | 55.6%    | 4.15 |
| 80-84      | 42   | 52.4%    | 4.89 |
| <80        | 27   | 48.1%    | 5.12 |

By Tier:
| Tier     | Bets | Hit Rate | Bias  |
|----------|------|----------|-------|
| Star     | 24   | 54.2%    | -1.2  |
| Starter  | 48   | 60.4%    | -0.5  |
| Rotation | 52   | 59.6%    | -0.8  |
| Bench    | 18   | 55.6%    | -0.3  |

Trading Picks (90+ conf, 3+ edge): 12 bets, 9 hits (75.0%)
```

## Quality Context Query (Session 140)

**IMPORTANT**: Join grading results to feature quality to understand whether poor performance is caused by low-quality input data rather than model issues.

```sql
-- Quality-stratified grading for yesterday
SELECT
  CASE WHEN fq.is_quality_ready THEN 'quality_ready' ELSE 'not_ready' END as quality_tier,
  fq.quality_alert_level,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(pa.absolute_error), 2) as mae,
  ROUND(AVG(fq.matchup_quality_pct), 1) as avg_matchup_q
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fq
  ON pa.player_lookup = fq.player_lookup AND pa.game_date = fq.game_date
WHERE pa.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND pa.system_id = 'catboost_v9'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY quality_tier, quality_alert_level;
```

**Interpretation**:
- If `quality_ready` hit rate >> `not_ready`, data quality is the limiting factor, not the model
- Predictions with `quality_alert_level = 'red'` should now be blocked by the quality gate (Session 139)
- If any red-alert predictions appear, investigate whether they were generated before the gate was deployed

## Pre-game vs Backfill Predictions (Session 139)

**IMPORTANT**: The `prediction_made_before_game` field distinguishes real pre-game predictions from backfill predictions generated after game results were known.

- **Pre-game** (`prediction_made_before_game = TRUE`): Legitimate predictions for grading
- **Backfill** (`prediction_made_before_game = FALSE`): Record-keeping only, exclude from accuracy analysis

```sql
-- Check prediction timing for yesterday
SELECT
  prediction_made_before_game,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN `nba-props-platform.nba_predictions.player_prop_predictions` pp
  ON pa.player_lookup = pp.player_lookup
  AND pa.game_date = pp.game_date
  AND pa.system_id = pp.system_id
WHERE pa.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND pa.system_id = 'catboost_v9'
GROUP BY 1;
```

**If backfill predictions exist**: These were generated via BACKFILL mode for players who were quality-blocked pre-game. Their accuracy should not count toward model performance.

## Parameters

- `date`: Specific date to check (default: yesterday)
- `system_id`: Which model to check (default: catboost_v9)
