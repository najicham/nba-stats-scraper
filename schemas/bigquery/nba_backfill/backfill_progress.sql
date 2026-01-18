-- NBA Backfill Progress Tracking Table
-- Tracks completion status of Phase 3 and Phase 4 backfill by date
-- Created: 2026-01-17

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_backfill.backfill_progress` (
  -- Primary key
  game_date DATE NOT NULL,

  -- Phase 3 (Analytics) status
  phase3_complete BOOLEAN DEFAULT FALSE,
  phase3_pgs_complete BOOLEAN DEFAULT FALSE,  -- player_game_summary
  phase3_togs_complete BOOLEAN DEFAULT FALSE, -- team_offense_game_summary
  phase3_tdgs_complete BOOLEAN DEFAULT FALSE, -- team_defense_game_summary
  phase3_upgc_complete BOOLEAN DEFAULT FALSE, -- upcoming_player_game_context
  phase3_utgc_complete BOOLEAN DEFAULT FALSE, -- upcoming_team_game_context

  -- Phase 4 (Precompute) status
  phase4_complete BOOLEAN DEFAULT FALSE,
  phase4_tdza_complete BOOLEAN DEFAULT FALSE, -- team_defensive_zone_analytics
  phase4_psza_complete BOOLEAN DEFAULT FALSE, -- player_shot_zone_analytics
  phase4_pdc_complete BOOLEAN DEFAULT FALSE,  -- player_defensive_context
  phase4_pcf_complete BOOLEAN DEFAULT FALSE,  -- player_composite_factors
  phase4_mlfs_complete BOOLEAN DEFAULT FALSE, -- ml_feature_store

  -- Metadata
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  phase3_started_at TIMESTAMP,
  phase3_completed_at TIMESTAMP,
  phase4_started_at TIMESTAMP,
  phase4_completed_at TIMESTAMP,

  -- Error tracking
  phase3_error_count INT64 DEFAULT 0,
  phase4_error_count INT64 DEFAULT 0,
  last_error STRING,

  -- Notes
  notes STRING
)
PARTITION BY game_date
CLUSTER BY phase3_complete, phase4_complete;

-- Create index on completion status for fast querying
-- CREATE INDEX idx_completion ON nba_backfill.backfill_progress (phase3_complete, phase4_complete);
