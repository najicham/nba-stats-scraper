-- File: schemas/bigquery/espn_boxscore_tables.sql
-- Description: BigQuery table schemas for ESPN boxscore data
-- ESPN Boxscore Tables
-- Description: ESPN boxscore data used as backup validation source for prop betting

CREATE TABLE IF NOT EXISTS `nba_raw.espn_boxscores` (
  -- Core identifiers
  game_id STRING NOT NULL,
  espn_game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  game_status STRING NOT NULL,
  period INT64,
  is_postseason BOOLEAN NOT NULL,
  
  -- Team information
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  home_team_score INT64 NOT NULL,
  away_team_score INT64 NOT NULL,
  home_team_espn_id STRING,
  away_team_espn_id STRING,
  
  -- Player information
  team_abbr STRING NOT NULL,
  player_full_name STRING NOT NULL,
  player_lookup STRING NOT NULL,
  espn_player_id STRING,
  jersey_number STRING,
  position STRING,
  starter BOOLEAN NOT NULL,
  
  -- Core statistics (points props focus)
  minutes STRING,
  points INT64,
  field_goals_made INT64,
  field_goals_attempted INT64,
  field_goal_percentage FLOAT64,
  three_pointers_made INT64,
  three_pointers_attempted INT64,
  three_point_percentage FLOAT64,
  free_throws_made INT64,
  free_throws_attempted INT64,
  free_throw_percentage FLOAT64,
  
  -- Additional statistics
  rebounds INT64,
  offensive_rebounds INT64,
  defensive_rebounds INT64,
  assists INT64,
  steals INT64,
  blocks INT64,
  turnovers INT64,
  fouls INT64,
  plus_minus INT64,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,  -- SHA256 hash of meaningful fields: game_id, player_lookup, points, rebounds, assists, field_goals_made, field_goals_attempted

  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date
OPTIONS (
  description = "ESPN boxscore data used as backup validation source for prop betting analysis. Collected during Early Morning Final Check workflow (5 AM PT) as alternative to Ball Don't Lie and NBA.com sources. Uses smart idempotency to skip redundant writes when stats unchanged.",
  require_partition_filter = true
);

-- Helpful views for common queries
CREATE OR REPLACE VIEW `nba_raw.espn_boxscores_recent` AS
SELECT *
FROM `nba_raw.espn_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for prop validation (points only)
CREATE OR REPLACE VIEW `nba_raw.espn_boxscores_prop_validation` AS
SELECT 
  game_id,
  game_date,
  player_lookup,
  player_full_name,
  team_abbr,
  points,
  assists,
  rebounds,
  source_file_path
FROM `nba_raw.espn_boxscores`
WHERE points IS NOT NULL
  AND player_lookup != ''
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY);

-- Cross-validation view (ESPN vs Ball Don't Lie)
CREATE OR REPLACE VIEW `nba_raw.boxscores_cross_validation` AS
SELECT 
  COALESCE(b.game_id, e.game_id) as game_id,
  COALESCE(b.player_lookup, e.player_lookup) as player_lookup,
  COALESCE(b.player_full_name, e.player_full_name) as player_name,
  b.points as bdl_points,
  e.points as espn_points,
  ABS(COALESCE(b.points, 0) - COALESCE(e.points, 0)) as points_diff,
  CASE 
    WHEN b.points IS NOT NULL AND e.points IS NOT NULL THEN 'both_sources'
    WHEN b.points IS NOT NULL THEN 'bdl_only'
    WHEN e.points IS NOT NULL THEN 'espn_only'
    ELSE 'no_data'
  END as data_availability
FROM `nba_raw.bdl_player_boxscores` b
FULL OUTER JOIN `nba_raw.espn_boxscores` e
  ON b.game_id = e.game_id AND b.player_lookup = e.player_lookup
WHERE COALESCE(b.game_date, e.game_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);