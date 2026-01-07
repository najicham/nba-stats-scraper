-- ============================================================================
-- MLB Lineups Tables (from MLB Stats API)
-- Starting batting lineups for bottom-up strikeout model
-- File: schemas/bigquery/mlb_raw/mlb_lineups_tables.sql
-- ============================================================================
--
-- Source: MLB Stats API - /api/v1/game/{gamePk}/boxscore
-- Scraper: scrapers/mlb/mlbstatsapi/mlb_lineups.py
--
-- CRITICAL for Bottom-Up Model:
-- - Provides the 9 batters in starting lineup
-- - We sum their individual K rates to predict pitcher Ks
-- - Lineups typically available 1-2 hours before game
--
-- Schema: Two tables for normalized data
-- 1. mlb_game_lineups - One row per game with lineup metadata
-- 2. mlb_lineup_batters - One row per batter in lineup (denormalized)
-- ============================================================================

-- ============================================================================
-- TABLE 1: Game Lineup Summary
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_game_lineups` (
  -- Game identifiers
  game_pk INT64 NOT NULL,                     -- MLB authoritative game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  game_time_utc TIMESTAMP,                    -- Scheduled start time

  -- Teams
  away_team_id INT64 NOT NULL,
  away_team_name STRING,
  away_team_abbr STRING NOT NULL,
  home_team_id INT64 NOT NULL,
  home_team_name STRING,
  home_team_abbr STRING NOT NULL,

  -- Venue
  venue_name STRING,

  -- Status
  status_code STRING,
  lineups_available BOOL NOT NULL,            -- Are lineups posted?

  -- Lineup counts (for validation)
  away_lineup_count INT64,                    -- Should be 9 when complete
  home_lineup_count INT64,                    -- Should be 9 when complete

  -- Processing metadata
  source_file_path STRING NOT NULL,
  scraped_at TIMESTAMP NOT NULL,              -- When we scraped this data
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_pk, away_team_abbr, home_team_abbr
OPTIONS (
  description = "MLB game lineup summary. One row per game with lineup availability status.",
  require_partition_filter = true
);

-- ============================================================================
-- TABLE 2: Individual Batters in Lineup (Denormalized for Easy Queries)
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_lineup_batters` (
  -- Game identifiers
  game_pk INT64 NOT NULL,                     -- MLB game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)

  -- Team
  team_abbr STRING NOT NULL,                  -- Which team this batter is on
  is_home BOOL NOT NULL,                      -- Home or away team

  -- Batter identifiers
  player_id INT64 NOT NULL,                   -- MLB player ID
  player_name STRING NOT NULL,                -- Full name
  player_lookup STRING NOT NULL,              -- Normalized for joins

  -- Lineup position (CRITICAL!)
  batting_order INT64 NOT NULL,               -- 1-9 position in lineup
  position STRING,                            -- Fielding position (C, 1B, SS, etc.)
  position_name STRING,                       -- Full position name

  -- Opponent (for K rate context)
  opponent_team_abbr STRING NOT NULL,         -- Team they're facing
  opponent_pitcher_id INT64,                  -- Pitcher they're facing (from schedule)
  opponent_pitcher_name STRING,               -- Pitcher name

  -- Processing metadata
  source_file_path STRING,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_pk, team_abbr, batting_order
OPTIONS (
  description = "MLB lineup batters. One row per batter per game. Critical for bottom-up strikeout model.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Today's lineups
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_todays_lineups` AS
SELECT
  gl.game_pk,
  gl.game_time_utc,
  gl.away_team_abbr,
  gl.home_team_abbr,
  gl.venue_name,
  gl.lineups_available,
  gl.away_lineup_count,
  gl.home_lineup_count
FROM `nba-props-platform.mlb_raw.mlb_game_lineups` gl
WHERE gl.game_date = CURRENT_DATE()
ORDER BY gl.game_time_utc;

-- Full lineup for a specific game (join with batters)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_full_lineups` AS
SELECT
  lb.game_pk,
  lb.game_date,
  lb.team_abbr,
  lb.is_home,
  lb.batting_order,
  lb.player_id,
  lb.player_name,
  lb.player_lookup,
  lb.position,
  lb.opponent_team_abbr,
  lb.opponent_pitcher_name
FROM `nba-props-platform.mlb_raw.mlb_lineup_batters` lb
WHERE lb.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY lb.game_pk, lb.is_home DESC, lb.batting_order;

-- Games ready for bottom-up prediction (have both lineups)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_games_ready_for_bottom_up` AS
SELECT
  gl.game_pk,
  gl.game_date,
  gl.game_time_utc,
  gl.away_team_abbr,
  gl.home_team_abbr,
  gl.away_lineup_count,
  gl.home_lineup_count
FROM `nba-props-platform.mlb_raw.mlb_game_lineups` gl
WHERE gl.game_date >= CURRENT_DATE()
  AND gl.away_lineup_count = 9
  AND gl.home_lineup_count = 9
  AND gl.status_code NOT IN ('F', 'FT')  -- Not final
ORDER BY gl.game_time_utc;

-- Lineup availability monitoring
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_lineup_availability` AS
SELECT
  game_date,
  COUNT(*) as total_games,
  COUNTIF(lineups_available) as games_with_lineups,
  COUNTIF(away_lineup_count = 9 AND home_lineup_count = 9) as games_complete_lineups,
  AVG(away_lineup_count) as avg_away_lineup_size,
  AVG(home_lineup_count) as avg_home_lineup_size
FROM `nba-props-platform.mlb_raw.mlb_game_lineups`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Batter lineup frequency (who bats in which order most often)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.mlb_batter_lineup_patterns` AS
SELECT
  player_lookup,
  player_name,
  team_abbr,
  COUNT(*) as games_in_lineup,
  ROUND(AVG(batting_order), 1) as avg_batting_order,
  MODE(batting_order) as most_common_order,
  STRING_AGG(DISTINCT position) as positions_played
FROM `nba-props-platform.mlb_raw.mlb_lineup_batters`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY player_lookup, player_name, team_abbr
HAVING COUNT(*) >= 5
ORDER BY games_in_lineup DESC;
