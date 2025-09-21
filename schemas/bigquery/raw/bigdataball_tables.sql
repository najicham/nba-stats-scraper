-- File: schemas/bigquery/bigdataball_tables.sql
-- Description: BigQuery table schemas for BigDataBall play-by-play data
-- BigDataBall Play-by-Play Tables
-- Enhanced play-by-play data with complete lineup tracking and advanced coordinates

CREATE TABLE IF NOT EXISTS `nba_raw.bigdataball_play_by_play` (
  -- Core Game Identifiers (consistent with other processors)
  game_id STRING NOT NULL,                    -- Format: "20241101_NYK_DET" 
  bdb_game_id INT64,                          -- BigDataBall source game ID: 22400134
  game_date DATE NOT NULL,                    -- Game date (PARTITION KEY)
  season_year INT64 NOT NULL,                 -- Starting year (2024 for 2024-25 season)
  data_set STRING,                            -- "NBA 2024-2025 Regular Season"
  home_team_abbr STRING NOT NULL,             -- Three-letter code "DET"
  away_team_abbr STRING NOT NULL,             -- Three-letter code "NYK"
  
  -- Event Identifiers (consistent with NBA.com processor pattern)
  event_id STRING NOT NULL,                   -- Constructed: "{game_id}_{play_id}"
  event_sequence INT64 NOT NULL,              -- BigDataBall play_id (1, 2, 3...)
  period INT64,                               -- Quarter/period (1-4 regular, 5+ OT)
  
  -- Game Clock (enhanced vs NBA.com - BigDataBall's richer time data)
  game_clock STRING,                          -- remaining_time: "0:11:40"
  game_clock_seconds INT64,                   -- Converted remaining time to seconds
  elapsed_time STRING,                        -- elapsed: "0:00:31" (unique to BigDataBall)
  elapsed_seconds INT64,                      -- Converted elapsed time to seconds
  play_length STRING,                         -- play_length: "0:00:08" (unique to BigDataBall)
  play_length_seconds INT64,                  -- Converted play duration to seconds
  
  -- Event Details (consistent pattern with NBA.com processor)
  event_type STRING,                          -- "shot", "rebound", "turnover"
  event_subtype STRING,                       -- "3pt jump shot", "rebound defensive"
  event_description STRING,                   -- Full text description
  
  -- Score Tracking (consistent naming with NBA.com processor)
  score_home INT64,                           -- Home team score after event
  score_away INT64,                           -- Away team score after event
  
  -- Event Participants (consistent with NBA.com processor pattern)
  player_1_name STRING,                       -- Primary player: "Tim Hardaway Jr."
  player_1_lookup STRING,                     -- Normalized: "timhardawayjr"
  player_1_team_abbr STRING,                  -- Player's team context
  
  player_2_name STRING,                       -- Secondary player (assister, etc.)
  player_2_lookup STRING,                     -- Normalized for joins
  player_2_team_abbr STRING,                  -- Team context
  player_2_role STRING,                       -- "assist", "block", "jump_ball_away", etc.
  
  player_3_name STRING,                       -- Tertiary player (rare events)
  player_3_lookup STRING,                     -- Normalized for joins
  player_3_team_abbr STRING,                  -- Team context
  player_3_role STRING,                       -- "jump_ball_home", "substitution_out", etc.
  
  -- Shot Details (consistent with NBA.com processor)
  shot_made BOOLEAN,                          -- TRUE if shot made
  shot_type STRING,                           -- "2PT", "3PT", "FT"
  shot_distance FLOAT64,                      -- Distance in feet (from BigDataBall)
  points_scored INT64,                        -- Points awarded (0, 2, 3)
  
  -- Shot Coordinates (enhanced vs NBA.com - dual coordinate systems)
  original_x FLOAT64,                         -- NBA's original coordinates
  original_y FLOAT64,                         -- NBA's original coordinates
  converted_x FLOAT64,                        -- BigDataBall's converted coordinates
  converted_y FLOAT64,                        -- BigDataBall's converted coordinates
  
  -- Lineup Data (major enhancement vs NBA.com - full 10-player tracking)
  away_player_1_lookup STRING,               -- Away team player 1: "karlanthonytowns"
  away_player_2_lookup STRING,               -- Away team player 2: "mikalbridges"
  away_player_3_lookup STRING,               -- Away team player 3: "jalenbrunson"
  away_player_4_lookup STRING,               -- Away team player 4: "joshhart"
  away_player_5_lookup STRING,               -- Away team player 5: "ogananoby"
  home_player_1_lookup STRING,               -- Home team player 1: "jalenduren"
  home_player_2_lookup STRING,               -- Home team player 2: "cadecunningham"
  home_player_3_lookup STRING,               -- Home team player 3: "timhardawayjr"
  home_player_4_lookup STRING,               -- Home team player 4: "jadenivey"
  home_player_5_lookup STRING,               -- Home team player 5: "tobiasharris"
  
  -- Additional BigDataBall Fields (unique data not in NBA.com)
  possession_player_name STRING,             -- Possession context player
  possession_player_lookup STRING,           -- Normalized possession player
  reason STRING,                             -- Foul reasons, etc.
  opponent STRING,                           -- Opponent context
  num STRING,                                -- Jersey numbers, etc.
  outof STRING,                              -- Shooting fouls context
  
  -- Processing Metadata (consistent with all processors)
  source_file_path STRING NOT NULL,          -- GCS path to source CSV
  csv_filename STRING,                       -- Original CSV filename from Google Drive
  csv_row_number INT64,                      -- Row number in source CSV
  processed_at TIMESTAMP NOT NULL,           -- Processing timestamp
  created_at TIMESTAMP NOT NULL              -- When record first created
)
PARTITION BY game_date
CLUSTER BY game_id, period, event_type, away_player_1_lookup
OPTIONS (
  description = "BigDataBall enhanced play-by-play data with complete lineup tracking, dual coordinate systems, and advanced timing data for basketball analytics",
  require_partition_filter = true,
  partition_expiration_days = 2555  -- 7 years retention
);

-- Helpful views for common BigDataBall analytics queries

CREATE OR REPLACE VIEW `nba_raw.bigdataball_pbp_recent` AS
SELECT *
FROM `nba_raw.bigdataball_play_by_play`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

CREATE OR REPLACE VIEW `nba_raw.bigdataball_shots_only` AS
SELECT 
  game_id,
  game_date,
  event_sequence,
  period,
  game_clock,
  player_1_name,
  player_1_lookup,
  player_1_team_abbr,
  shot_made,
  shot_type,
  shot_distance,
  points_scored,
  original_x,
  original_y,
  converted_x,
  converted_y,
  -- Assisting player
  CASE WHEN player_2_role = 'assist' THEN player_2_name END as assist_player_name,
  CASE WHEN player_2_role = 'assist' THEN player_2_lookup END as assist_player_lookup,
  -- Score context
  score_home,
  score_away
FROM `nba_raw.bigdataball_play_by_play`
WHERE event_type = 'shot';

CREATE OR REPLACE VIEW `nba_raw.bigdataball_lineups` AS
SELECT DISTINCT
  game_id,
  game_date,
  season_year,
  home_team_abbr,
  away_team_abbr,
  -- Away lineup
  away_player_1_lookup,
  away_player_2_lookup, 
  away_player_3_lookup,
  away_player_4_lookup,
  away_player_5_lookup,
  -- Home lineup
  home_player_1_lookup,
  home_player_2_lookup,
  home_player_3_lookup, 
  home_player_4_lookup,
  home_player_5_lookup,
  -- Lineup fingerprint for grouping
  FARM_FINGERPRINT(CONCAT(
    IFNULL(away_player_1_lookup, ''), '|',
    IFNULL(away_player_2_lookup, ''), '|',
    IFNULL(away_player_3_lookup, ''), '|',
    IFNULL(away_player_4_lookup, ''), '|',
    IFNULL(away_player_5_lookup, '')
  )) as away_lineup_hash,
  FARM_FINGERPRINT(CONCAT(
    IFNULL(home_player_1_lookup, ''), '|',
    IFNULL(home_player_2_lookup, ''), '|',
    IFNULL(home_player_3_lookup, ''), '|',
    IFNULL(home_player_4_lookup, ''), '|',
    IFNULL(home_player_5_lookup, '')
  )) as home_lineup_hash
FROM `nba_raw.bigdataball_play_by_play`
WHERE away_player_1_lookup IS NOT NULL 
  AND home_player_1_lookup IS NOT NULL;