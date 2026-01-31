-- ============================================================================
-- Vegas Sharpness Daily Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: vegas_sharpness_daily
-- Purpose: Track Vegas line accuracy and model comparison metrics over time
-- Created: 2026-01-31 (Session 56)
-- ============================================================================
--
-- This table aggregates prediction_accuracy to track:
-- 1. How accurate Vegas lines are (MAE, within-N percentages)
-- 2. How often our model beats Vegas
-- 3. Edge availability (opportunities to profit)
-- 4. Sharpness trends over time
--
-- Source: nba_predictions.prediction_accuracy
-- Refresh: Daily after Phase 5B grading completes
-- Retention: 2 years (for season-over-season analysis)
--
-- Dashboard Integration:
-- - Admin dashboard Vegas Sharpness page
-- - Charts: Trend lines, tier comparison, day-of-week patterns
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.vegas_sharpness_daily` (
  -- Primary Keys
  game_date DATE NOT NULL,
  tier STRING NOT NULL,              -- 'Star', 'Starter', 'Rotation', 'Bench', 'All'
  system_id STRING NOT NULL,         -- 'catboost_v8', 'all_systems', etc.

  -- Sample Size
  predictions_count INT64,           -- Number of predictions in this segment
  players_count INT64,               -- Distinct players in segment

  -- Vegas Accuracy Metrics
  vegas_mae FLOAT64,                 -- Mean Absolute Error for Vegas lines
  vegas_std FLOAT64,                 -- Standard deviation of Vegas errors
  vegas_within_3pts_pct FLOAT64,     -- % of Vegas lines within 3 points of actual
  vegas_within_5pts_pct FLOAT64,     -- % of Vegas lines within 5 points of actual

  -- Model Accuracy Metrics
  model_mae FLOAT64,                 -- Model's Mean Absolute Error
  model_std FLOAT64,                 -- Standard deviation of model errors
  model_within_3pts_pct FLOAT64,
  model_within_5pts_pct FLOAT64,

  -- Model vs Vegas Comparison
  vegas_minus_model_mae FLOAT64,     -- Positive = model is more accurate
  model_beats_vegas_pct FLOAT64,     -- % of predictions where model error < Vegas error
  model_beats_vegas_count INT64,

  -- Edge Availability
  pct_3plus_edge FLOAT64,            -- % of predictions with |model - line| >= 3
  pct_5plus_edge FLOAT64,            -- % of predictions with |model - line| >= 5
  avg_edge_magnitude FLOAT64,        -- Average |model - line| for all predictions

  -- Win Rate Metrics
  recommendation_count INT64,         -- OVER + UNDER count
  correct_count INT64,
  win_rate FLOAT64,

  -- High-Edge Win Rate (only 3+ edge predictions)
  high_edge_count INT64,
  high_edge_correct INT64,
  high_edge_win_rate FLOAT64,

  -- Sharpness Score (composite)
  sharpness_score FLOAT64,           -- 0-100 scale: higher = easier to beat Vegas
  sharpness_status STRING,           -- 'VERY_SHARP', 'SHARP', 'NORMAL', 'SOFT'

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY tier, system_id
OPTIONS (
  description = 'Daily Vegas sharpness and model comparison metrics by player tier. Used for admin dashboard charts.',
  require_partition_filter = TRUE,
  partition_expiration_days = 730  -- 2 years
);

-- ============================================================================
-- Population Query (run daily after grading)
-- ============================================================================
--
-- INSERT INTO `nba_predictions.vegas_sharpness_daily`
-- WITH player_tiers AS (
--   SELECT player_lookup,
--     CASE
--       WHEN AVG(points) >= 22 THEN 'Star'
--       WHEN AVG(points) >= 14 THEN 'Starter'
--       WHEN AVG(points) >= 6 THEN 'Rotation'
--       ELSE 'Bench'
--     END as tier
--   FROM nba_analytics.player_game_summary
--   WHERE game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
--     AND game_date < @target_date AND minutes_played > 10
--   GROUP BY 1
-- ),
-- base_metrics AS (
--   SELECT
--     pa.game_date, COALESCE(pt.tier, 'Unclassified') as tier, pa.system_id,
--     pa.line_value, pa.actual_points, pa.predicted_points,
--     pa.absolute_error, pa.signed_error,
--     pa.recommendation, pa.prediction_correct, pa.player_lookup,
--     ABS(pa.line_value - pa.actual_points) as vegas_error,
--     ABS(pa.predicted_points - pa.line_value) as edge
--   FROM nba_predictions.prediction_accuracy pa
--   LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
--   WHERE pa.game_date = @target_date
--     AND pa.line_value IS NOT NULL AND pa.is_voided IS NOT TRUE
-- )
-- SELECT
--   game_date, tier, system_id,
--   COUNT(*) as predictions_count,
--   COUNT(DISTINCT player_lookup) as players_count,
--   ROUND(AVG(vegas_error), 2) as vegas_mae,
--   ROUND(STDDEV(vegas_error), 2) as vegas_std,
--   ROUND(COUNTIF(vegas_error <= 3) / COUNT(*), 4) as vegas_within_3pts_pct,
--   ROUND(COUNTIF(vegas_error <= 5) / COUNT(*), 4) as vegas_within_5pts_pct,
--   ROUND(AVG(absolute_error), 2) as model_mae,
--   ROUND(STDDEV(signed_error), 2) as model_std,
--   ROUND(COUNTIF(absolute_error <= 3) / COUNT(*), 4) as model_within_3pts_pct,
--   ROUND(COUNTIF(absolute_error <= 5) / COUNT(*), 4) as model_within_5pts_pct,
--   ROUND(AVG(vegas_error) - AVG(absolute_error), 2) as vegas_minus_model_mae,
--   ROUND(COUNTIF(absolute_error < vegas_error) / COUNT(*), 4) as model_beats_vegas_pct,
--   COUNTIF(absolute_error < vegas_error) as model_beats_vegas_count,
--   ROUND(COUNTIF(edge >= 3) / COUNT(*), 4) as pct_3plus_edge,
--   ROUND(COUNTIF(edge >= 5) / COUNT(*), 4) as pct_5plus_edge,
--   ROUND(AVG(edge), 2) as avg_edge_magnitude,
--   COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendation_count,
--   COUNTIF(prediction_correct = TRUE) as correct_count,
--   ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 4) as win_rate,
--   COUNTIF(edge >= 3 AND recommendation IN ('OVER', 'UNDER')) as high_edge_count,
--   COUNTIF(edge >= 3 AND prediction_correct = TRUE) as high_edge_correct,
--   ROUND(SAFE_DIVIDE(COUNTIF(edge >= 3 AND prediction_correct), COUNTIF(edge >= 3 AND recommendation IN ('OVER', 'UNDER'))), 4) as high_edge_win_rate,
--   ROUND(COUNTIF(absolute_error < vegas_error) / COUNT(*) * 100, 1) as sharpness_score,
--   CASE
--     WHEN COUNTIF(absolute_error < vegas_error) / COUNT(*) < 0.45 THEN 'VERY_SHARP'
--     WHEN COUNTIF(absolute_error < vegas_error) / COUNT(*) < 0.50 THEN 'SHARP'
--     WHEN COUNTIF(absolute_error < vegas_error) / COUNT(*) < 0.55 THEN 'NORMAL'
--     ELSE 'SOFT'
--   END as sharpness_status,
--   CURRENT_TIMESTAMP() as computed_at
-- FROM base_metrics
-- GROUP BY game_date, tier, system_id;
