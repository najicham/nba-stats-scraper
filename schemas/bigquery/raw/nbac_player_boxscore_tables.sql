-- File: schemas/bigquery/nbac_player_boxscore_tables.sql
-- Description: BigQuery table schemas for NBA.com player boxscore data
-- NBA.com Player Boxscore Tables
-- Official NBA player statistics for prop validation and enhanced analysis

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_player_boxscores` (
  -- Core identifiers
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  season_type STRING,
  
  -- Game context
  nba_game_id STRING NOT NULL,
  game_code STRING,
  game_status STRING,
  period INT64,
  is_playoff_game BOOLEAN,
  
  -- Team information
  home_team_id INT64,
  home_team_abbr STRING NOT NULL,
  home_team_score INT64,
  away_team_id INT64,
  away_team_abbr STRING NOT NULL,
  away_team_score INT64,
  
  -- Player identification
  nba_player_id INT64 NOT NULL,
  player_full_name STRING NOT NULL,
  player_lookup STRING NOT NULL,
  team_id INT64,
  team_abbr STRING NOT NULL,
  jersey_number STRING,
  position STRING,
  starter BOOLEAN,
  
  -- Core statistics
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
  
  -- Advanced statistics
  offensive_rebounds INT64,
  defensive_rebounds INT64,
  total_rebounds INT64,
  assists INT64,
  steals INT64,
  blocks INT64,
  turnovers INT64,
  personal_fouls INT64,
  flagrant_fouls INT64,
  technical_fouls INT64,
  plus_minus INT64,
  
  -- Enhanced metrics (future implementation)
  true_shooting_pct FLOAT64,
  effective_fg_pct FLOAT64,
  usage_rate FLOAT64,
  offensive_rating FLOAT64,
  defensive_rating FLOAT64,
  pace FLOAT64,
  pie FLOAT64,
  
  -- Quarter breakdown (future implementation)
  points_q1 INT64,
  points_q2 INT64,
  points_q3 INT64,
  points_q4 INT64,
  points_ot INT64,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  created_at TIMESTAMP NOT NULL,

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,  -- SHA256 hash of meaningful fields: game_id, player_lookup, points, rebounds, assists, minutes, field_goals_made, field_goals_attempted

  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date
OPTIONS (
  description = "Official NBA.com enhanced player statistics for prop validation and cross-source analysis. Provides detailed player performance data as alternative to Ball Don't Lie box scores with official NBA.com player IDs and enhanced statistical categories. Uses smart idempotency to skip redundant writes when stats unchanged.",
  require_partition_filter = true
);

-- View for recent games (commonly used for prop analysis)
CREATE OR REPLACE VIEW `nba_raw.nbac_player_boxscores_recent` AS
SELECT *
FROM `nba_raw.nbac_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for active players only (excludes DNP/inactive)
CREATE OR REPLACE VIEW `nba_raw.nbac_player_boxscores_active` AS
SELECT *
FROM `nba_raw.nbac_player_boxscores`
WHERE minutes IS NOT NULL AND minutes != '0:00';

-- View for prop validation (clean data for joining with odds)
CREATE OR REPLACE VIEW `nba_raw.nbac_player_boxscores_prop_validation` AS
SELECT 
  game_id,
  game_date,
  player_lookup,
  player_full_name,
  team_abbr,
  points,
  total_rebounds,
  assists,
  minutes,
  starter,
  processed_at
FROM `nba_raw.nbac_player_boxscores`
WHERE points IS NOT NULL  -- Only include players who actually played
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY);

-- Cross-validation view comparing NBA.com vs Ball Don't Lie
CREATE OR REPLACE VIEW `nba_raw.player_boxscore_comparison` AS
SELECT 
  n.game_id,
  n.game_date,
  n.player_lookup,
  n.player_full_name,
  n.team_abbr,
  n.points as nbac_points,
  b.points as bdl_points,
  ABS(COALESCE(n.points, 0) - COALESCE(b.points, 0)) as points_diff,
  n.total_rebounds as nbac_rebounds,
  b.rebounds as bdl_rebounds,
  ABS(COALESCE(n.total_rebounds, 0) - COALESCE(b.rebounds, 0)) as rebounds_diff,
  n.assists as nbac_assists,
  b.assists as bdl_assists,
  ABS(COALESCE(n.assists, 0) - COALESCE(b.assists, 0)) as assists_diff,
  n.minutes as nbac_minutes,
  b.minutes as bdl_minutes
FROM `nba_raw.nbac_player_boxscores` n
FULL OUTER JOIN `nba_raw.bdl_player_boxscores` b
  ON n.game_id = b.game_id AND n.player_lookup = b.player_lookup
WHERE n.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  OR b.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);

-- Quality monitoring view
CREATE OR REPLACE VIEW `nba_raw.nbac_player_boxscores_quality` AS
SELECT
  game_date,
  COUNT(*) as total_player_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT nba_player_id) as unique_players,
  ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_players_per_game,
  COUNT(CASE WHEN points IS NULL THEN 1 END) as null_points_count,
  COUNT(CASE WHEN minutes IS NULL OR minutes = '0:00' THEN 1 END) as dnp_count,
  COUNT(CASE WHEN starter = true THEN 1 END) as starters_count
FROM `nba_raw.nbac_player_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;