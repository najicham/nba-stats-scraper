-- ============================================================================
-- League Macro Daily Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: league_macro_daily
-- Purpose: Daily league-level macro trends for monitoring market efficiency,
--          scoring environment, and system health at a glance.
-- Created: 2026-03-08 (Session 435)
-- ============================================================================
--
-- Single row per game_date. Tracks:
-- 1. Vegas accuracy trends (is the market getting sharper?)
-- 2. Model accuracy trends (are we keeping up?)
-- 3. League scoring environment (high/low scoring affects signals)
-- 4. Edge availability (can we still find value?)
-- 5. Best bets rolling performance
--
-- Source: prediction_accuracy, player_game_summary, signal_best_bets_picks
-- Refresh: Daily after grading completes (via post_grading_export CF)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.league_macro_daily` (
  game_date DATE NOT NULL,

  -- Slate size
  games_played INT64,                    -- Number of completed games

  -- Vegas accuracy (daily + rolling)
  vegas_mae_daily FLOAT64,               -- Vegas MAE for this day
  vegas_mae_7d FLOAT64,                  -- 7-day rolling avg Vegas MAE
  vegas_mae_14d FLOAT64,                 -- 14-day rolling avg Vegas MAE

  -- Model accuracy (daily + rolling)
  model_mae_daily FLOAT64,               -- Model MAE for this day
  model_mae_7d FLOAT64,                  -- 7-day rolling avg Model MAE
  model_mae_14d FLOAT64,                 -- 14-day rolling avg Model MAE

  -- MAE gap (model - vegas; positive = model worse, negative = model better)
  mae_gap_daily FLOAT64,
  mae_gap_7d FLOAT64,
  mae_gap_14d FLOAT64,

  -- League scoring environment
  league_avg_ppg FLOAT64,                -- Avg points per player (active, >0 min)
  league_avg_ppg_7d FLOAT64,             -- 7-day rolling
  league_scoring_std FLOAT64,            -- Daily scoring variance
  league_pct_over_20 FLOAT64,            -- % of players scoring 20+ (blow-up rate)

  -- Edge availability
  avg_edge_daily FLOAT64,                -- Avg |predicted - line| for graded picks
  avg_edge_7d FLOAT64,                   -- 7-day rolling
  avg_line_daily FLOAT64,                -- Avg prop line level
  pct_edge_3plus FLOAT64,               -- % of predictions with edge >= 3

  -- Prediction volume
  total_predictions INT64,               -- Total graded predictions (catboost_v12)
  pct_over FLOAT64,                      -- % OVER recommendations

  -- Best bets rolling performance
  bb_hr_7d FLOAT64,                      -- 7-day rolling BB hit rate
  bb_n_7d INT64,                         -- 7-day BB sample size
  bb_hr_14d FLOAT64,                     -- 14-day rolling
  bb_n_14d INT64,

  -- Market regime summary
  market_regime STRING,                  -- TIGHT | NORMAL | LOOSE (based on vegas_mae_7d)

  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
OPTIONS (
  require_partition_filter=TRUE,
  description='Daily league macro trends — Vegas accuracy, scoring environment, edge availability, BB performance. '
              'Single row per date. Used for monitoring market efficiency and system health.'
);
