-- =============================================================================
-- Pre-Game Daily Diagnostic
-- Run each morning before betting to assess prediction quality signals
-- =============================================================================

-- Query 1: Main Diagnostic
-- Returns all key signals for today's predictions
SELECT
  game_date,
  COUNT(*) as total_picks,
  SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) as high_edge_picks,
  SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 3 AND confidence_score >= 0.92 THEN 1 ELSE 0 END) as premium_picks,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,

  -- Warning Flags
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 20
    THEN 'RED: EXTREME UNDER SKEW (<20%)'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
    THEN 'YELLOW: HEAVY UNDER SKEW (<25%)'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45
    THEN 'YELLOW: HEAVY OVER SKEW (>45%)'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 50
    THEN 'RED: EXTREME OVER SKEW (>50%)'
    ELSE 'GREEN: BALANCED (25-45%)'
  END as skew_signal,

  CASE
    WHEN SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) < 3
    THEN 'RED: VERY LOW PICK COUNT (<3)'
    WHEN SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) < 5
    THEN 'YELLOW: LOW PICK COUNT (<5)'
    ELSE 'GREEN: ADEQUATE VOLUME (5+)'
  END as volume_signal

FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND current_points_line IS NOT NULL
GROUP BY 1;


-- Query 2: High-Edge Pick Details
-- See the actual high-edge picks for today
SELECT
  player_lookup,
  predicted_points,
  current_points_line,
  ROUND(predicted_points - current_points_line, 1) as edge,
  confidence_score,
  recommendation,
  game_id
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND current_points_line IS NOT NULL
  AND ABS(predicted_points - current_points_line) >= 5
ORDER BY ABS(predicted_points - current_points_line) DESC;


-- Query 3: Compare to Recent History
-- See how today's signals compare to last 7 days
WITH daily_signals AS (
  SELECT
    game_date,
    COUNT(*) as total_picks,
    SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) as high_edge_picks,
    ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND system_id = 'catboost_v9'
    AND current_points_line IS NOT NULL
  GROUP BY 1
)
SELECT
  game_date,
  total_picks,
  high_edge_picks,
  pct_over,
  CASE
    WHEN pct_over < 25 THEN 'UNDER SKEW'
    WHEN pct_over > 40 THEN 'OVER SKEW'
    ELSE 'BALANCED'
  END as skew_category
FROM daily_signals
ORDER BY game_date DESC;


-- Query 4: Game-by-Game Breakdown
-- See signal distribution across today's games
SELECT
  game_id,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  SUM(CASE WHEN ABS(predicted_points - current_points_line) >= 5 THEN 1 ELSE 0 END) as high_edge
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND current_points_line IS NOT NULL
GROUP BY 1
ORDER BY high_edge DESC;
