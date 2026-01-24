-- ============================================================================
-- System Performance Summary Table Schema
-- ============================================================================
-- Dataset: nba_grading
-- Table: system_performance_summary
-- Purpose: Aggregated prediction success rates per system for dashboard access
-- Created: 2026-01-23
-- ============================================================================
--
-- This table stores pre-computed performance metrics for each prediction system
-- across different time periods (rolling_7d, rolling_30d, season).
-- Used by the admin dashboard /api/system-performance endpoint.
--
-- Source: nba_predictions.prediction_accuracy (Phase 5B)
-- Refresh: Daily after grading completes
-- ============================================================================

-- Create dataset if not exists
CREATE SCHEMA IF NOT EXISTS `nba-props-platform.nba_grading`
OPTIONS (
  location = 'US',
  description = 'NBA prediction grading and performance tracking'
);

-- Create the performance summary table
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_grading.system_performance_summary` (
  -- Identifiers
  system_id STRING NOT NULL,
  prop_type STRING NOT NULL DEFAULT 'points',  -- points, assists, rebounds (future)
  period_type STRING NOT NULL,                 -- rolling_7d, rolling_30d, season

  -- Period bounds
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,

  -- Volume metrics
  total_predictions INTEGER,
  total_recommendations INTEGER,               -- OVER + UNDER (excludes PASS)
  pass_count INTEGER,

  -- Win/Loss metrics
  wins INTEGER,
  losses INTEGER,
  pushes INTEGER,
  success_rate_pct NUMERIC(5, 2),              -- 0.00 to 100.00

  -- Error metrics
  mae NUMERIC(5, 2),                           -- Mean Absolute Error
  avg_bias NUMERIC(5, 2),                      -- Mean Signed Error
  error_stddev NUMERIC(5, 2),                  -- Error standard deviation

  -- Over breakdown
  over_count INTEGER,
  over_wins INTEGER,
  over_success_rate_pct NUMERIC(5, 2),

  -- Under breakdown
  under_count INTEGER,
  under_wins INTEGER,
  under_success_rate_pct NUMERIC(5, 2),

  -- Threshold accuracy
  within_3_count INTEGER,
  within_3_pct NUMERIC(5, 2),
  within_5_count INTEGER,
  within_5_pct NUMERIC(5, 2),

  -- High confidence analysis (>= 70%)
  high_conf_count INTEGER,
  high_conf_wins INTEGER,
  high_conf_success_rate_pct NUMERIC(5, 2),

  -- Very high confidence (>= 80%)
  very_high_conf_count INTEGER,
  very_high_conf_wins INTEGER,
  very_high_conf_success_rate_pct NUMERIC(5, 2),

  -- Average confidence
  avg_confidence NUMERIC(4, 3),

  -- Coverage metrics
  voided_count INTEGER,
  unique_players INTEGER,
  unique_games INTEGER,
  days_with_data INTEGER,

  -- Metadata
  computed_at TIMESTAMP
)
CLUSTER BY system_id, period_type
OPTIONS (
  description = 'Aggregated prediction success rates per system for dashboard access'
);

-- ============================================================================
-- Example Queries
-- ============================================================================

-- Get all systems performance for last 7 days (dashboard main view)
-- SELECT
--   system_id,
--   prop_type,
--   success_rate_pct,
--   wins,
--   losses,
--   mae,
--   high_conf_success_rate_pct,
--   total_predictions
-- FROM `nba-props-platform.nba_grading.system_performance_summary`
-- WHERE period_type = 'rolling_7d'
-- ORDER BY success_rate_pct DESC;

-- Compare systems across periods
-- SELECT
--   system_id,
--   period_type,
--   success_rate_pct,
--   high_conf_success_rate_pct,
--   mae
-- FROM `nba-props-platform.nba_grading.system_performance_summary`
-- WHERE system_id = 'catboost_v8'
-- ORDER BY
--   CASE period_type
--     WHEN 'rolling_7d' THEN 1
--     WHEN 'rolling_30d' THEN 2
--     WHEN 'season' THEN 3
--   END;

-- ============================================================================
-- VERSION HISTORY
-- ============================================================================
-- v1.0 (2026-01-23): Initial schema for system performance tracking
--                    Supports points prop type, ready for assists/rebounds expansion
-- ============================================================================
