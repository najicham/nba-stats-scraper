-- ============================================================================
-- NBA Props Platform - Game Referees Analytics Table
-- NBA referee assignments and basic chief referee tendencies
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.game_referees` (
  -- Core identifiers (3 fields)
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  season_year INT64 NOT NULL,                       -- Season year
  
  -- Referee assignments (3 fields)
  chief_referee STRING NOT NULL,                    -- Lead referee name
  crew_referee_1 STRING NOT NULL,                   -- Second referee name
  crew_referee_2 STRING NOT NULL,                   -- Third referee name
  
  -- Simplified chief referee tendencies (3 fields)
  chief_avg_total_points NUMERIC(5,1),              -- Historical avg total points
  chief_avg_fouls_per_game NUMERIC(4,1),            -- Historical fouls per game
  chief_games_sample_size INT64,                    -- Sample size for averages
  
  -- Source tracking (2 fields)
  refs_announced_timestamp TIMESTAMP,               -- When assignments posted
  refs_source STRING,                               -- Data source
  
  -- Processing metadata (1 field)
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_date, chief_referee
OPTIONS(
  description="NBA referee assignments and basic chief referee tendencies"
);