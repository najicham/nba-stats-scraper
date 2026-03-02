-- ============================================================================
-- Best Bets Pick Events Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: best_bets_pick_events
-- Purpose: Structured lifecycle events for picks — tracks when and why picks
--          are dropped from signal, disabled, or manually removed.
-- Created: 2026-03-02 (Session 386)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.best_bets_pick_events` (
  -- Event Identity
  event_id STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Pick Identity
  player_lookup STRING NOT NULL,
  game_id STRING,

  -- Event Details
  event_type STRING NOT NULL,           -- 'dropped_from_signal', 'model_disabled', 'manually_removed'
  event_reason STRING,                  -- Human-readable reason (e.g. 'model_disabled:xgb_v12_...')
  system_id STRING,                     -- Model that sourced the original prediction

  -- Snapshot at event time
  previous_edge NUMERIC(5, 1),
  previous_rank INT64,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, event_type
OPTIONS (
  require_partition_filter=TRUE,
  description='Structured lifecycle events for best bets picks. '
              'Tracks drops, disabled models, and manual removals for audit and debugging.'
);
