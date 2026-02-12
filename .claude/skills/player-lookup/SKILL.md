# Skill: Player Lookup

Look up prediction history and accuracy for a specific player.

## Trigger
- User asks about a specific player's predictions or accuracy
- User types `/player-lookup <player-name>`
- "How is LeBron doing?", "Show me Tatum's predictions"

## Workflow

1. Parse player name from query
2. Query recent predictions and grading for that player
3. Calculate player-specific metrics
4. Display historical trend

## Player Search Query

```sql
-- Find player lookup by partial name
SELECT DISTINCT player_lookup
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE player_lookup LIKE '%lebron%'  -- Replace with search term
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
LIMIT 10
```

## Recent Predictions Query

```sql
SELECT
  pa.game_date,
  ROUND(pa.predicted_points, 1) as predicted,
  ROUND(pa.actual_points, 1) as actual,
  ROUND(pa.line_value, 1) as vegas_line,
  ROUND(pa.absolute_error, 1) as error,
  pa.prediction_correct as hit,
  ROUND(pa.confidence_score * 100, 0) as confidence,
  pa.recommendation
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
WHERE pa.player_lookup = @player_lookup
  AND pa.system_id = 'catboost_v9'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY pa.game_date DESC
LIMIT 20
```

## Player Summary Query

```sql
SELECT
  player_lookup,
  COUNT(*) as total_predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as avg_error,
  ROUND(AVG(signed_error), 2) as avg_bias,
  ROUND(AVG(confidence_score) * 100, 0) as avg_confidence,
  COUNTIF(prediction_correct AND confidence_score >= 0.90) as high_conf_hits,
  COUNTIF(confidence_score >= 0.90) as high_conf_total
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE player_lookup = @player_lookup
  AND system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1
```

## Today's Prediction Query

```sql
SELECT
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(predicted_points - current_points_line, 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation,
  key_factors,
  warnings
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE player_lookup = @player_lookup
  AND game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'
```

## Rolling Performance Query

```sql
WITH rolling_stats AS (
  SELECT
    game_date,
    prediction_correct,
    absolute_error,
    ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE player_lookup = @player_lookup
    AND system_id = 'catboost_v9'
    AND prediction_correct IS NOT NULL
  ORDER BY game_date DESC
)
SELECT
  'Last 5' as window,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM rolling_stats
WHERE game_num <= 5

UNION ALL

SELECT
  'Last 10' as window,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as avg_error
FROM rolling_stats
WHERE game_num <= 10
```

## Output Format

```
Player: lebron-james
========================

Today's Prediction:
  Predicted: 27.5 pts | Vegas: 24.5 | Edge: +3.0 | Confidence: 93%
  Recommendation: OVER
  Key Factors: High usage, favorable matchup vs DEN
  Warnings: Back-to-back game

30-Day Performance:
  Total Predictions: 15
  Hit Rate: 66.7% (10/15)
  Average Error: 3.8 pts
  Bias: -0.5 (slight underprediction)
  High Confidence (90+): 80.0% (4/5)

Rolling Performance:
| Window   | Hit Rate | Avg Error |
|----------|----------|-----------|
| Last 5   | 60.0%    | 4.2       |
| Last 10  | 70.0%    | 3.5       |

Recent Games:
| Date       | Pred  | Actual | Line  | Error | Hit |
|------------|-------|--------|-------|-------|-----|
| 2026-01-30 | 27.5  | 29     | 24.5  | 1.5   | YES |
| 2026-01-28 | 26.0  | 22     | 25.5  | 4.0   | NO  |
```

## Parameters

- `player`: Player lookup name (e.g., "lebron-james", "jayson-tatum")
- `days`: Lookback period (default: 30)
- `system_id`: Model version (default: catboost_v9)
