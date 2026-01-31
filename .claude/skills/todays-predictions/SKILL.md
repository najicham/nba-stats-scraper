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

```sql
SELECT
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(predicted_points - current_points_line, 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation,
  system_id
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v8'
ORDER BY confidence_score DESC, ABS(predicted_points - current_points_line) DESC
LIMIT 50
```

## High-Confidence Picks Query

```sql
SELECT
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v8'
  AND confidence_score >= 0.90
  AND ABS(predicted_points - current_points_line) >= 3
ORDER BY ABS(predicted_points - current_points_line) DESC
```

## Summary Query

```sql
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks,
  COUNTIF(confidence_score >= 0.90) as high_confidence,
  COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge_3plus,
  COUNTIF(confidence_score >= 0.90 AND ABS(predicted_points - current_points_line) >= 3) as trading_candidates
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v8'
```

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
