-- Daily Scraper Health Dashboard
-- Run every morning at 9 AM ET to check yesterday's data
-- Created: January 22, 2026

-- =============================================================================
-- 1. Overall Coverage Summary (Last 7 Days)
-- =============================================================================
-- Shows scraper coverage percentages and alert levels

SELECT
  game_date,
  total_games,

  -- BDL Coverage
  bdl_games_available,
  bdl_coverage_pct,
  bdl_games_missing,

  -- NBAC Coverage
  nbac_games_available,
  nbac_coverage_pct,
  nbac_games_missing,

  -- OddsAPI Coverage
  oddsapi_games_available,
  oddsapi_coverage_pct,
  oddsapi_games_missing,

  -- Alert Level
  daily_alert_level as alert_level,
  CASE
    WHEN daily_alert_level = 'CRITICAL' THEN '🚨'
    WHEN daily_alert_level = 'WARNING' THEN '⚠️'
    ELSE '✅'
  END as status

FROM `nba-props-platform.nba_orchestration.v_scraper_availability_daily_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;


-- =============================================================================
-- 2. Missing Games Detail (Last 3 Days)
-- =============================================================================
-- Shows exactly which games are missing from each source

SELECT
  game_date,
  matchup,

  -- Availability by source
  bdl_available,
  nbac_available,
  oddsapi_available,

  -- Which source had it first
  first_available_source,

  -- Timing
  hours_since_game_end,
  availability_status,

  -- Latency
  bdl_latency_hours,
  nbac_latency_hours

FROM `nba-props-platform.nba_orchestration.v_scraper_game_availability`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND availability_status IN ('WARNING', 'CRITICAL')
ORDER BY game_date DESC, matchup;


-- =============================================================================
-- 3. Latency Trends (Last 7 Days)
-- =============================================================================
-- Average latency and slow game counts by source

SELECT
  game_date,

  -- BDL Latency
  ROUND(AVG(bdl_latency_hours), 1) as avg_bdl_latency_h,
  COUNT(CASE WHEN bdl_latency_hours > 4 THEN 1 END) as bdl_slow_count,
  COUNT(CASE WHEN bdl_latency_hours > 6 THEN 1 END) as bdl_very_slow_count,

  -- NBAC Latency
  ROUND(AVG(nbac_latency_hours), 1) as avg_nbac_latency_h,
  COUNT(CASE WHEN nbac_latency_hours > 2 THEN 1 END) as nbac_slow_count,

  -- Comparison
  COUNT(*) as total_games,
  COUNTIF(nbac_latency_hours < bdl_latency_hours) as nbac_faster_count

FROM `nba-props-platform.nba_orchestration.v_scraper_game_availability`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND bdl_available
GROUP BY game_date
ORDER BY game_date DESC;


-- =============================================================================
-- 4. West Coast Game Analysis (Last 7 Days)
-- =============================================================================
-- Identifies West Coast game patterns and issues

SELECT
  game_date,
  west_coast_games,
  west_coast_bdl_missing,

  -- Calculate West Coast miss rate
  CASE
    WHEN west_coast_games > 0
    THEN ROUND(100.0 * west_coast_bdl_missing / west_coast_games, 1)
    ELSE 0
  END as west_coast_miss_pct,

  -- Overall stats
  total_games,
  bdl_games_missing,
  ROUND(100.0 * bdl_games_missing / total_games, 1) as overall_miss_pct

FROM `nba-props-platform.nba_orchestration.v_scraper_availability_daily_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND total_games > 0
ORDER BY game_date DESC;


-- =============================================================================
-- 5. BDL Per-Game Attempts Timeline (If bdl_game_scrape_attempts has data)
-- =============================================================================
-- Shows timeline of scrape attempts for recent games
-- Note: This will only have data after scrapers start logging to the table

SELECT
  game_date,
  matchup,
  attempt_number,
  workflow,
  FORMAT_TIMESTAMP('%H:%M ET', scrape_timestamp, 'America/New_York') as checked_at,
  was_available,
  player_count,
  minutes_after_game_end,
  total_attempts,
  CASE
    WHEN was_available AND scrape_timestamp = first_seen_at THEN '✅ FIRST SEEN HERE'
    WHEN was_available THEN '✓ Available'
    ELSE '❌ Not available'
  END as status

FROM (
  SELECT
    a.game_date,
    CONCAT(a.away_team, ' @ ', a.home_team) as matchup,
    a.scrape_timestamp,
    a.was_available,
    a.player_count,
    a.workflow,
    TIMESTAMP_DIFF(a.scrape_timestamp, a.estimated_end_time, MINUTE) as minutes_after_game_end,
    ROW_NUMBER() OVER (
      PARTITION BY a.game_date, a.home_team, a.away_team
      ORDER BY a.scrape_timestamp
    ) as attempt_number,
    (
      SELECT MIN(scrape_timestamp)
      FROM `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts` b
      WHERE b.game_date = a.game_date
        AND b.home_team = a.home_team
        AND b.away_team = a.away_team
        AND b.was_available = TRUE
    ) as first_seen_at,
    (
      SELECT COUNT(*)
      FROM `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts` c
      WHERE c.game_date = a.game_date
        AND c.home_team = a.home_team
        AND c.away_team = a.away_team
    ) as total_attempts
  FROM `nba-props-platform.nba_orchestration.bdl_game_scrape_attempts` a
  WHERE a.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
)
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY game_date DESC, matchup, attempt_number;


-- =============================================================================
-- 6. First Availability Summary (From v_bdl_first_availability)
-- =============================================================================
-- Shows when games first appeared in BDL
-- Note: Only populated after scraper integration

SELECT
  game_date,
  matchup,
  first_available_at,
  FORMAT_TIMESTAMP('%H:%M ET', first_available_at, 'America/New_York') as first_seen_at_et,
  ROUND(latency_minutes / 60.0, 1) as latency_hours,
  attempts_before_available,
  is_west_coast,
  CASE
    WHEN latency_minutes IS NULL THEN '❌ Never Available'
    WHEN latency_minutes < 60 THEN '✅ Fast (< 1h)'
    WHEN latency_minutes < 120 THEN '✓ Normal (1-2h)'
    WHEN latency_minutes < 360 THEN '⚠️ Slow (2-6h)'
    ELSE '🚨 Very Slow (> 6h)'
  END as latency_category

FROM `nba-props-platform.nba_orchestration.v_bdl_first_availability`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC, latency_minutes DESC NULLS FIRST;


-- =============================================================================
-- QUICK CHECKS
-- =============================================================================

-- Quick check: Yesterday's overall status
/*
SELECT
  CONCAT('Yesterday (', CAST(game_date AS STRING), '): ',
         CAST(total_games AS STRING), ' games, ',
         'BDL: ', CAST(ROUND(bdl_coverage_pct, 1) AS STRING), '%, ',
         'NBAC: ', CAST(ROUND(nbac_coverage_pct, 1) AS STRING), '% - ',
         daily_alert_level) as summary
FROM `nba-props-platform.nba_orchestration.v_scraper_availability_daily_summary`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
*/

-- Quick check: Any missing games today or yesterday?
/*
SELECT
  game_date,
  matchup,
  CASE
    WHEN NOT bdl_available THEN 'Missing from BDL'
    WHEN NOT nbac_available THEN 'Missing from NBAC'
    WHEN NOT oddsapi_available THEN 'Missing from OddsAPI'
  END as issue
FROM `nba-props-platform.nba_orchestration.v_scraper_game_availability`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  AND (NOT bdl_available OR NOT nbac_available)
ORDER BY game_date DESC, matchup;
*/
