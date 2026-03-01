-- ============================================================================
-- Best Bets Manual Picks Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: best_bets_manual_picks
-- Purpose: Manual overrides added via CLI. These picks are merged into the
--          export alongside algorithm picks and also written to
--          signal_best_bets_picks for grading.
-- Created: 2026-02-28
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.best_bets_manual_picks` (
  -- Primary Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Player/Team Context
  player_name STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,

  -- Pick Details
  recommendation STRING NOT NULL,      -- OVER/UNDER
  line_value NUMERIC(5, 1),
  stat STRING DEFAULT 'PTS',
  edge NUMERIC(5, 1),
  rank INT64,
  pick_angles ARRAY<STRING>,

  -- Admin Fields
  added_by STRING NOT NULL,            -- Who added this pick (e.g. 'naji')
  added_at TIMESTAMP NOT NULL,
  notes STRING,                        -- Free-form reason for the manual pick
  is_active BOOLEAN NOT NULL,               -- Soft delete: FALSE = removed

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='Manual best bets picks added via CLI. Merged into exports alongside '
              'algorithm picks. Soft-deleted via is_active=FALSE.'
);
