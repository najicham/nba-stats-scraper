# Skill: Top Picks

Extract the best trading candidates based on confidence and edge.

## Trigger
- User asks about "top picks", "best bets", "trading candidates", "what should I bet on"
- User types `/top-picks`

## Definition

**Top Picks** = Predictions with:
- Confidence >= 90% (model is highly certain)
- Edge >= 3 points (meaningful disagreement with Vegas)

These are the picks most likely to be profitable based on historical analysis.

## Main Query

**IMPORTANT**: This query uses the CURRENT production model (catboost_v9 as of Jan 31, 2026).

```sql
-- Top picks for CURRENT production model (catboost_v9)
SELECT
  player_lookup,
  ROUND(predicted_points, 1) as predicted,
  ROUND(current_points_line, 1) as vegas_line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  ROUND(confidence_score * 100, 0) as confidence,
  recommendation,
  system_id,
  CASE
    WHEN ABS(predicted_points - current_points_line) >= 5 THEN 'HIGH'
    ELSE 'MEDIUM'
  END as edge_level
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'  -- Use current production model
  AND confidence_score >= 0.90
  AND ABS(predicted_points - current_points_line) >= 3
ORDER BY
  ABS(predicted_points - current_points_line) DESC,
  confidence_score DESC
```

**Model Selection Logic**:
- Use `catboost_v9` for current predictions (Jan 31+ games)
- Use `catboost_v8` for historical analysis (Jan 18-28, 2026)
- Can add `OR system_id = 'ensemble_v1_1'` to compare models

## With Recent Player Performance

**IMPORTANT**: Uses CURRENT production model (catboost_v9) for both today's picks and historical performance.

```sql
WITH player_recent AS (
  SELECT
    player_lookup,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as recent_hit_rate,
    COUNT(*) as recent_games
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND system_id = 'catboost_v9'  -- Use current production model
  GROUP BY player_lookup
)
SELECT
  p.player_lookup,
  ROUND(p.predicted_points, 1) as predicted,
  ROUND(p.current_points_line, 1) as vegas_line,
  ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
  ROUND(p.confidence_score * 100, 0) as confidence,
  p.recommendation,
  p.system_id,
  COALESCE(r.recent_hit_rate, 0) as player_30d_hit_rate,
  COALESCE(r.recent_games, 0) as games_l30
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
LEFT JOIN player_recent r ON p.player_lookup = r.player_lookup
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND p.system_id = 'catboost_v9'  -- Use current production model
  AND p.confidence_score >= 0.90
  AND ABS(p.predicted_points - p.current_points_line) >= 3
ORDER BY
  ABS(p.predicted_points - p.current_points_line) DESC,
  p.confidence_score DESC
```

**Note**: For dates before Jan 31, 2026, change `system_id = 'catboost_v8'` to match historical data.

## Summary Stats

**IMPORTANT**: Summary for CURRENT production model (catboost_v9).

```sql
SELECT
  system_id,
  COUNT(*) as top_picks_count,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 1) as avg_edge,
  ROUND(AVG(confidence_score) * 100, 0) as avg_confidence,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge_5plus
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'  -- Use current production model
  AND confidence_score >= 0.90
  AND ABS(predicted_points - current_points_line) >= 3
GROUP BY system_id
```

## Historical Performance of Top Picks

**IMPORTANT**: Shows historical performance for ALL active models to compare.

```sql
-- How do 90+ conf, 3+ edge picks perform historically? (ALL MODELS)
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN (SELECT system_id FROM active_models)
  AND confidence_score >= 0.90
  AND ABS(predicted_points - line_value) >= 3
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY system_id, month
ORDER BY system_id, month DESC
```

**Model Comparison Notes**:
- catboost_v9 is expected to have limited historical data (just started Jan 31)
- catboost_v8 has full historical data through Jan 28
- Compare performance to determine if V9 is improving over V8

## Output Format

```
Top Picks for Today (2026-01-31)
================================

Found 12 trading candidates (90+ confidence, 3+ edge)

| Player          | Predicted | Vegas | Edge  | Conf | Pick  | 30d Hit |
|-----------------|-----------|-------|-------|------|-------|---------|
| lebron-james    | 27.5      | 22.5  | +5.0  | 93%  | OVER  | 68.2%   |
| jayson-tatum    | 25.1      | 30.5  | -5.4  | 92%  | UNDER | 71.4%   |
| luka-doncic     | 33.2      | 29.5  | +3.7  | 91%  | OVER  | 65.0%   |

Summary:
  Total Picks: 12
  Over/Under Split: 7 OVER / 5 UNDER
  Average Edge: 4.2 points
  Average Confidence: 91.3%

Historical Performance (Last 90 Days):
  Hit Rate: 76.8% (target: 52.4%)
  ROI: +46.7%
```

## Filtering Options

- `/top-picks 5` → Only 5+ edge picks
- `/top-picks over` → Only OVER picks
- `/top-picks under` → Only UNDER picks
- `/top-picks star` → Only star players (22+ ppg)

## Why These Thresholds?

Based on Session 55 analysis:
- 90+ confidence hits ~77% when combined with 3+ edge
- 85-89 confidence drops to ~50% even with good edge
- Edge < 3 has poor ROI regardless of confidence

The breakeven at -110 odds is 52.4%, so 77% provides significant edge.
