-- ============================================================================
-- MLB Model Performance Daily Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: model_performance_daily
-- Purpose: Daily rolling performance metrics per model. Tracks hit rates,
--          decay state machine, and best bets post-filter metrics.
--          Modeled after nba_predictions.model_performance_daily.
-- Created: 2026-03-06
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.model_performance_daily` (
  -- Primary Keys
  game_date DATE NOT NULL,                      -- Date of metrics snapshot
  model_id STRING NOT NULL,                     -- Model system_id from model_registry

  -- Rolling Hit Rates (overall)
  hr_7d FLOAT64,                                -- 7-day rolling hit rate
  hr_14d FLOAT64,                               -- 14-day rolling hit rate
  hr_30d FLOAT64,                               -- 30-day rolling hit rate

  -- Rolling Sample Counts
  n_7d INT64,                                   -- 7-day graded prediction count
  n_14d INT64,                                  -- 14-day graded prediction count
  n_30d INT64,                                  -- 30-day graded prediction count

  -- Directional Splits (OVER)
  hr_over_7d FLOAT64,
  hr_over_14d FLOAT64,
  hr_over_30d FLOAT64,
  n_over_7d INT64,
  n_over_14d INT64,
  n_over_30d INT64,

  -- Directional Splits (UNDER)
  hr_under_7d FLOAT64,
  hr_under_14d FLOAT64,
  hr_under_30d FLOAT64,
  n_under_7d INT64,
  n_under_14d INT64,
  n_under_30d INT64,

  -- Daily Metrics (single day)
  daily_picks INT64,                            -- Predictions made today
  daily_wins INT64,                             -- Correct predictions today
  daily_losses INT64,                           -- Incorrect predictions today
  daily_hr FLOAT64,                             -- Today's hit rate
  daily_roi FLOAT64,                            -- Today's ROI (assuming -110 juice)

  -- Decay State Machine
  decay_state STRING,                           -- HEALTHY | WATCH | DEGRADING | BLOCKED
  consecutive_days_below_watch INT64,           -- Days below watch threshold (HR < 55%)
  consecutive_days_below_alert INT64,           -- Days below alert threshold (HR < 50%)
  decay_action STRING,                          -- NULL | 'WATCH' | 'DEWEIGHT' | 'DISABLE'
  decay_action_reason STRING,                   -- Human-readable reason for action

  -- Best Bets Post-Filter Metrics
  bb_picks_7d INT64,                            -- Best bets sourced from this model (7d)
  bb_hr_7d FLOAT64,                             -- Best bets hit rate from this model (7d)
  bb_picks_14d INT64,
  bb_hr_14d FLOAT64,
  bb_picks_30d INT64,
  bb_hr_30d FLOAT64,

  -- Brier Score Calibration
  brier_score_7d FLOAT64,                       -- 7-day Brier score (lower = better calibrated)
  brier_score_14d FLOAT64,                      -- 14-day Brier score
  brier_score_30d FLOAT64,                      -- 30-day Brier score

  -- MAE Tracking
  mae_7d FLOAT64,                               -- 7-day mean absolute error
  mae_14d FLOAT64,                              -- 14-day mean absolute error
  mae_30d FLOAT64,                              -- 30-day mean absolute error

  -- Metadata
  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY model_id
OPTIONS (
  require_partition_filter=TRUE,
  description='Daily rolling performance metrics per MLB model. Tracks hit rates across 7d/14d/30d windows, '
              'OVER/UNDER directional splits, decay state machine (HEALTHY/WATCH/DEGRADING/BLOCKED), '
              'best bets post-filter metrics, and Brier score calibration.'
);
