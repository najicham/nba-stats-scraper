-- ============================================================================
-- Signal Health Daily Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: signal_health_daily
-- Purpose: Daily multi-timeframe performance tracking for each signal.
--          Used for monitoring and frontend transparency, NOT blocking.
-- Created: 2026-02-15 (Session 259)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.signal_health_daily` (
  game_date DATE NOT NULL,
  signal_tag STRING NOT NULL,

  -- Multi-timeframe performance
  hr_7d FLOAT64,
  hr_14d FLOAT64,
  hr_30d FLOAT64,
  hr_season FLOAT64,
  picks_7d INT64,
  picks_14d INT64,
  picks_30d INT64,
  picks_season INT64,

  -- Divergence metrics (key insight from Session 257 analysis)
  divergence_7d_vs_season FLOAT64,       -- hr_7d - hr_season
  divergence_14d_vs_season FLOAT64,      -- hr_14d - hr_season

  -- Regime classification
  regime STRING,                          -- HOT | NORMAL | COLD

  -- Status (for alerting, NOT for blocking)
  status STRING,                          -- HEALTHY | WATCH | DEGRADING

  days_in_current_regime INT64,

  -- Signal family
  is_model_dependent BOOLEAN,             -- high_edge, edge_spread_optimal = TRUE

  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY signal_tag
OPTIONS (
  require_partition_filter=TRUE,
  description='Daily signal health metrics. Multi-timeframe hit rates and regime classification. '
              'For monitoring and frontend transparency, NOT for blocking picks. '
              'COLD regime (divergence < -10) predicts 39.6% HR vs NORMAL at 80.0%.'
);
