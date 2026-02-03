# Skill: Today's Predictions

View today's active predictions with filtering options.

## Trigger
- User asks about "today's predictions", "today's picks", "what are today's bets"
- User types `/todays-predictions`

## Workflow

1. Query today's predictions from `nba_predictions.player_prop_predictions`
2. Filter by confidence and edge if requested
3. Display in a readable table format

## Default Query (All Predictions)

**IMPORTANT**: This query shows predictions from ALL active models to compare.

```sql
-- Today's predictions for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
    AND is_active = TRUE
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(predicted_points - current_points_line, 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT system_id FROM active_models)
ORDER BY system_id, confidence_score DESC, ABS(predicted_points - current_points_line) DESC
LIMIT 100
```

**Model Version Notes**:
- **catboost_v9**: Current production model (Jan 31+ predictions)
- **ensemble_v1_1**: Active ensemble model for comparison
- Results grouped by model to compare predictions side-by-side

## High-Confidence Picks Query

**IMPORTANT**: Shows high-confidence picks for ALL active models.

```sql
-- High-confidence picks for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
    AND is_active = TRUE
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT system_id FROM active_models)
  AND confidence_score >= 0.90
  AND ABS(predicted_points - current_points_line) >= 3
ORDER BY system_id, ABS(predicted_points - current_points_line) DESC
```

## Summary Query

**IMPORTANT**: Summary stats for ALL active models to compare.

```sql
-- Summary for ALL active models
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
    AND is_active = TRUE
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks,
  COUNTIF(confidence_score >= 0.90) as high_confidence,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus,
  COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - current_points_line) >= 3) as trading_candidates
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT system_id FROM active_models)
GROUP BY system_id
ORDER BY system_id
```

## ⚠️ Star Player UNDER Warning (Session 101)

**CRITICAL CHECK**: Before trusting high-edge UNDER picks on star players, verify model doesn't have regression-to-mean bias.

**Background**: Session 101 discovered that high-edge UNDER picks on stars (25+ pt scorers) were losing consistently because the model was under-predicting stars by ~9 points.

**Quick Bias Check**:
```sql
-- Check if star UNDERs are reliable today
SELECT
  p.player_lookup,
  p.predicted_points,
  p.current_points_line as vegas_line,
  p.recommendation,
  ROUND(h.avg_points, 1) as player_season_avg,
  CASE
    WHEN h.avg_points >= 25 AND p.recommendation = 'UNDER'
         AND p.predicted_points < h.avg_points - 5
    THEN '⚠️ CAUTION: Star player, model predicts well below avg'
    ELSE '✅'
  END as warning
FROM nba_predictions.player_prop_predictions p
LEFT JOIN (
  SELECT player_lookup, AVG(points) as avg_points
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND points > 0
  GROUP BY 1
) h ON p.player_lookup = h.player_lookup
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = 'catboost_v9'
  AND p.is_active = TRUE
  AND ABS(p.predicted_points - p.current_points_line) >= 5  -- High edge only
ORDER BY h.avg_points DESC NULLS LAST
LIMIT 20
```

**Red Flags**:
- Model predicts star at 15-20 pts when their season avg is 28+
- UNDER recommendation on high-usage player with >5 pt edge
- Heavy UNDER skew (>70% of picks are UNDER)

**If warnings appear**: Check `/model-health` tier bias before placing bets.

## Output Format

### Summary
```
Today's Predictions Summary (2026-01-31)
========================================
Total Predictions: 145
Over Picks: 72 | Under Picks: 73
High Confidence (90+): 34
Edge 3+ Points: 28
Trading Candidates (90+ conf, 3+ edge): 12
```

### Detailed Table
```
| Player          | Predicted | Vegas | Edge  | Conf | Rec   |
|-----------------|-----------|-------|-------|------|-------|
| lebron-james    | 27.5      | 24.5  | +3.0  | 92%  | OVER  |
| jayson-tatum    | 28.1      | 31.5  | -3.4  | 91%  | UNDER |
```

## Filtering Options

Users can ask for:
- "Show only high confidence picks" → confidence >= 90
- "Show picks with 5+ edge" → edge >= 5
- "Show only OVER picks" → recommendation = 'OVER'
- "Show star players only" → filter by tier
