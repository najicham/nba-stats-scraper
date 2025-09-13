-- File: schemas/bigquery/nbac_referee_tables.sql
-- Description: BigQuery table schemas for NBA.com referee assignment data

-- Main table for game referee assignments
-- Each row represents one official assigned to a game
CREATE TABLE IF NOT EXISTS `nba_raw.nbac_referee_game_assignments` (
  -- Core game identifiers
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  season STRING NOT NULL,
  game_code STRING NOT NULL,
  
  -- Team information
  home_team_id INT64 NOT NULL,
  home_team STRING NOT NULL,
  home_team_abbr STRING NOT NULL,
  away_team_id INT64 NOT NULL,
  away_team STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  
  -- Official information
  official_position INT64 NOT NULL,  -- 1, 2, 3, or 4
  official_name STRING NOT NULL,
  official_code INT64 NOT NULL,
  official_jersey_number STRING,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_date, official_code, home_team_abbr
OPTIONS (
  description = "NBA game referee assignments - one row per official per game",
  require_partition_filter = true
);

-- Table for replay center officials (separate workflow)
CREATE TABLE IF NOT EXISTS `nba_raw.nbac_referee_replay_center` (
  -- Date identifier
  game_date DATE NOT NULL,
  
  -- Replay center official information  
  official_code INT64 NOT NULL,
  official_name STRING NOT NULL,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_date, official_code
OPTIONS (
  description = "NBA replay center officials by date",
  require_partition_filter = true
);

-- Helpful views for common queries
CREATE OR REPLACE VIEW `nba_raw.nbac_referee_game_assignments_recent` AS
SELECT *
FROM `nba_raw.nbac_referee_game_assignments`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

CREATE OR REPLACE VIEW `nba_raw.nbac_referee_assignments_summary` AS
SELECT 
  game_date,
  game_id,
  home_team_abbr,
  away_team_abbr,
  STRING_AGG(official_name, ' | ' ORDER BY official_position) as all_officials,
  COUNT(*) as official_count
FROM `nba_raw.nbac_referee_game_assignments`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
ORDER BY game_date DESC;