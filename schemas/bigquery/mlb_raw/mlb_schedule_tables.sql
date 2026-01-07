-- ============================================================================
-- MLB Schedule Tables (from MLB Stats API)
-- Daily game schedule with probable pitchers
-- File: schemas/bigquery/mlb_raw/mlb_schedule_tables.sql
-- ============================================================================
--
-- Source: MLB Stats API - /api/v1/schedule
-- Scraper: scrapers/mlb/mlbstatsapi/mlb_schedule.py
--
-- CRITICAL for Predictions:
-- - Tells us which games are happening (orchestration)
-- - Provides probable pitchers (who we're predicting Ks for)
-- - Game context for features (venue, day/night, home/away)
--
-- Key Fields:
-- - game_pk: MLB authoritative game ID
-- - away_probable_pitcher_id/name: Starting pitcher (away team)
-- - home_probable_pitcher_id/name: Starting pitcher (home team)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_schedule` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_pk INT64 NOT NULL,                     -- MLB authoritative game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  game_time_utc TIMESTAMP,                    -- Scheduled start time (UTC)
  season INT64 NOT NULL,                      -- Season year
  game_type STRING NOT NULL,                  -- R=Regular, P=Postseason, S=Spring

  -- ============================================================================
  -- TEAMS
  -- ============================================================================
  away_team_id INT64 NOT NULL,
  away_team_name STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  home_team_id INT64 NOT NULL,
  home_team_name STRING NOT NULL,
  home_team_abbr STRING NOT NULL,

  -- ============================================================================
  -- PROBABLE PITCHERS (CRITICAL FOR PREDICTIONS!)
  -- ============================================================================
  away_probable_pitcher_id INT64,             -- Pitcher ID (NULL if not announced)
  away_probable_pitcher_name STRING,          -- Pitcher full name
  away_probable_pitcher_number STRING,        -- Jersey number
  home_probable_pitcher_id INT64,             -- Pitcher ID (NULL if not announced)
  home_probable_pitcher_name STRING,          -- Pitcher full name
  home_probable_pitcher_number STRING,        -- Jersey number

  -- ============================================================================
  -- VENUE & CONTEXT
  -- ============================================================================
  venue_id INT64,
  venue_name STRING,
  day_night STRING,                           -- 'day' or 'night'
  series_description STRING,                  -- e.g., "Regular Season"
  games_in_series INT64,                      -- Total games in series
  series_game_number INT64,                   -- Game N of series

  -- ============================================================================
  -- GAME STATUS
  -- ============================================================================
  status_code STRING,                         -- S=Scheduled, I=In Progress, F=Final
  status_detailed STRING,                     -- Detailed status text
  is_final BOOL NOT NULL,                     -- Game completed

  -- ============================================================================
  -- FINAL SCORES (for completed games)
  -- ============================================================================
  away_score INT64,
  home_score INT64,
  away_hits INT64,
  home_hits INT64,

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,
  data_hash STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_pk, away_team_abbr, home_team_abbr
OPTIONS (
  description = "MLB game schedule from official MLB Stats API. Contains probable pitchers - critical for strikeout predictions.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Today's games with probable pitchers
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_todays_games` AS
SELECT
  game_pk,
  game_time_utc,
  away_team_abbr,
  home_team_abbr,
  away_probable_pitcher_name,
  home_probable_pitcher_name,
  venue_name,
  day_night,
  status_detailed
FROM `nba-props-platform.mlb_raw.mlb_schedule`
WHERE game_date = CURRENT_DATE()
ORDER BY game_time_utc;

-- Games with both probable pitchers announced (ready for predictions)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_games_ready_for_predictions` AS
SELECT *
FROM `nba-props-platform.mlb_raw.mlb_schedule`
WHERE game_date >= CURRENT_DATE()
  AND away_probable_pitcher_id IS NOT NULL
  AND home_probable_pitcher_id IS NOT NULL
  AND is_final = FALSE
ORDER BY game_date, game_time_utc;

-- Recent schedule quality monitoring
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_schedule_quality` AS
SELECT
  game_date,
  COUNT(*) as total_games,
  COUNT(away_probable_pitcher_id) as games_with_away_starter,
  COUNT(home_probable_pitcher_id) as games_with_home_starter,
  COUNTIF(away_probable_pitcher_id IS NOT NULL AND home_probable_pitcher_id IS NOT NULL) as games_both_starters,
  COUNTIF(is_final) as games_final
FROM `nba-props-platform.mlb_raw.mlb_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Starting pitcher frequency (who starts most often)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_starter_frequency` AS
WITH all_starters AS (
  SELECT away_probable_pitcher_id as pitcher_id, away_probable_pitcher_name as pitcher_name, away_team_abbr as team_abbr
  FROM `nba-props-platform.mlb_raw.mlb_schedule`
  WHERE away_probable_pitcher_id IS NOT NULL AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  UNION ALL
  SELECT home_probable_pitcher_id, home_probable_pitcher_name, home_team_abbr
  FROM `nba-props-platform.mlb_raw.mlb_schedule`
  WHERE home_probable_pitcher_id IS NOT NULL AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  pitcher_id,
  pitcher_name,
  team_abbr,
  COUNT(*) as starts_last_30_days
FROM all_starters
GROUP BY pitcher_id, pitcher_name, team_abbr
ORDER BY starts_last_30_days DESC;
