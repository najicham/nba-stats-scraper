-- ============================================================================
-- MLB Ball Don't Lie Pitcher Stats Tables
-- Per-game pitching statistics for strikeout predictions
-- File: schemas/bigquery/mlb_raw/bdl_pitcher_stats_tables.sql
-- ============================================================================
--
-- Source: Ball Don't Lie MLB API - /mlb/v1/stats
-- Scraper: scrapers/mlb/balldontlie/mlb_pitcher_stats.py
--
-- Key Fields for Strikeout Prediction:
-- - p_k: Strikeouts (TARGET VARIABLE)
-- - ip: Innings Pitched
-- - pitch_count: Total pitches thrown
-- - strikes: Strike count
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bdl_pitcher_stats` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_id STRING NOT NULL,                    -- BDL game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  season_year INT64 NOT NULL,                 -- Season year (2024, 2025, etc.)
  is_postseason BOOL NOT NULL,                -- Playoff game flag

  -- ============================================================================
  -- GAME CONTEXT
  -- ============================================================================
  home_team_abbr STRING NOT NULL,             -- Home team abbreviation
  away_team_abbr STRING NOT NULL,             -- Away team abbreviation
  home_team_score INT64,                      -- Final home team score
  away_team_score INT64,                      -- Final away team score
  venue STRING,                               -- Stadium name
  game_status STRING,                         -- Game status (Final, In Progress, etc.)

  -- ============================================================================
  -- PITCHER IDENTIFICATION
  -- ============================================================================
  bdl_player_id INT64 NOT NULL,               -- Ball Don't Lie player ID
  player_full_name STRING NOT NULL,           -- Full player name
  player_lookup STRING NOT NULL,              -- Normalized lookup key (lowercase, no spaces)
  team_abbr STRING NOT NULL,                  -- Pitcher's team abbreviation
  position STRING,                            -- Position (Starting Pitcher, Relief Pitcher, etc.)
  jersey_number STRING,                       -- Jersey number

  -- ============================================================================
  -- PITCHING STATS (CORE - for predictions)
  -- ============================================================================
  strikeouts INT64,                           -- p_k: STRIKEOUTS (TARGET VARIABLE!)
  innings_pitched NUMERIC(4,1),               -- ip: Innings pitched (e.g., 6.2)
  pitch_count INT64,                          -- Total pitches thrown
  strikes INT64,                              -- Total strikes thrown

  -- ============================================================================
  -- PITCHING STATS (EXTENDED)
  -- ============================================================================
  walks_allowed INT64,                        -- p_bb: Walks (bases on balls)
  hits_allowed INT64,                         -- p_hits: Hits allowed
  runs_allowed INT64,                         -- p_runs: Runs allowed
  earned_runs INT64,                          -- er: Earned runs
  home_runs_allowed INT64,                    -- p_hr: Home runs allowed
  era NUMERIC(5,2),                           -- Earned Run Average

  -- ============================================================================
  -- GAME RESULT
  -- ============================================================================
  win BOOL,                                   -- Pitcher got the win
  loss BOOL,                                  -- Pitcher got the loss
  save BOOL,                                  -- Pitcher got the save
  hold BOOL,                                  -- Pitcher got a hold
  blown_save BOOL,                            -- Pitcher blew the save

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,           -- GCS path to source JSON
  data_hash STRING,                           -- SHA256 hash for idempotency
  created_at TIMESTAMP NOT NULL,              -- Record creation time
  processed_at TIMESTAMP NOT NULL             -- Processing timestamp
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, game_date
OPTIONS (
  description = "MLB pitcher per-game statistics from Ball Don't Lie API. Primary source for strikeout prediction target variable (strikeouts field).",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Recent pitcher stats (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_pitcher_stats_recent` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_pitcher_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Starting pitchers only (IP >= 5.0)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_starting_pitchers` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bdl_pitcher_stats`
WHERE innings_pitched >= 5.0
  AND game_status = 'STATUS_FINAL';

-- Quality monitoring view
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_pitcher_stats_quality` AS
SELECT
  game_date,
  COUNT(*) as total_pitcher_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT player_lookup) as unique_pitchers,
  AVG(strikeouts) as avg_strikeouts,
  AVG(innings_pitched) as avg_innings,
  AVG(pitch_count) as avg_pitch_count,
  COUNT(CASE WHEN strikeouts IS NULL THEN 1 END) as null_strikeouts_count
FROM `nba-props-platform.mlb_raw.bdl_pitcher_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Strikeout leaders view (useful for model validation)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bdl_strikeout_leaders` AS
SELECT
  player_lookup,
  player_full_name,
  team_abbr,
  COUNT(*) as games,
  SUM(strikeouts) as total_strikeouts,
  AVG(strikeouts) as avg_strikeouts,
  MAX(strikeouts) as max_strikeouts,
  AVG(innings_pitched) as avg_innings,
  ROUND(SUM(strikeouts) / NULLIF(SUM(innings_pitched), 0) * 9, 2) as k_per_9
FROM `nba-props-platform.mlb_raw.bdl_pitcher_stats`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  AND innings_pitched >= 1.0
GROUP BY player_lookup, player_full_name, team_abbr
HAVING COUNT(*) >= 3
ORDER BY avg_strikeouts DESC;
