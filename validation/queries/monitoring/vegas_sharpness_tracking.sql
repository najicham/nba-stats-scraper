-- Vegas Line Sharpness Tracking
-- Purpose: Monitor if Vegas lines are getting more accurate over time
-- Usage: Run weekly to detect market efficiency changes
-- Alert: If model_edge < 0 for 2+ consecutive weeks

-- Weekly Vegas vs Model Performance
SELECT
  DATE_TRUNC(game_date, WEEK) as week_start,
  COUNT(*) as total_predictions,

  -- Vegas accuracy
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(STDDEV(actual_points - line_value), 2) as vegas_std,

  -- Model accuracy
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as model_mae,

  -- Edge calculation (positive = we beat Vegas)
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as model_edge,

  -- Line tightness (% outcomes within X points of line)
  ROUND(100.0 * COUNTIF(ABS(actual_points - line_value) <= 2) / COUNT(*), 1) as within_2pts_pct,
  ROUND(100.0 * COUNTIF(ABS(actual_points - line_value) <= 3) / COUNT(*), 1) as within_3pts_pct,

  -- Alert flag
  CASE
    WHEN AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)) < -0.5 THEN 'ALERT: Vegas beating us'
    WHEN AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)) < 0 THEN 'WARNING: Negative edge'
    ELSE 'OK'
  END as status

FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND line_value IS NOT NULL
  AND actual_points IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;


-- OVER vs UNDER Edge Comparison
SELECT
  DATE_TRUNC(game_date, WEEK) as week_start,
  recommendation,
  COUNT(*) as picks,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as model_mae,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  CASE
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) < 50 THEN 'FAILING'
    WHEN ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) < 55 THEN 'WARNING'
    ELSE 'OK'
  END as status

FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND recommendation IN ('OVER', 'UNDER')
  AND line_value IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
