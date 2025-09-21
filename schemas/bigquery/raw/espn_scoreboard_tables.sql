-- File: schemas/bigquery/espn_scoreboard_tables.sql
-- Description: BigQuery table schemas for ESPN scoreboard data
-- ESPN Scoreboard Tables
-- Backup validation source for final game scores

CREATE TABLE IF NOT EXISTS `nba_raw.espn_scoreboard` (
  -- Core identifiers
  game_id STRING NOT NULL,
  espn_game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  
  -- Team information
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  home_team_name STRING NOT NULL,
  away_team_name STRING NOT NULL,
  home_team_espn_id STRING NOT NULL,
  away_team_espn_id STRING NOT NULL,
  home_team_espn_abbr STRING NOT NULL,  -- Original ESPN abbreviation
  away_team_espn_abbr STRING NOT NULL,  -- Original ESPN abbreviation
  
  -- Game status
  game_status STRING NOT NULL,          -- Normalized: "final", "scheduled" 
  game_status_detail STRING NOT NULL,   -- Original ESPN status
  espn_status_id STRING NOT NULL,       -- ESPN statusId field
  espn_state STRING NOT NULL,           -- ESPN state field  
  is_completed BOOLEAN NOT NULL,
  scheduled_start_time TIMESTAMP,       -- Game start time
  
  -- Scoring
  home_team_score INT64 NOT NULL,
  away_team_score INT64 NOT NULL,
  home_team_winner BOOLEAN NOT NULL,
  away_team_winner BOOLEAN NOT NULL,
  
  -- Processing metadata
  scrape_timestamp TIMESTAMP NOT NULL,  -- When ESPN data was scraped
  source_file_path STRING NOT NULL,
  processing_confidence FLOAT64 NOT NULL,
  data_quality_flags STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, game_status
OPTIONS (
  description = "ESPN scoreboard data - backup validation source for final game scores. Part of Early Morning Final Check workflow.",
  require_partition_filter = true
);

-- View for recent games (last 30 days)
CREATE OR REPLACE VIEW `nba_raw.espn_scoreboard_recent` AS
SELECT *
FROM `nba_raw.espn_scoreboard`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for completed games only
CREATE OR REPLACE VIEW `nba_raw.espn_scoreboard_final` AS
SELECT *
FROM `nba_raw.espn_scoreboard`
WHERE is_completed = TRUE;

-- View for cross-validation with other sources
CREATE OR REPLACE VIEW `nba_raw.espn_scoreboard_validation` AS
SELECT 
  game_id,
  game_date,
  home_team_abbr,
  away_team_abbr,
  home_team_score,
  away_team_score,
  'ESPN' as data_source,
  processing_confidence
FROM `nba_raw.espn_scoreboard`
WHERE is_completed = TRUE
  AND processing_confidence >= 0.8;