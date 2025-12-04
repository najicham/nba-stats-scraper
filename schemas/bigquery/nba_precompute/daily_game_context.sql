-- ============================================================================
-- Daily Game Context Table Schema
-- ============================================================================
-- Dataset: nba_precompute
-- Table: daily_game_context
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_precompute.daily_game_context` (
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  referee_crew_id STRING,
  chief_referee STRING,
  referee_avg_points_per_game NUMERIC(5, 1),
  referee_avg_pace NUMERIC(5, 1),
  projected_pace NUMERIC(5, 1),
  pace_differential NUMERIC(5, 1),
  home_rest_advantage INTEGER,
  rest_asymmetry_significant BOOLEAN,
  game_total NUMERIC(5, 1),
  over_under_movement NUMERIC(4, 1),
  data_quality_tier STRING,
  created_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY DAY(game_date)
CLUSTER BY game_id;
