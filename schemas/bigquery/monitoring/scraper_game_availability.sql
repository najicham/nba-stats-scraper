-- File: schemas/bigquery/monitoring/scraper_game_availability.sql
-- ============================================================================
-- Unified Scraper Game Availability Monitoring
-- ============================================================================
-- Purpose: Track data availability across ALL key scrapers for each game
--          Compare against NBA Schedule as source of truth
--          Calculate latency from game end to data availability
--          Power automated alerting for missing data
--
-- Created: January 21, 2026
-- Location: nba_orchestration dataset (us-west2)
--
-- Key Sources Monitored:
--   1. BDL (Ball Don't Lie) - bdl_player_boxscores
--   2. NBAC (NBA.com Gamebook) - nbac_gamebook_player_stats
--   3. OddsAPI - odds_api_game_lines
--
-- Usage:
--   - Daily alerting Cloud Function queries this view
--   - Dashboard for scraper reliability tracking
--   - Investigation of missing data patterns
-- ============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_scraper_game_availability AS

-- ============================================================================
-- Step 1: Get the authoritative game schedule
-- ============================================================================
WITH schedule AS (
  SELECT
    game_id AS nba_game_id,
    game_date,
    game_date_est AS game_start_time,
    -- Estimate game end: start + 2.5 hours (typical NBA game duration)
    TIMESTAMP_ADD(game_date_est, INTERVAL 150 MINUTE) AS estimated_game_end,
    home_team_tricode,
    away_team_tricode,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) AS matchup,
    arena_timezone,
    game_status,
    -- Flag late games (start after 10 PM ET)
    EXTRACT(HOUR FROM game_date_est) >= 22 AS is_late_game,
    -- Flag west coast games
    arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') AS is_west_coast
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3  -- Final games only
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND season_year = 2025  -- Current season
),

-- ============================================================================
-- Step 2: BDL (Ball Don't Lie) availability
-- ============================================================================
bdl_first_seen AS (
  SELECT
    game_date,
    home_team_abbr,
    away_team_abbr,
    MIN(created_at) AS first_available_at,
    COUNT(DISTINCT bdl_player_id) AS record_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, home_team_abbr, away_team_abbr
),

-- ============================================================================
-- Step 3: NBAC (NBA.com Gamebook) availability
-- Parse timestamp from source_file_path since processed_at is NULL
-- Format: nba-com/gamebooks-data/YYYY-MM-DD/YYYYMMDD-TEAMS/YYYYMMDD_HHMMSS.json
-- ============================================================================
nbac_first_seen AS (
  SELECT
    game_date,
    home_team_abbr,
    away_team_abbr,
    MIN(
      PARSE_TIMESTAMP(
        '%Y%m%d_%H%M%S',
        REGEXP_EXTRACT(source_file_path, r'/(\d{8}_\d{6})\.json$')
      )
    ) AS first_available_at,
    COUNT(*) AS record_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND source_file_path IS NOT NULL
  GROUP BY game_date, home_team_abbr, away_team_abbr
),

-- ============================================================================
-- Step 4: OddsAPI game lines availability
-- ============================================================================
odds_first_seen AS (
  SELECT
    game_date,
    -- OddsAPI uses full team names, need to map to abbreviations
    -- For now, join on game_date and use home/away from schedule
    MIN(created_at) AS first_available_at,
    COUNT(DISTINCT game_id) AS games_with_lines
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
)

-- ============================================================================
-- Step 5: Join everything together
-- ============================================================================
SELECT
  s.nba_game_id,
  s.game_date,
  s.game_start_time,
  s.estimated_game_end,
  s.home_team_tricode,
  s.away_team_tricode,
  s.matchup,
  s.arena_timezone,
  s.is_late_game,
  s.is_west_coast,

  -- Hours since game ended (for freshness check)
  ROUND(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.estimated_game_end, MINUTE) / 60.0, 1) AS hours_since_game_end,

  -- ========== BDL Availability ==========
  bdl.first_available_at AS bdl_first_available_at,
  bdl.record_count AS bdl_record_count,
  CASE WHEN bdl.first_available_at IS NOT NULL THEN TRUE ELSE FALSE END AS bdl_available,
  ROUND(TIMESTAMP_DIFF(bdl.first_available_at, s.estimated_game_end, MINUTE) / 60.0, 1) AS bdl_latency_hours,
  CASE
    WHEN bdl.first_available_at IS NULL THEN 'MISSING'
    WHEN TIMESTAMP_DIFF(bdl.first_available_at, s.estimated_game_end, MINUTE) <= 120 THEN 'FAST'
    WHEN TIMESTAMP_DIFF(bdl.first_available_at, s.estimated_game_end, MINUTE) <= 360 THEN 'NORMAL'
    ELSE 'SLOW'
  END AS bdl_latency_category,

  -- ========== NBAC Availability ==========
  nbac.first_available_at AS nbac_first_available_at,
  nbac.record_count AS nbac_record_count,
  CASE WHEN nbac.first_available_at IS NOT NULL THEN TRUE ELSE FALSE END AS nbac_available,
  ROUND(TIMESTAMP_DIFF(nbac.first_available_at, s.estimated_game_end, MINUTE) / 60.0, 1) AS nbac_latency_hours,
  CASE
    WHEN nbac.first_available_at IS NULL THEN 'MISSING'
    WHEN TIMESTAMP_DIFF(nbac.first_available_at, s.estimated_game_end, MINUTE) <= 60 THEN 'FAST'
    WHEN TIMESTAMP_DIFF(nbac.first_available_at, s.estimated_game_end, MINUTE) <= 180 THEN 'NORMAL'
    ELSE 'SLOW'
  END AS nbac_latency_category,

  -- ========== OddsAPI Availability (date-level only for now) ==========
  odds.first_available_at AS odds_first_available_at,
  CASE WHEN odds.first_available_at IS NOT NULL THEN TRUE ELSE FALSE END AS odds_available,

  -- ========== Aggregate Status ==========
  -- Which source got data first?
  CASE
    WHEN bdl.first_available_at IS NULL AND nbac.first_available_at IS NULL THEN 'NEITHER'
    WHEN bdl.first_available_at IS NULL THEN 'NBAC_ONLY'
    WHEN nbac.first_available_at IS NULL THEN 'BDL_ONLY'
    WHEN bdl.first_available_at <= nbac.first_available_at THEN 'BDL_FIRST'
    ELSE 'NBAC_FIRST'
  END AS first_available_source,

  -- Missing sources as array
  ARRAY_CONCAT(
    IF(bdl.first_available_at IS NULL, ['BDL'], []),
    IF(nbac.first_available_at IS NULL, ['NBAC'], []),
    IF(odds.first_available_at IS NULL, ['ODDS'], [])
  ) AS missing_sources,

  -- Overall availability status
  CASE
    -- Too early to check (game ended less than 6 hours ago)
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), s.estimated_game_end, HOUR) < 6 THEN 'TOO_EARLY'
    -- Critical: Neither BDL nor NBAC has data after 6+ hours
    WHEN bdl.first_available_at IS NULL AND nbac.first_available_at IS NULL THEN 'CRITICAL'
    -- Warning: BDL missing but NBAC has it (our current situation)
    WHEN bdl.first_available_at IS NULL AND nbac.first_available_at IS NOT NULL THEN 'WARNING'
    -- OK: At least BDL has data
    ELSE 'OK'
  END AS availability_status

FROM schedule s

LEFT JOIN bdl_first_seen bdl
  ON s.game_date = bdl.game_date
  AND s.home_team_tricode = bdl.home_team_abbr
  AND s.away_team_tricode = bdl.away_team_abbr

LEFT JOIN nbac_first_seen nbac
  ON s.game_date = nbac.game_date
  AND s.home_team_tricode = nbac.home_team_abbr
  AND s.away_team_tricode = nbac.away_team_abbr

LEFT JOIN odds_first_seen odds
  ON s.game_date = odds.game_date;


-- ============================================================================
-- VIEW 2: Daily Summary for Alerting
-- ============================================================================
-- Aggregates per-game availability into daily summary
-- Used by the alerting Cloud Function

CREATE OR REPLACE VIEW nba_orchestration.v_scraper_availability_daily_summary AS

SELECT
  game_date,

  -- Game counts
  COUNT(*) AS total_games,

  -- BDL stats
  COUNTIF(bdl_available) AS bdl_games_available,
  COUNTIF(NOT bdl_available) AS bdl_games_missing,
  ROUND(100.0 * COUNTIF(bdl_available) / COUNT(*), 1) AS bdl_coverage_pct,
  ARRAY_AGG(IF(NOT bdl_available, matchup, NULL) IGNORE NULLS) AS bdl_missing_matchups,

  -- NBAC stats
  COUNTIF(nbac_available) AS nbac_games_available,
  COUNTIF(NOT nbac_available) AS nbac_games_missing,
  ROUND(100.0 * COUNTIF(nbac_available) / COUNT(*), 1) AS nbac_coverage_pct,
  ARRAY_AGG(IF(NOT nbac_available, matchup, NULL) IGNORE NULLS) AS nbac_missing_matchups,

  -- OddsAPI stats
  COUNTIF(odds_available) AS odds_games_available,
  COUNTIF(NOT odds_available) AS odds_games_missing,
  ROUND(100.0 * COUNTIF(odds_available) / COUNT(*), 1) AS odds_coverage_pct,

  -- Overall status
  COUNTIF(availability_status = 'CRITICAL') AS critical_count,
  COUNTIF(availability_status = 'WARNING') AS warning_count,
  COUNTIF(availability_status = 'OK') AS ok_count,

  -- West coast breakdown
  COUNTIF(is_west_coast) AS west_coast_games,
  COUNTIF(is_west_coast AND NOT bdl_available) AS west_coast_bdl_missing,

  -- Latency stats (for games with data)
  ROUND(AVG(IF(bdl_available, bdl_latency_hours, NULL)), 1) AS bdl_avg_latency_hours,
  ROUND(AVG(IF(nbac_available, nbac_latency_hours, NULL)), 1) AS nbac_avg_latency_hours,

  -- Should we alert?
  CASE
    WHEN COUNTIF(availability_status = 'CRITICAL') > 0 THEN 'CRITICAL'
    WHEN COUNTIF(availability_status = 'WARNING') > 2 THEN 'WARNING'
    WHEN 100.0 * COUNTIF(bdl_available) / COUNT(*) < 80 THEN 'WARNING'
    ELSE 'OK'
  END AS daily_alert_level

FROM nba_orchestration.v_scraper_game_availability
WHERE availability_status != 'TOO_EARLY'  -- Only check games that have had time to be scraped
GROUP BY game_date
ORDER BY game_date DESC;


-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

/*
-- Check yesterday's availability
SELECT *
FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

-- Find all missing BDL games in past week
SELECT game_date, matchup, nbac_available, hours_since_game_end
FROM nba_orchestration.v_scraper_game_availability
WHERE NOT bdl_available
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND availability_status != 'TOO_EARLY'
ORDER BY game_date DESC;

-- Latency comparison: BDL vs NBAC
SELECT
  game_date,
  matchup,
  bdl_latency_hours,
  nbac_latency_hours,
  first_available_source
FROM nba_orchestration.v_scraper_game_availability
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND bdl_available AND nbac_available
ORDER BY game_date DESC;
*/
