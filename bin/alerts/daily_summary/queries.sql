-- =====================================================================
-- NBA Prediction Daily Summary - BigQuery Queries
--
-- Queries used by the daily Slack summary Cloud Function
-- Fetches yesterday's prediction stats for monitoring and visibility
--
-- Created: 2026-01-17 (Week 3 - Option B Implementation)
-- =====================================================================

-- Query 1: Yesterday's Prediction Count by System
-- Returns total predictions generated and systems operational
-- =====================================================================
WITH yesterday_predictions AS (
  SELECT
    system_id,
    COUNT(*) as prediction_count,
    AVG(confidence_score) as avg_confidence,
    COUNTIF(confidence_score = 0.5) as fallback_count,
    COUNTIF(recommendation = 'OVER') as over_count,
    COUNTIF(recommendation = 'UNDER') as under_count,
    COUNTIF(recommendation = 'PASS') as pass_count
  FROM `nba_predictions.player_prop_predictions`
  WHERE
    created_at >= TIMESTAMP(CURRENT_DATE() - 1)
    AND created_at < TIMESTAMP(CURRENT_DATE())
  GROUP BY system_id
)
SELECT
  COUNT(DISTINCT system_id) as systems_operational,
  SUM(prediction_count) as total_predictions,
  AVG(avg_confidence) as overall_avg_confidence,
  SUM(fallback_count) as total_fallback_predictions,
  SAFE_DIVIDE(SUM(fallback_count), SUM(prediction_count)) * 100 as fallback_rate_pct,
  SUM(over_count) as total_over,
  SUM(under_count) as total_under,
  SUM(pass_count) as total_pass
FROM yesterday_predictions;

-- Query 2: Top 5 Picks by Confidence (Yesterday)
-- Returns highest confidence predictions for highlight in summary
-- =====================================================================
SELECT
  player_lookup,
  predicted_points,
  current_points_line,
  recommendation,
  confidence_score,
  system_id,
  game_date
FROM `nba_predictions.player_prop_predictions`
WHERE
  created_at >= TIMESTAMP(CURRENT_DATE() - 1)
  AND created_at < TIMESTAMP(CURRENT_DATE())
  AND recommendation IN ('OVER', 'UNDER')  -- Exclude PASS
  AND confidence_score > 0.5  -- Exclude fallback predictions
ORDER BY confidence_score DESC
LIMIT 5;

-- Query 3: System-Level Performance (Yesterday)
-- Returns per-system stats for detailed breakdown
-- =====================================================================
SELECT
  system_id,
  COUNT(*) as prediction_count,
  AVG(confidence_score) as avg_confidence,
  MIN(confidence_score) as min_confidence,
  MAX(confidence_score) as max_confidence,
  COUNTIF(confidence_score = 0.5) as fallback_count,
  SAFE_DIVIDE(COUNTIF(confidence_score = 0.5), COUNT(*)) * 100 as fallback_rate_pct,
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba_predictions.player_prop_predictions`
WHERE
  created_at >= TIMESTAMP(CURRENT_DATE() - 1)
  AND created_at < TIMESTAMP(CURRENT_DATE())
GROUP BY system_id
ORDER BY system_id;

-- Query 4: Feature Quality Check (Last 24 Hours)
-- Checks if features are fresh and available
-- =====================================================================
SELECT
  COUNT(DISTINCT player_lookup) as players_with_features,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_updated, HOUR)) as max_hours_since_update,
  AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_updated, HOUR)) as avg_hours_since_update
FROM `nba_predictions.ml_feature_store_v2`
WHERE
  game_date >= CURRENT_DATE()
  AND last_updated >= TIMESTAMP(CURRENT_DATE() - 1);

-- Query 5: Recent Alerts Count (Last 24 Hours)
-- Count of critical/warning alerts triggered in last 24h
-- Note: This queries Cloud Logging, so it may need to be handled differently
-- in the Cloud Function using the Logging API
-- =====================================================================
-- This query placeholder - actual implementation in Cloud Function
-- will use google-cloud-logging library to query:
--   - nba_model_load_failures
--   - nba_env_var_changes
--   - nba_fallback_predictions (if > threshold)
--   - nba_confidence_drift
--   - nba_feature_pipeline_stale

-- Query 6: Dead Letter Queue Status
-- Check for failed prediction requests
-- Note: This will be queried via Pub/Sub API in Cloud Function
-- =====================================================================
-- Placeholder - actual implementation uses google-cloud-pubsub
-- to get num_undelivered_messages metric for prediction-request-dlq-sub

-- Query 7: Unique Players Predicted (Yesterday)
-- =====================================================================
SELECT
  COUNT(DISTINCT player_lookup) as unique_players_predicted,
  COUNT(DISTINCT game_id) as unique_games_covered
FROM `nba_predictions.player_prop_predictions`
WHERE
  created_at >= TIMESTAMP(CURRENT_DATE() - 1)
  AND created_at < TIMESTAMP(CURRENT_DATE());

-- Query 8: Confidence Distribution (Yesterday)
-- Breakdown of predictions by confidence tier
-- =====================================================================
SELECT
  CASE
    WHEN confidence_score >= 0.90 THEN 'Gold (90%+)'
    WHEN confidence_score >= 0.80 THEN 'Silver (80-90%)'
    WHEN confidence_score >= 0.70 THEN 'Bronze (70-80%)'
    WHEN confidence_score >= 0.60 THEN 'Standard (60-70%)'
    WHEN confidence_score > 0.50 THEN 'Low (50-60%)'
    ELSE 'Fallback (50%)'
  END as confidence_tier,
  COUNT(*) as prediction_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM `nba_predictions.player_prop_predictions`
WHERE
  created_at >= TIMESTAMP(CURRENT_DATE() - 1)
  AND created_at < TIMESTAMP(CURRENT_DATE())
GROUP BY confidence_tier
ORDER BY
  CASE confidence_tier
    WHEN 'Gold (90%+)' THEN 1
    WHEN 'Silver (80-90%)' THEN 2
    WHEN 'Bronze (70-80%)' THEN 3
    WHEN 'Standard (60-70%)' THEN 4
    WHEN 'Low (50-60%)' THEN 5
    ELSE 6
  END;
