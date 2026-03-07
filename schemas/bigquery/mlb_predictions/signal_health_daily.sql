-- ============================================================================
-- MLB Signal Health Daily Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: signal_health_daily
-- Purpose: Daily multi-timeframe performance tracking for each signal.
--          Used for monitoring and frontend transparency, NOT blocking.
--          Modeled after nba_predictions.signal_health_daily.
-- Created: 2026-03-06
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.signal_health_daily` (
  game_date DATE NOT NULL,
  signal_tag STRING NOT NULL,                   -- Signal identifier (e.g., 'high_k_rate', 'bullpen_fatigue')

  -- Multi-timeframe performance
  hr_7d FLOAT64,                                -- 7-day hit rate
  hr_14d FLOAT64,                               -- 14-day hit rate
  hr_30d FLOAT64,                               -- 30-day hit rate
  hr_season FLOAT64,                            -- Season-to-date hit rate
  picks_7d INT64,                               -- 7-day sample count
  picks_14d INT64,                              -- 14-day sample count
  picks_30d INT64,                              -- 30-day sample count
  picks_season INT64,                           -- Season-to-date sample count

  -- Divergence metrics (short-term vs long-term drift)
  divergence_7d_vs_season FLOAT64,              -- hr_7d - hr_season
  divergence_14d_vs_season FLOAT64,             -- hr_14d - hr_season

  -- Regime classification
  regime STRING,                                -- HOT | NORMAL | COLD

  -- Status (for alerting, NOT for blocking)
  status STRING,                                -- HEALTHY | WATCH | DEGRADING

  days_in_current_regime INT64,                 -- Consecutive days in current regime

  -- Directional splits (OVER/UNDER)
  hr_over_7d FLOAT64,
  hr_under_7d FLOAT64,
  hr_over_30d FLOAT64,
  hr_under_30d FLOAT64,
  picks_over_7d INT64,
  picks_under_7d INT64,
  picks_over_30d INT64,
  picks_under_30d INT64,

  -- Signal classification
  is_model_dependent BOOLEAN,                   -- TRUE if signal depends on model output (e.g., high_edge)

  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY signal_tag
OPTIONS (
  require_partition_filter=TRUE,
  description='Daily MLB signal health metrics. Multi-timeframe hit rates and regime classification '
              'for pitcher strikeout signals. For monitoring and frontend transparency, NOT for '
              'blocking picks. COLD regime signals may predict poor HR.'
);
