-- File: schemas/bigquery/nba_orchestration/scraper_data_arrival.sql
-- ============================================================================
-- Scraper Data Arrival Tracking - Unified Per-Game Availability
-- ============================================================================
-- Purpose: Track when data becomes available for each game from each scraper.
--          This generalizes the BDL-specific tracking to ALL scrapers.
--
-- Key Questions This Answers:
--   1. "When did BDL first have data for GSW @ LAL on Jan 21?"
--   2. "How many attempts before NBAC gamebook was available?"
--   3. "Which scrapers are consistently late for West Coast games?"
--   4. "What's the P90 latency for each scraper?"
--
-- Created: January 22, 2026
-- ============================================================================

-- ============================================================================
-- TABLE 1: Per-Game Per-Scraper Attempt Tracking
-- ============================================================================
-- One row per game per scraper per attempt. This is the raw data.
-- Example: BDL scraper runs at 1 AM, 2 AM, 4 AM - each is a row.

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.scraper_data_arrival` (
  -- ==========================================================================
  -- ATTEMPT CONTEXT
  -- ==========================================================================

  attempt_timestamp TIMESTAMP NOT NULL,
    -- When this scrape attempt occurred (UTC)

  scraper_name STRING NOT NULL,
    -- Which scraper: 'bdl_box_scores', 'nbac_gamebook', 'oddsa_player_props', etc.

  workflow STRING,
    -- Which workflow triggered this: 'post_game_window_1', 'morning_recovery',
    -- 'bdl_catchup_midday', etc.

  execution_id STRING,
    -- Links to scraper_execution_log for full context

  attempt_number INT64,
    -- 1st, 2nd, 3rd attempt for this game on this date
    -- Calculated based on prior attempts for same game/scraper

  -- ==========================================================================
  -- GAME IDENTIFICATION
  -- ==========================================================================

  game_date DATE NOT NULL,
    -- The game date being checked

  home_team STRING NOT NULL,
    -- Home team abbreviation (e.g., 'GSW', 'LAL')

  away_team STRING NOT NULL,
    -- Away team abbreviation (e.g., 'MIA', 'BOS')

  game_id STRING,
    -- NBA game ID if known (e.g., '0022500123')

  -- ==========================================================================
  -- AVAILABILITY STATUS
  -- ==========================================================================

  was_available BOOL NOT NULL,
    -- TRUE if scraper returned data for this game
    -- FALSE if game was expected but not returned

  record_count INT64,
    -- Number of records returned for this game
    -- For box scores: player count (~24-30)
    -- For props: line count (~50-200)

  data_status STRING,
    -- 'complete': Full data available
    -- 'partial': Some data but incomplete (e.g., only 10 players)
    -- 'missing': No data returned
    -- 'in_progress': Game still in progress (live data)

  data_quality_score FLOAT64,
    -- 0.0 to 1.0 quality score
    -- Based on: record_count vs expected, field completeness, etc.

  -- ==========================================================================
  -- TIMING CONTEXT
  -- ==========================================================================

  game_start_time TIMESTAMP,
    -- When the game was scheduled to start

  estimated_game_end TIMESTAMP,
    -- game_start_time + 2.5 hours

  latency_minutes INT64,
    -- Minutes from estimated_game_end to attempt_timestamp
    -- Negative if checked before game ended

  is_west_coast BOOL,
    -- TRUE if home team is in Pacific timezone

  is_late_game BOOL,
    -- TRUE if game started after 10 PM ET

  -- ==========================================================================
  -- METADATA
  -- ==========================================================================

  error_message STRING,
    -- If was_available=FALSE, why? (e.g., 'API timeout', '404 not found')

  source_url STRING,
    -- The URL/endpoint that was scraped (for debugging)

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(attempt_timestamp)
CLUSTER BY scraper_name, game_date, was_available
OPTIONS(
  description = "Tracks per-game data availability across all scrapers. Each row = one game checked during one scraper run. Use to calculate: when did each source first have data for a game?",
  partition_expiration_days = 90
);


-- ============================================================================
-- VIEW 1: First Availability Per Game Per Scraper
-- ============================================================================
-- Shows when each game's data first appeared from each source.
-- This is the key view for latency analysis.

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_first_availability` AS

WITH ranked_attempts AS (
  SELECT
    scraper_name,
    game_date,
    home_team,
    away_team,
    CONCAT(away_team, ' @ ', home_team) AS matchup,
    attempt_timestamp,
    was_available,
    record_count,
    data_status,
    latency_minutes,
    workflow,
    is_west_coast,
    is_late_game,

    -- Rank by attempt time (earliest first)
    ROW_NUMBER() OVER (
      PARTITION BY scraper_name, game_date, home_team, away_team
      ORDER BY attempt_timestamp
    ) AS attempt_number,

    -- Find first successful attempt
    MIN(CASE WHEN was_available AND data_status IN ('complete', 'partial')
        THEN attempt_timestamp END) OVER (
      PARTITION BY scraper_name, game_date, home_team, away_team
    ) AS first_available_at

  FROM `nba-props-platform.nba_orchestration.scraper_data_arrival`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  scraper_name,
  game_date,
  matchup,
  home_team,
  away_team,
  is_west_coast,
  is_late_game,

  -- Attempt metrics
  MAX(attempt_number) AS total_attempts,
  COUNTIF(NOT was_available) AS failed_attempts,
  MIN(attempt_timestamp) AS first_checked_at,
  first_available_at,

  -- Latency
  MIN(CASE WHEN was_available THEN latency_minutes END) AS latency_minutes,
  ROUND(MIN(CASE WHEN was_available THEN latency_minutes END) / 60.0, 1) AS latency_hours,

  -- Data quality at first availability
  MAX(CASE WHEN attempt_timestamp = first_available_at THEN record_count END) AS record_count,
  MAX(CASE WHEN attempt_timestamp = first_available_at THEN data_status END) AS data_status,
  MAX(CASE WHEN attempt_timestamp = first_available_at THEN workflow END) AS found_in_workflow,

  -- Status
  CASE
    WHEN first_available_at IS NULL THEN 'NEVER_AVAILABLE'
    WHEN MIN(CASE WHEN was_available THEN latency_minutes END) <= 60 THEN 'FAST_0_1H'
    WHEN MIN(CASE WHEN was_available THEN latency_minutes END) <= 180 THEN 'NORMAL_1_3H'
    WHEN MIN(CASE WHEN was_available THEN latency_minutes END) <= 360 THEN 'SLOW_3_6H'
    WHEN MIN(CASE WHEN was_available THEN latency_minutes END) <= 720 THEN 'DELAYED_6_12H'
    WHEN MIN(CASE WHEN was_available THEN latency_minutes END) <= 1440 THEN 'VERY_DELAYED_12_24H'
    ELSE 'EXTREMELY_DELAYED_24H_PLUS'
  END AS latency_category

FROM ranked_attempts
GROUP BY
  scraper_name, game_date, matchup, home_team, away_team,
  is_west_coast, is_late_game, first_available_at;


-- ============================================================================
-- VIEW 2: Multi-Scraper Game Timeline
-- ============================================================================
-- Shows all sources for a single game side-by-side.
-- Key for answering: "Which source had data first for this game?"

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_game_data_timeline` AS

WITH game_schedule AS (
  SELECT
    game_date,
    home_team_tricode AS home_team,
    away_team_tricode AS away_team,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) AS matchup,
    game_date_est AS game_start_time,
    TIMESTAMP_ADD(game_date_est, INTERVAL 150 MINUTE) AS estimated_game_end,
    arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') AS is_west_coast
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3  -- Final games only
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    -- Dynamic season year: Oct-Dec = current year, Jan-Sep = previous year
    AND season_year = CASE
        WHEN EXTRACT(MONTH FROM CURRENT_DATE()) >= 10
        THEN EXTRACT(YEAR FROM CURRENT_DATE())
        ELSE EXTRACT(YEAR FROM CURRENT_DATE()) - 1
      END
),

scraper_availability AS (
  SELECT
    scraper_name,
    game_date,
    home_team,
    away_team,
    first_available_at,
    latency_minutes,
    total_attempts,
    record_count,
    data_status,
    latency_category
  FROM `nba-props-platform.nba_orchestration.v_scraper_first_availability`
)

SELECT
  s.game_date,
  s.matchup,
  s.home_team,
  s.away_team,
  s.game_start_time,
  s.estimated_game_end,
  s.is_west_coast,

  -- BDL availability
  bdl.first_available_at AS bdl_first_available,
  bdl.latency_minutes AS bdl_latency_minutes,
  bdl.total_attempts AS bdl_attempts,
  bdl.latency_category AS bdl_status,

  -- NBAC Gamebook availability
  nbac.first_available_at AS nbac_first_available,
  nbac.latency_minutes AS nbac_latency_minutes,
  nbac.total_attempts AS nbac_attempts,
  nbac.latency_category AS nbac_status,

  -- Odds API availability
  odds.first_available_at AS odds_first_available,
  odds.latency_minutes AS odds_latency_minutes,
  odds.total_attempts AS odds_attempts,
  odds.latency_category AS odds_status,

  -- ESPN availability
  espn.first_available_at AS espn_first_available,
  espn.latency_minutes AS espn_latency_minutes,
  espn.latency_category AS espn_status,

  -- Which source was first?
  CASE
    WHEN bdl.first_available_at IS NULL
     AND nbac.first_available_at IS NULL
     AND odds.first_available_at IS NULL THEN 'NONE'
    WHEN bdl.first_available_at <= COALESCE(nbac.first_available_at, TIMESTAMP('9999-12-31'))
     AND bdl.first_available_at <= COALESCE(odds.first_available_at, TIMESTAMP('9999-12-31'))
     AND bdl.first_available_at <= COALESCE(espn.first_available_at, TIMESTAMP('9999-12-31')) THEN 'BDL'
    WHEN nbac.first_available_at <= COALESCE(odds.first_available_at, TIMESTAMP('9999-12-31'))
     AND nbac.first_available_at <= COALESCE(espn.first_available_at, TIMESTAMP('9999-12-31')) THEN 'NBAC'
    WHEN odds.first_available_at <= COALESCE(espn.first_available_at, TIMESTAMP('9999-12-31')) THEN 'ODDS'
    ELSE 'ESPN'
  END AS first_available_source,

  -- Overall completeness
  (CASE WHEN bdl.first_available_at IS NOT NULL THEN 1 ELSE 0 END +
   CASE WHEN nbac.first_available_at IS NOT NULL THEN 1 ELSE 0 END +
   CASE WHEN odds.first_available_at IS NOT NULL THEN 1 ELSE 0 END +
   CASE WHEN espn.first_available_at IS NOT NULL THEN 1 ELSE 0 END) AS sources_with_data,

  -- Any critical sources missing?
  CASE
    WHEN nbac.first_available_at IS NULL THEN 'CRITICAL_MISSING_NBAC'
    WHEN bdl.first_available_at IS NULL AND odds.first_available_at IS NULL THEN 'WARNING_MISSING_SECONDARY'
    ELSE 'OK'
  END AS availability_status

FROM game_schedule s
LEFT JOIN scraper_availability bdl
  ON s.game_date = bdl.game_date AND s.home_team = bdl.home_team AND s.away_team = bdl.away_team
  AND bdl.scraper_name = 'bdl_box_scores'
LEFT JOIN scraper_availability nbac
  ON s.game_date = nbac.game_date AND s.home_team = nbac.home_team AND s.away_team = nbac.away_team
  AND nbac.scraper_name = 'nbac_gamebook'
LEFT JOIN scraper_availability odds
  ON s.game_date = odds.game_date AND s.home_team = odds.home_team AND s.away_team = odds.away_team
  AND odds.scraper_name = 'oddsa_player_props'
LEFT JOIN scraper_availability espn
  ON s.game_date = espn.game_date AND s.home_team = espn.home_team AND s.away_team = espn.away_team
  AND espn.scraper_name = 'espn_boxscore';


-- ============================================================================
-- VIEW 3: Daily Scraper Latency Summary
-- ============================================================================
-- Aggregated metrics per scraper per day for dashboards.

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_latency_daily` AS

SELECT
  game_date,
  scraper_name,

  -- Coverage
  COUNT(*) AS total_games,
  COUNTIF(first_available_at IS NOT NULL) AS games_with_data,
  ROUND(100.0 * COUNTIF(first_available_at IS NOT NULL) / COUNT(*), 1) AS coverage_pct,

  -- Latency percentiles
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(50)] AS latency_p50_minutes,
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(90)] AS latency_p90_minutes,
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(95)] AS latency_p95_minutes,
  MAX(latency_minutes) AS latency_max_minutes,

  -- Latency in hours for readability
  ROUND(APPROX_QUANTILES(latency_minutes, 100)[OFFSET(50)] / 60.0, 1) AS latency_p50_hours,
  ROUND(APPROX_QUANTILES(latency_minutes, 100)[OFFSET(90)] / 60.0, 1) AS latency_p90_hours,

  -- Attempts
  ROUND(AVG(total_attempts), 1) AS avg_attempts_per_game,
  MAX(total_attempts) AS max_attempts,

  -- Category breakdown
  COUNTIF(latency_category = 'FAST_0_1H') AS fast_count,
  COUNTIF(latency_category = 'NORMAL_1_3H') AS normal_count,
  COUNTIF(latency_category = 'SLOW_3_6H') AS slow_count,
  COUNTIF(latency_category = 'DELAYED_6_12H') AS delayed_count,
  COUNTIF(latency_category IN ('VERY_DELAYED_12_24H', 'EXTREMELY_DELAYED_24H_PLUS')) AS very_delayed_count,
  COUNTIF(latency_category = 'NEVER_AVAILABLE') AS never_available_count,

  -- West Coast analysis
  COUNTIF(is_west_coast) AS west_coast_games,
  COUNTIF(is_west_coast AND first_available_at IS NULL) AS west_coast_missing,

  -- Health score (0-100, higher = better)
  ROUND(
    (COUNTIF(latency_category = 'FAST_0_1H') * 100.0 +
     COUNTIF(latency_category = 'NORMAL_1_3H') * 80.0 +
     COUNTIF(latency_category = 'SLOW_3_6H') * 50.0 +
     COUNTIF(latency_category = 'DELAYED_6_12H') * 20.0) / NULLIF(COUNT(*), 0),
    1
  ) AS health_score

FROM `nba-props-platform.nba_orchestration.v_scraper_first_availability`
GROUP BY game_date, scraper_name
ORDER BY game_date DESC, scraper_name;


-- ============================================================================
-- VIEW 4: Scraper Latency Report (For Contacting APIs)
-- ============================================================================
-- Summary statistics for sharing with external API providers.

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_latency_report` AS

SELECT
  scraper_name,

  -- Date range
  MIN(game_date) AS first_date,
  MAX(game_date) AS last_date,
  COUNT(DISTINCT game_date) AS days_analyzed,

  -- Overall coverage
  COUNT(*) AS total_games,
  COUNTIF(first_available_at IS NOT NULL) AS games_with_data,
  COUNTIF(first_available_at IS NULL) AS games_missing_data,
  ROUND(100.0 * COUNTIF(first_available_at IS NOT NULL) / COUNT(*), 1) AS overall_coverage_pct,

  -- Latency stats (only for games with data)
  ROUND(AVG(latency_minutes), 0) AS avg_latency_minutes,
  ROUND(AVG(latency_minutes) / 60.0, 1) AS avg_latency_hours,
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(50)] AS median_latency_minutes,
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(90)] AS p90_latency_minutes,
  APPROX_QUANTILES(latency_minutes, 100)[OFFSET(95)] AS p95_latency_minutes,
  MAX(latency_minutes) AS max_latency_minutes,
  ROUND(MAX(latency_minutes) / 60.0, 1) AS max_latency_hours,

  -- Problem patterns
  COUNTIF(latency_minutes > 360) AS games_delayed_over_6h,
  COUNTIF(latency_minutes > 720) AS games_delayed_over_12h,
  COUNTIF(latency_minutes > 1440) AS games_delayed_over_24h,

  -- West Coast issues
  COUNTIF(is_west_coast AND first_available_at IS NULL) AS west_coast_missing,
  COUNTIF(is_west_coast) AS west_coast_total,
  ROUND(100.0 * COUNTIF(is_west_coast AND first_available_at IS NULL) /
        NULLIF(COUNTIF(is_west_coast), 0), 1) AS west_coast_missing_pct,

  -- Retry efficiency
  ROUND(AVG(total_attempts), 1) AS avg_attempts_per_game,
  COUNTIF(total_attempts > 3) AS games_needing_many_retries

FROM `nba-props-platform.nba_orchestration.v_scraper_first_availability`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY scraper_name
ORDER BY overall_coverage_pct ASC;


-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Query 1: Games missing BDL data but have NBAC
/*
SELECT
  game_date, matchup,
  nbac_status, nbac_latency_minutes,
  bdl_status, bdl_latency_minutes,
  first_available_source
FROM `nba-props-platform.nba_orchestration.v_game_data_timeline`
WHERE bdl_status = 'NEVER_AVAILABLE'
  AND nbac_status != 'NEVER_AVAILABLE'
ORDER BY game_date DESC;
*/

-- Query 2: Scraper latency trends over time
/*
SELECT
  game_date, scraper_name,
  coverage_pct, latency_p50_hours, latency_p90_hours,
  health_score
FROM `nba-props-platform.nba_orchestration.v_scraper_latency_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY game_date, scraper_name;
*/

-- Query 3: Full attempt timeline for a specific game
/*
SELECT
  attempt_timestamp, scraper_name, workflow,
  was_available, record_count, data_status, latency_minutes
FROM `nba-props-platform.nba_orchestration.scraper_data_arrival`
WHERE game_date = '2026-01-21'
  AND home_team = 'GSW'
ORDER BY attempt_timestamp;
*/

-- Query 4: Generate report for contacting BDL support
/*
SELECT *
FROM `nba-props-platform.nba_orchestration.v_scraper_latency_report`
WHERE scraper_name = 'bdl_box_scores';
*/
