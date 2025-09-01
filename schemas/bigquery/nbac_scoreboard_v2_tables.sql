-- File: schemas/bigquery/nbac_scoreboard_v2_tables.sql
-- Description: BigQuery table schemas for NBA.com Scoreboard V2 data
-- NBA.com Scoreboard V2 Tables
-- Game results with basic team stats for cross-validation and team performance context

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_scoreboard_v2` (
  -- Core game identifiers
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  start_time TIMESTAMP,
  
  -- Game status
  game_status_id STRING NOT NULL,
  game_state STRING NOT NULL,
  game_status_text STRING NOT NULL,
  
  -- Home team data
  home_team_id STRING NOT NULL,
  home_team_abbr STRING NOT NULL,
  home_team_abbr_raw STRING NOT NULL,
  home_score INT64,
  
  -- Away team data  
  away_team_id STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  away_team_abbr_raw STRING NOT NULL,
  away_score INT64,
  
  -- Game outcome
  winning_team_abbr STRING,
  winning_team_side STRING,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, game_state
OPTIONS (
  description = "NBA.com Scoreboard V2 game results for cross-validation and team performance context",
  require_partition_filter = true
);

-- Helpful views for common queries
CREATE OR REPLACE VIEW `nba_raw.nbac_scoreboard_v2_recent` AS
SELECT *
FROM `nba_raw.nbac_scoreboard_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for completed games only
CREATE OR REPLACE VIEW `nba_raw.nbac_scoreboard_v2_final` AS
SELECT *
FROM `nba_raw.nbac_scoreboard_v2`
WHERE game_state = 'post' AND game_status_id = '3';

-- Team record calculation view
CREATE OR REPLACE VIEW `nba_raw.nbac_scoreboard_v2_team_records` AS
WITH team_games AS (
  SELECT 
    game_date,
    season_year,
    home_team_abbr as team_abbr,
    CASE WHEN winning_team_side = 'home' THEN 1 ELSE 0 END as wins,
    1 as games
  FROM `nba_raw.nbac_scoreboard_v2`
  WHERE game_state = 'post'
  
  UNION ALL
  
  SELECT 
    game_date,
    season_year, 
    away_team_abbr as team_abbr,
    CASE WHEN winning_team_side = 'away' THEN 1 ELSE 0 END as wins,
    1 as games
  FROM `nba_raw.nbac_scoreboard_v2`
  WHERE game_state = 'post'
)
SELECT 
  season_year,
  team_abbr,
  SUM(wins) as total_wins,
  SUM(games) - SUM(wins) as total_losses,
  SUM(games) as total_games,
  ROUND(SUM(wins) / SUM(games), 3) as win_percentage,
  MAX(game_date) as last_game_date
FROM team_games
GROUP BY season_year, team_abbr
ORDER BY season_year DESC, total_wins DESC;