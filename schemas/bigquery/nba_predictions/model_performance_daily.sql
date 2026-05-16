-- ============================================================================
-- NBA Model Performance Daily Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table:   model_performance_daily
-- Purpose: Daily rolling performance metrics per NBA model. Tracks hit rates,
--          decay state machine, best bets post-filter metrics, Brier calibration,
--          pipeline candidate counts, and (Session 545) per-model bias/MAE
--          tracking for regime-shift detection.
--
-- Owner:   Written by `ml/analysis/model_performance.py` (daily, via
--          `post-grading-export` CF). Read by `bin/monitoring/bias_decay_monitor.py`,
--          `data_processors/publishing/model_health_exporter.py`,
--          `data_processors/publishing/admin_dashboard_exporter.py`,
--          `orchestration/cloud_functions/decay_detection/main.py`.
--
-- Created: 2026-02-15 (Session 262)
-- History:
--   2026-02-15  initial table
--   2026-02-22  +rolling_hr_over/under, +rolling_n_over/under (Session 366)
--   2026-03-12  +best_bets_*, +best_bets_filter_pass_rate (Session 366)
--   2026-04-05  +brier_score_* (Session 399)
--   2026-04-22  +pipeline_* candidate metrics (Session 443)
--   2026-05-15  +pred_bias_*, +model_mae_*, +vegas_mae_*, +mae_gap_* (Session 545,
--               2025-26 anomaly follow-up)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.model_performance_daily` (
  -- Primary keys
  game_date DATE NOT NULL,
  model_id  STRING NOT NULL,

  -- Rolling hit rates (overall, all directions, edge >= 3)
  rolling_hr_7d  FLOAT64,
  rolling_hr_14d FLOAT64,
  rolling_hr_30d FLOAT64,
  rolling_n_7d   INT64,
  rolling_n_14d  INT64,
  rolling_n_30d  INT64,

  -- Same-day metrics
  daily_picks  INT64,
  daily_wins   INT64,
  daily_losses INT64,
  daily_hr     FLOAT64,
  daily_roi    FLOAT64,

  -- Decay state machine
  state                       STRING,   -- HEALTHY | WATCH | DEGRADING | BLOCKED | INSUFFICIENT_DATA
  consecutive_days_below_watch INT64,
  consecutive_days_below_alert INT64,
  action                       STRING,  -- NO_CHANGE | DEGRADED | RECOVERED
  action_reason                STRING,
  days_since_training          INT64,
  computed_at                  TIMESTAMP,

  -- Directional splits (Session 366)
  rolling_hr_over_7d   FLOAT64,
  rolling_hr_under_7d  FLOAT64,
  rolling_n_over_7d    INT64,
  rolling_n_under_7d   INT64,
  rolling_hr_over_14d  FLOAT64,
  rolling_hr_under_14d FLOAT64,
  rolling_n_over_14d   INT64,
  rolling_n_under_14d  INT64,

  -- Best bets post-filter metrics (Session 366)
  best_bets_hr_14d         FLOAT64,
  best_bets_hr_21d         FLOAT64,
  best_bets_n_14d          INT64,
  best_bets_n_21d          INT64,
  best_bets_over_hr_21d    FLOAT64,
  best_bets_under_hr_21d   FLOAT64,
  best_bets_filter_pass_rate FLOAT64,

  -- Brier score calibration (Session 399)
  brier_score_7d  FLOAT64,
  brier_score_14d FLOAT64,
  brier_score_30d FLOAT64,

  -- Pipeline candidate metrics (Session 443)
  pipeline_candidates    INT64,
  pipeline_selected      INT64,
  pipeline_hr_21d        FLOAT64,
  pipeline_over_hr_21d   FLOAT64,
  pipeline_under_hr_21d  FLOAT64,
  pipeline_n_graded_21d  INT64,

  -- Bias and MAE tracking (Session 545, 2025-26 anomaly follow-up)
  -- pred_bias is AVG(predicted - actual): negative = under-prediction.
  -- mae_gap is model_mae - vegas_mae: positive = model worse than Vegas.
  -- Both intended as diagnostic columns. Primary alerting on mae_gap_*
  -- (per docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/01-MONITORING-PLAN.md).
  pred_bias_7d   FLOAT64,
  pred_bias_14d  FLOAT64,
  pred_bias_30d  FLOAT64,
  model_mae_7d   FLOAT64,
  model_mae_14d  FLOAT64,
  model_mae_30d  FLOAT64,
  vegas_mae_7d   FLOAT64,
  vegas_mae_14d  FLOAT64,
  vegas_mae_30d  FLOAT64,
  mae_gap_7d     FLOAT64,
  mae_gap_14d    FLOAT64,
  mae_gap_30d    FLOAT64
)
PARTITION BY game_date
CLUSTER BY model_id
OPTIONS (
  description='Daily rolling per-model performance metrics. Hit rates, decay state, '
              'best bets post-filter HR, Brier calibration, pipeline candidates, and '
              'bias/MAE drift tracking. Written daily by ml/analysis/model_performance.py.'
);
