-- ============================================================================
-- System Daily Performance Table Schema (Phase 6 - Publishing)
-- ============================================================================
-- Dataset: nba_predictions
-- Table: system_daily_performance
-- Purpose: Pre-aggregate daily system metrics for website dashboard
-- Created: 2025-12-10
-- ============================================================================
--
-- This table aggregates prediction_accuracy (Phase 5B) by system and date.
-- Used by Phase 6 JSON exporters for efficient dashboard queries.
--
-- Source: nba_predictions.prediction_accuracy
-- Refresh: Daily after Phase 5B grading completes
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.system_daily_performance` (
  -- Primary Keys
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Volume Metrics
  predictions_count INTEGER,           -- All predictions for this system
  recommendations_count INTEGER,       -- OVER + UNDER (excludes PASS)
  correct_count INTEGER,               -- Correct OVER/UNDER recommendations
  incorrect_count INTEGER,             -- Incorrect OVER/UNDER recommendations
  pass_count INTEGER,                  -- PASS recommendations

  -- Core Accuracy Metrics
  win_rate NUMERIC(4, 3),              -- correct / recommendations (0.000 to 1.000)
  mae NUMERIC(5, 2),                   -- Mean Absolute Error
  avg_bias NUMERIC(5, 2),              -- Mean Signed Error (+ = over-predict)

  -- OVER/UNDER Breakdown
  over_count INTEGER,
  over_correct INTEGER,
  over_win_rate NUMERIC(4, 3),
  under_count INTEGER,
  under_correct INTEGER,
  under_win_rate NUMERIC(4, 3),

  -- Threshold Accuracy
  within_3_count INTEGER,
  within_3_pct NUMERIC(4, 3),
  within_5_count INTEGER,
  within_5_pct NUMERIC(4, 3),

  -- Confidence Analysis (high = confidence >= 0.70)
  avg_confidence NUMERIC(4, 3),
  high_confidence_count INTEGER,
  high_confidence_correct INTEGER,
  high_confidence_win_rate NUMERIC(4, 3),

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id
OPTIONS (
  require_partition_filter=TRUE
);

-- ============================================================================
-- Aggregation Query (run after Phase 5B grading)
-- ============================================================================
-- INSERT INTO system_daily_performance
-- SELECT
--   game_date, system_id,
--   COUNT(*) as predictions_count,
--   COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations_count,
--   COUNTIF(prediction_correct) as correct_count,
--   COUNTIF(NOT prediction_correct AND recommendation IN ('OVER', 'UNDER')) as incorrect_count,
--   COUNTIF(recommendation = 'PASS') as pass_count,
--   ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 3) as win_rate,
--   ROUND(AVG(absolute_error), 2) as mae,
--   ROUND(AVG(signed_error), 2) as avg_bias,
--   ... (see populate query)
-- FROM prediction_accuracy
-- WHERE game_date = @target_date
-- GROUP BY game_date, system_id;
-- ============================================================================
