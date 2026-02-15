-- ============================================================================
-- Pick Signal Tags Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: pick_signal_tags
-- Purpose: Signal annotations for ALL predictions (not just curated picks).
--          Stores which signals fired on each prediction so any downstream
--          consumer (subsets, exporters, daily review) can see signal badges.
-- Created: 2026-02-14 (Session 254)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.pick_signal_tags` (
  -- Identity (one row per prediction per day)
  game_date DATE NOT NULL,
  player_lookup STRING NOT NULL,
  system_id STRING NOT NULL,
  game_id STRING,

  -- Signal evaluation results
  signal_tags ARRAY<STRING>,             -- ['high_edge', '3pt_bounce', ...] or []
  signal_count INT64,                    -- Number of qualifying signals

  -- Model health context (same for all rows on a given day)
  model_health_status STRING,            -- 'healthy', 'watch', 'blocked', 'unknown'
  model_health_hr_7d NUMERIC(5, 1),      -- Rolling 7d hit rate

  -- Metadata
  evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  version_id STRING                      -- Matches current_subset_picks version_id
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='Signal annotations for all predictions. One row per (game_date, player_lookup, system_id). '
              'Consumers LEFT JOIN this to add signal badges to any pick or subset.'
);
