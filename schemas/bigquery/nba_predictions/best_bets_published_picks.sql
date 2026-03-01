-- ============================================================================
-- Best Bets Published Picks Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: best_bets_published_picks
-- Purpose: Locked picks that have been published to the frontend. Once a pick
--          enters this table, it ALWAYS appears in the export — even if the
--          signal pipeline later drops it from signal_best_bets_picks.
-- Created: 2026-02-28
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.best_bets_published_picks` (
  -- Primary Keys (same grain as signal_best_bets_picks)
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Player/Team Context (snapshot at publish time)
  player_name STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,

  -- Prediction Snapshot
  recommendation STRING,               -- OVER/UNDER
  line_value NUMERIC(5, 1),
  edge NUMERIC(5, 1),
  rank INT64,
  pick_angles ARRAY<STRING>,
  ultra_tier STRING,

  -- Source Tracking
  source STRING NOT NULL,              -- 'algorithm' or 'manual'
  first_published_at TIMESTAMP NOT NULL,
  last_seen_in_signal TIMESTAMP,       -- NULL if never in signal (manual-only pick)

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='Locked best bets picks. Once published, a pick persists in exports '
              'regardless of signal pipeline changes. Source of truth for "what was shown to users".'
);
