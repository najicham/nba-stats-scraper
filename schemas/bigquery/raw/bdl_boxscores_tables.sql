-- Ball Don't Lie Box Scores Tables
-- Player-focused table with comprehensive stats for prop validation

CREATE TABLE IF NOT EXISTS `nba_raw.bdl_player_boxscores` (
  -- Core identifiers
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  game_status STRING,
  period INT64,
  is_postseason BOOL NOT NULL,
  
  -- Team context
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  home_team_score INT64,
  away_team_score INT64,
  team_abbr STRING NOT NULL,
  
  -- Player identification
  player_full_name STRING NOT NULL,
  player_lookup STRING NOT NULL,
  bdl_player_id INT64,
  jersey_number STRING,
  position STRING,
  
  -- Performance stats (critical for props validation)
  minutes STRING,
  points INT64,
  assists INT64,
  rebounds INT64,
  offensive_rebounds INT64,
  defensive_rebounds INT64,
  steals INT64,
  blocks INT64,
  turnovers INT64,
  personal_fouls INT64,
  
  -- Shooting stats
  field_goals_made INT64,
  field_goals_attempted INT64,
  field_goal_pct FLOAT64,
  three_pointers_made INT64,
  three_pointers_attempted INT64,
  three_point_pct FLOAT64,
  free_throws_made INT64,
  free_throws_attempted INT64,
  free_throw_pct FLOAT64,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date
OPTIONS (
  description = "Ball Don't Lie player box scores - individual player performance by game for prop validation and settlement",
  require_partition_filter = true
);

-- Create indexes for common query patterns
CREATE OR REPLACE VIEW `nba_raw.bdl_boxscores_recent` AS
SELECT *
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for prop validation joins
CREATE OR REPLACE VIEW `nba_raw.bdl_boxscores_prop_validation` AS
SELECT
  game_id,
  game_date,
  player_lookup,
  player_full_name,
  team_abbr,
  points,
  assists,
  rebounds,
  game_status
FROM `nba_raw.bdl_player_boxscores`
WHERE game_status = 'Final'
  AND points IS NOT NULL;

-- Quality monitoring view
CREATE OR REPLACE VIEW `nba_raw.bdl_boxscores_quality_check` AS
SELECT
  game_date,
  COUNT(*) as total_player_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT player_lookup) as unique_players,
  AVG(points) as avg_points,
  COUNT(CASE WHEN points IS NULL THEN 1 END) as null_points_count,
  COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as null_team_count
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;