-- File: schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql
-- ============================================================================
-- BDL Game Scrape Attempts - Per-Game Availability Tracking
-- ============================================================================
-- Purpose: Track which specific games BDL returned on each scrape attempt.
--          This enables precise latency measurement: "We checked at 1 AM and
--          the game wasn't there. We checked at 2 AM and it was."
--
-- Created: January 21, 2026
--
-- Usage:
--   1. BDL scraper logs expected games (from schedule) vs returned games
--   2. Query this table to find first availability time per game
--   3. Calculate true latency: first_available - game_end_time
--
-- Integration Point: scrapers/balldontlie/bdl_box_scores.py
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts` (
  -- ==========================================================================
  -- SCRAPE CONTEXT
  -- ==========================================================================

  scrape_timestamp TIMESTAMP NOT NULL,
    -- When this scrape attempt occurred (UTC)
    -- This is the key for latency calculation

  execution_id STRING NOT NULL,
    -- Links to scraper_execution_log for full context
    -- Format: 8-character UUID

  workflow STRING,
    -- Which workflow triggered this scrape
    -- Examples: 'post_game_window_1', 'post_game_window_2', 'morning_recovery'

  -- ==========================================================================
  -- GAME IDENTIFICATION
  -- ==========================================================================

  game_date DATE NOT NULL,
    -- The game date being checked

  home_team STRING NOT NULL,
    -- Home team abbreviation (e.g., 'GSW', 'LAL')

  away_team STRING NOT NULL,
    -- Away team abbreviation (e.g., 'MIA', 'BOS')

  -- ==========================================================================
  -- AVAILABILITY STATUS
  -- ==========================================================================

  was_available BOOL NOT NULL,
    -- TRUE if BDL returned data for this game
    -- FALSE if game was expected but not returned

  player_count INT64,
    -- Number of player box score rows returned (NULL if not available)
    -- Useful for detecting partial data (should be ~24-30 per game)

  game_status STRING,
    -- BDL's reported game status if available
    -- Examples: 'Final', 'In Progress', NULL

  bdl_game_id INT64,
    -- BDL's internal game ID if returned
    -- Useful for debugging and cross-reference

  -- ==========================================================================
  -- EXPECTATION CONTEXT
  -- ==========================================================================

  was_expected BOOL DEFAULT TRUE,
    -- TRUE if this game was in the schedule for this date
    -- FALSE for unexpected games (rare, but possible)

  expected_start_time TIMESTAMP,
    -- When the game was scheduled to start (from schedule API)

  estimated_end_time TIMESTAMP,
    -- expected_start_time + 2.5 hours
    -- Used for latency calculation

  is_west_coast BOOL,
    -- TRUE if home team is in Pacific timezone
    -- Useful for analyzing West Coast game delays

  -- ==========================================================================
  -- METADATA
  -- ==========================================================================

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    -- Row creation timestamp
)
PARTITION BY DATE(scrape_timestamp)
CLUSTER BY game_date, home_team, was_available
OPTIONS(
  description = "Per-game tracking of BDL data availability. Each row represents one game checked during one scrape attempt. Use to calculate: when did BDL first return data for a specific game?",
  partition_expiration_days = 90
);

-- ============================================================================
-- DERIVED VIEW: First Availability Per Game
-- ============================================================================
-- Calculates when each game first appeared in BDL responses

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_bdl_first_availability` AS
SELECT
  game_date,
  home_team,
  away_team,
  CONCAT(away_team, ' @ ', home_team) AS matchup,

  -- First time we saw this game
  MIN(CASE WHEN was_available THEN scrape_timestamp END) AS first_available_at,

  -- How many times did we check before finding it?
  COUNTIF(NOT was_available) AS attempts_before_available,
  COUNT(*) AS total_attempts,

  -- First scrape attempt timestamp (whether available or not)
  MIN(scrape_timestamp) AS first_checked_at,

  -- Estimated game end for latency calculation
  MIN(estimated_end_time) AS estimated_end_time,

  -- Latency in minutes
  TIMESTAMP_DIFF(
    MIN(CASE WHEN was_available THEN scrape_timestamp END),
    MIN(estimated_end_time),
    MINUTE
  ) AS latency_minutes,

  -- Is it a west coast game?
  MAX(CASE WHEN is_west_coast THEN 1 ELSE 0 END) = 1 AS is_west_coast

FROM `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date, home_team, away_team;


-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Query 1: Find games with high latency (data came late)
/*
SELECT
  game_date,
  matchup,
  first_available_at,
  estimated_end_time,
  latency_minutes,
  ROUND(latency_minutes / 60.0, 1) AS latency_hours,
  attempts_before_available,
  is_west_coast
FROM `nba-props-platform.nba_orchestration.v_bdl_first_availability`
WHERE latency_minutes > 120  -- More than 2 hours late
ORDER BY latency_minutes DESC;
*/

-- Query 2: Timeline for a specific game
/*
SELECT
  scrape_timestamp,
  was_available,
  player_count,
  workflow
FROM `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts`
WHERE game_date = '2026-01-19'
  AND home_team = 'GSW'
  AND away_team = 'MIA'
ORDER BY scrape_timestamp;
*/

-- Query 3: Average latency by day of week and west coast flag
/*
SELECT
  EXTRACT(DAYOFWEEK FROM game_date) AS day_of_week,
  is_west_coast,
  COUNT(*) AS games,
  ROUND(AVG(latency_minutes), 0) AS avg_latency_min,
  ROUND(APPROX_QUANTILES(latency_minutes, 100)[OFFSET(50)], 0) AS p50_latency_min,
  ROUND(APPROX_QUANTILES(latency_minutes, 100)[OFFSET(90)], 0) AS p90_latency_min
FROM `nba-props-platform.nba_orchestration.v_bdl_first_availability`
WHERE first_available_at IS NOT NULL
GROUP BY day_of_week, is_west_coast
ORDER BY day_of_week, is_west_coast;
*/

-- Query 4: Games still missing data (never became available)
/*
SELECT
  game_date,
  matchup,
  first_checked_at,
  total_attempts,
  estimated_end_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), estimated_end_time, HOUR) AS hours_since_game_end
FROM `nba-props-platform.nba_orchestration.v_bdl_first_availability`
WHERE first_available_at IS NULL
  AND estimated_end_time < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
ORDER BY game_date DESC;
*/
