-- ============================================================================
-- Model Profile Daily Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: model_profile_daily
-- Purpose: Per-model performance profiles across 6 dimensions (direction,
--          tier, line_range, edge_band, home_away, signal). Used for
--          data-driven per-model filtering and monitoring.
--          One row per model per dimension-slice per day (~220 rows/day).
-- Created: 2026-03-01 (Session 384)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.model_profile_daily` (
  -- Partition key
  game_date DATE NOT NULL,

  -- Model identification
  model_id STRING NOT NULL,                -- individual system_id
  affinity_group STRING,                   -- v9/v9_low_vegas/v12_noveg/v12_vegas (fallback grouping)

  -- Dimension slice
  dimension STRING NOT NULL,               -- 'direction', 'tier', 'line_range', 'edge_band', 'home_away', 'signal'
  dimension_value STRING NOT NULL,         -- 'OVER', 'starter', '15_20', '3_5', 'HOME', 'high_edge'

  -- 14-day rolling performance
  hr_14d FLOAT64,
  n_14d INT64,
  wins_14d INT64,
  losses_14d INT64,

  -- Best bets performance in this slice
  bb_hr_14d FLOAT64,
  bb_n_14d INT64,

  -- Blocking decision
  is_blocked BOOLEAN DEFAULT FALSE,        -- hr_14d < 45% AND n_14d >= 15
  block_reason STRING,                     -- human-readable reason for block

  -- Metadata
  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY model_id, dimension
OPTIONS (
  require_partition_filter=TRUE,
  description='Per-model daily performance profiles across 6 dimensions. '
              'Used for data-driven per-model filtering (replacing hardcoded model-family filters). '
              'Blocking threshold: hr_14d < 45% AND n_14d >= 15. '
              'Dimensions: direction, tier, line_range, edge_band, home_away, signal.'
);
