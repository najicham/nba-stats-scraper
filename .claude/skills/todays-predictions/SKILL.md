---
name: todays-predictions
description: View today's active predictions with filtering options
---

# Skill: Today's Predictions

View today's active predictions with filtering options.

## Trigger
- User asks about "today's predictions", "today's picks", "what are today's bets"
- User types `/todays-predictions`

## Workflow

1. Query today's predictions from `nba_predictions.player_prop_predictions`
2. Filter by edge if requested
3. Display in a readable table format

**Note**: For actionable trading picks, use `/top-picks` instead — it queries the signal-filtered best bets.

## Default Query (All Predictions)

Shows predictions from ALL enabled models dynamically.

```sql
-- Today's predictions for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(predicted_points - current_points_line, 1) as edge,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT model_id FROM enabled_models)
ORDER BY system_id, ABS(predicted_points - current_points_line) DESC
LIMIT 100
```

## High-Edge Picks Query

```sql
-- High-edge picks (3+) for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT model_id FROM enabled_models)
  AND ABS(predicted_points - current_points_line) >= 3
ORDER BY system_id, ABS(predicted_points - current_points_line) DESC
```

## Summary Query

```sql
-- Summary stats for ALL enabled models
WITH enabled_models AS (
  SELECT model_id
  FROM nba_predictions.model_registry
  WHERE enabled = TRUE
)
SELECT
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge_5plus,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 1) as avg_edge
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id IN (SELECT model_id FROM enabled_models)
GROUP BY system_id
ORDER BY system_id
```

## Output Format

### Summary
```
Today's Predictions Summary (2026-03-03)
========================================
Model: catboost_v12_noveg_train0103_0227
  Total: 75 | Over: 38 | Under: 37
  Edge 3+: 28 | Edge 5+: 12 | Avg Edge: 3.1

Model: lgbm_v12_noveg_train0103_0227
  Total: 72 | Over: 35 | Under: 37
  Edge 3+: 22 | Edge 5+: 8 | Avg Edge: 2.8
```

### Detailed Table
```
| Player          | Predicted | Vegas | Edge  | Rec   | Model               |
|-----------------|-----------|-------|-------|-------|---------------------|
| lebron-james    | 27.5      | 24.5  | +3.0  | OVER  | catboost_v12_noveg_ |
| jayson-tatum    | 28.1      | 31.5  | -3.4  | UNDER | catboost_v12_noveg_ |
```

## Filtering Options

Users can ask for:
- "Show picks with 5+ edge" → edge >= 5
- "Show only OVER picks" → recommendation = 'OVER'
- "Show only UNDER picks" → recommendation = 'UNDER'
- "Show a specific model" → filter by system_id

## Parameters

- `date`: Specific date to check (default: today)
- `model`: Filter to a specific model (default: all enabled)
