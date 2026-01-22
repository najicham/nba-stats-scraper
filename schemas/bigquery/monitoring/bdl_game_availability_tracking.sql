-- File: schemas/bigquery/monitoring/bdl_game_availability_tracking.sql
-- ============================================================================
-- BDL Data Availability Tracking - Views and Tables
-- ============================================================================
-- Purpose: Track when BDL data becomes available for each game, calculate
--          latency from game end, and identify patterns in data delays.
--
-- Created: January 21, 2026
-- Updated: January 21, 2026 (Fixed bugs: processed_at NULL, syntax errors)
-- Location: nba_orchestration dataset (us-west2, same as source data)
--
-- IMPORTANT: These views are in nba_orchestration, NOT nba_monitoring,
--            because BigQuery requires views to be in the same region as
--            the underlying tables (nba_raw is in us-west2).
--
-- Components:
--   1. v_bdl_game_availability - View showing per-game first-availability
--   2. v_bdl_availability_latency - View with latency calculations
--   3. v_bdl_availability_summary - Aggregated metrics for monitoring
--
-- FIXES APPLIED (Jan 21, 2026):
--   - Changed NBAC from processed_at (always NULL) to parsing source_file_path
--   - Fixed SQL syntax errors (backticks replaced with proper semicolons)
--   - Added game_id alias fix for latency view
-- ============================================================================

-- ============================================================================
-- VIEW 1: Per-Game First Availability
-- ============================================================================
-- Shows when each game's BDL data first appeared in our system
-- Uses MIN(created_at) from bdl_player_boxscores as "first seen" timestamp
-- Uses source_file_path timestamp for NBAC (since processed_at is NULL)
--
-- DEPLOYED: January 21, 2026
-- ============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_bdl_game_availability AS

WITH schedule AS (
  -- Get game schedule with start times and team info
  -- NOTE: Uses nbac_schedule directly with partition filter for efficiency
  SELECT
    game_id AS nba_game_id,
    game_date,
    game_date_est AS game_start_time,
    -- Estimate game end: start + 2.5 hours (typical NBA game duration)
    TIMESTAMP_ADD(game_date_est, INTERVAL 150 MINUTE) AS estimated_game_end,
    home_team_tricode,
    away_team_tricode,
    arena_timezone,
    game_status,
    -- Flag late games (start after 10 PM ET)
    EXTRACT(HOUR FROM game_date_est) >= 22 AS is_late_game,
    -- Flag west coast games
    arena_timezone IN ('America/Los_Angeles', 'America/Phoenix') AS is_west_coast
  FROM nba_raw.nbac_schedule
  WHERE game_status = 3  -- Final games only
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND season_year = 2025  -- Current season
),

bdl_first_seen AS (
  -- Find when BDL data first appeared for each game
  -- NOTE: Joins on date + teams because game_id formats differ between sources
  SELECT
    game_date,
    home_team_abbr,
    away_team_abbr,
    MIN(created_at) AS bdl_first_available_at,
    COUNT(DISTINCT bdl_player_id) AS players_in_first_load
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, home_team_abbr, away_team_abbr
),

nbac_first_seen AS (
  -- Find when NBAC (NBA.com) data first appeared for each game
  -- NOTE: processed_at is NULL, so we parse timestamp from source_file_path
  -- Format: nba-com/gamebooks-data/YYYY-MM-DD/YYYYMMDD-TEAMS/YYYYMMDD_HHMMSS.json
  SELECT
    game_date,
    home_team_abbr,
    away_team_abbr,
    MIN(
      PARSE_TIMESTAMP(
        '%Y%m%d_%H%M%S',
        REGEXP_EXTRACT(source_file_path, r'/(\d{8}_\d{6})\.json$')
      )
    ) AS nbac_first_available_at
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND source_file_path IS NOT NULL
  GROUP BY game_date, home_team_abbr, away_team_abbr
)

SELECT
  s.nba_game_id,
  s.game_date,
  s.game_start_time,
  s.estimated_game_end,
  s.home_team_tricode,
  s.away_team_tricode,
  CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) AS matchup,
  s.arena_timezone,
  s.is_late_game,
  s.is_west_coast,

  -- BDL availability
  bdl.bdl_first_available_at,
  bdl.players_in_first_load,
  CASE WHEN bdl.bdl_first_available_at IS NOT NULL THEN TRUE ELSE FALSE END AS has_bdl_data,

  -- NBAC availability (fallback)
  nbac.nbac_first_available_at,
  CASE WHEN nbac.nbac_first_available_at IS NOT NULL THEN TRUE ELSE FALSE END AS has_nbac_data,

  -- Which source was available first?
  CASE
    WHEN bdl.bdl_first_available_at IS NULL AND nbac.nbac_first_available_at IS NULL THEN 'NEITHER'
    WHEN bdl.bdl_first_available_at IS NULL THEN 'NBAC_ONLY'
    WHEN nbac.nbac_first_available_at IS NULL THEN 'BDL_ONLY'
    WHEN bdl.bdl_first_available_at <= nbac.nbac_first_available_at THEN 'BDL_FIRST'
    ELSE 'NBAC_FIRST'
  END AS first_available_source,

  -- Timestamps for latency calculation
  COALESCE(bdl.bdl_first_available_at, nbac.nbac_first_available_at) AS any_source_first_available

FROM schedule s
LEFT JOIN bdl_first_seen bdl
  ON s.game_date = bdl.game_date
  AND s.home_team_tricode = bdl.home_team_abbr
  AND s.away_team_tricode = bdl.away_team_abbr
LEFT JOIN nbac_first_seen nbac
  ON s.game_date = nbac.game_date
  AND s.home_team_tricode = nbac.home_team_abbr
  AND s.away_team_tricode = nbac.away_team_abbr;


-- ============================================================================
-- VIEW 2: Availability Latency Calculations
-- ============================================================================
-- Calculates how long after game end each data source became available
-- Key metric: "How late is BDL posting data?"
-- ============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_bdl_availability_latency AS

SELECT
  nba_game_id AS game_id,
  game_date,
  matchup,
  home_team_tricode,
  away_team_tricode,
  game_start_time,
  estimated_game_end,
  arena_timezone,
  is_late_game,
  is_west_coast,

  -- BDL latency
  bdl_first_available_at,
  has_bdl_data,
  TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) AS bdl_latency_minutes,
  ROUND(TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) / 60.0, 1) AS bdl_latency_hours,

  -- NBAC latency
  nbac_first_available_at,
  has_nbac_data,
  TIMESTAMP_DIFF(nbac_first_available_at, estimated_game_end, MINUTE) AS nbac_latency_minutes,
  ROUND(TIMESTAMP_DIFF(nbac_first_available_at, estimated_game_end, MINUTE) / 60.0, 1) AS nbac_latency_hours,

  first_available_source,

  -- Latency classification for BDL
  CASE
    WHEN NOT has_bdl_data THEN 'NEVER_AVAILABLE'
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) < 0 THEN 'BEFORE_GAME_END'  -- Data before game ended (live updates)
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) <= 30 THEN 'FAST_0_30_MIN'
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) <= 60 THEN 'NORMAL_30_60_MIN'
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) <= 120 THEN 'SLOW_1_2_HOURS'
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) <= 360 THEN 'DELAYED_2_6_HOURS'
    ELSE 'VERY_DELAYED_6_PLUS_HOURS'
  END AS bdl_latency_category,

  -- Highlight problematic games
  CASE
    WHEN NOT has_bdl_data THEN 'CRITICAL'
    WHEN TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE) > 360 THEN 'WARNING'
    ELSE 'OK'
  END AS availability_status

FROM nba_orchestration.v_bdl_game_availability;


-- ============================================================================
-- VIEW 3: Aggregated Availability Summary
-- ============================================================================
-- Daily/weekly summary of BDL data availability patterns
-- Use this for dashboards and trend analysis
-- ============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_bdl_availability_summary AS

WITH daily_stats AS (
  SELECT
    game_date,
    COUNT(*) AS total_games,
    COUNTIF(has_bdl_data) AS games_with_bdl,
    COUNTIF(has_nbac_data) AS games_with_nbac,
    COUNTIF(NOT has_bdl_data AND has_nbac_data) AS nbac_fallback_used,
    COUNTIF(NOT has_bdl_data AND NOT has_nbac_data) AS games_missing_both,

    -- West coast breakdown
    COUNTIF(is_west_coast) AS west_coast_games,
    COUNTIF(is_west_coast AND has_bdl_data) AS west_coast_with_bdl,
    COUNTIF(is_late_game) AS late_games,
    COUNTIF(is_late_game AND has_bdl_data) AS late_games_with_bdl,

    -- Latency percentiles (only for games with BDL data)
    APPROX_QUANTILES(
      IF(has_bdl_data, TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE), NULL),
      100
    )[OFFSET(50)] AS bdl_latency_p50_minutes,
    APPROX_QUANTILES(
      IF(has_bdl_data, TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE), NULL),
      100
    )[OFFSET(90)] AS bdl_latency_p90_minutes,
    APPROX_QUANTILES(
      IF(has_bdl_data, TIMESTAMP_DIFF(bdl_first_available_at, estimated_game_end, MINUTE), NULL),
      100
    )[OFFSET(95)] AS bdl_latency_p95_minutes,

    -- Latency category breakdown
    COUNTIF(bdl_latency_category = 'FAST_0_30_MIN') AS fast_count,
    COUNTIF(bdl_latency_category = 'NORMAL_30_60_MIN') AS normal_count,
    COUNTIF(bdl_latency_category = 'SLOW_1_2_HOURS') AS slow_count,
    COUNTIF(bdl_latency_category = 'DELAYED_2_6_HOURS') AS delayed_count,
    COUNTIF(bdl_latency_category = 'VERY_DELAYED_6_PLUS_HOURS') AS very_delayed_count,
    COUNTIF(bdl_latency_category = 'NEVER_AVAILABLE') AS never_available_count

  FROM nba_orchestration.v_bdl_availability_latency
  GROUP BY game_date
)

SELECT
  game_date,
  total_games,
  games_with_bdl,
  ROUND(100.0 * games_with_bdl / total_games, 1) AS bdl_coverage_pct,
  nbac_fallback_used,
  games_missing_both,

  west_coast_games,
  west_coast_with_bdl,
  ROUND(100.0 * west_coast_with_bdl / NULLIF(west_coast_games, 0), 1) AS west_coast_bdl_pct,

  late_games,
  late_games_with_bdl,

  -- Latency metrics
  bdl_latency_p50_minutes,
  bdl_latency_p90_minutes,
  bdl_latency_p95_minutes,
  ROUND(bdl_latency_p50_minutes / 60.0, 1) AS bdl_latency_p50_hours,
  ROUND(bdl_latency_p90_minutes / 60.0, 1) AS bdl_latency_p90_hours,

  -- Latency breakdown
  fast_count,
  normal_count,
  slow_count,
  delayed_count,
  very_delayed_count,
  never_available_count,

  -- Health score (higher = better)
  ROUND(
    (fast_count * 100 + normal_count * 80 + slow_count * 50 + delayed_count * 20)
    / NULLIF(total_games, 0),
    1
  ) AS availability_health_score

FROM daily_stats
ORDER BY game_date DESC;


-- ============================================================================
-- QUERY: Games Missing BDL Data (for alerting)
-- ============================================================================
-- Run this query to find games that should have BDL data but don't
-- Use in alerting systems or morning checks

/*
SELECT
  game_date,
  game_id,
  matchup,
  estimated_game_end,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), estimated_game_end, HOUR) AS hours_since_game_end,
  has_bdl_data,
  has_nbac_data,
  availability_status
FROM nba_orchestration.v_bdl_availability_latency
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND availability_status != 'OK'
ORDER BY game_date DESC, estimated_game_end DESC;
*/


-- ============================================================================
-- QUERY: BDL Latency Trend (for dashboards)
-- ============================================================================
-- Use this to chart BDL availability patterns over time

/*
SELECT
  game_date,
  bdl_coverage_pct,
  bdl_latency_p50_hours AS median_latency_hours,
  bdl_latency_p90_hours AS p90_latency_hours,
  availability_health_score
FROM nba_orchestration.v_bdl_availability_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY game_date;
*/


-- ============================================================================
-- QUERY: West Coast Game Latency Analysis
-- ============================================================================
-- Specifically analyze late west coast games

/*
SELECT
  game_date,
  matchup,
  arena_timezone,
  game_start_time,
  estimated_game_end,
  bdl_first_available_at,
  bdl_latency_hours,
  bdl_latency_category
FROM nba_orchestration.v_bdl_availability_latency
WHERE is_west_coast = TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY game_date DESC, bdl_latency_hours DESC;
*/
