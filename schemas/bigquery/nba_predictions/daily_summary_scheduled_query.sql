-- Daily NBA Prediction Summary Query
-- Scheduled to run at 9 AM daily (America/Los_Angeles)
-- Results published to Pub/Sub topic: nba-daily-summary

SELECT
  CURRENT_DATE() as report_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  COUNTIF(confidence_score = 0.50) as fallback_count,
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count,
  ROUND(100.0 * COUNTIF(confidence_score = 0.50) / COUNT(*), 1) as fallback_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
GROUP BY system_id
