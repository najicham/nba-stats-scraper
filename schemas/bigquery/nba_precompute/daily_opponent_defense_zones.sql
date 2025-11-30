-- ============================================================================
-- Daily Opponent Defense Zones Table Schema
-- ============================================================================
-- Dataset: nba_precompute
-- Table: daily_opponent_defense_zones
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.daily_opponent_defense_zones` (
  game_date DATE NOT NULL,
  opponent_team_abbr STRING NOT NULL,
  paint_fg_pct_allowed NUMERIC(5, 3),
  paint_attempts_allowed INTEGER,
  paint_blocks INTEGER,
  mid_range_fg_pct_allowed NUMERIC(5, 3),
  mid_range_attempts_allowed INTEGER,
  mid_range_blocks INTEGER,
  three_pt_fg_pct_allowed NUMERIC(5, 3),
  three_pt_attempts_allowed INTEGER,
  three_pt_blocks INTEGER,
  defensive_rating NUMERIC(6, 2),
  opponent_points_avg NUMERIC(5, 1),
  games_in_sample INTEGER,
  data_quality_tier STRING,
  created_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY DAY(game_date)
OPTIONS(partition_expiration_days=90)
CLUSTER BY opponent_team_abbr, game_date;
