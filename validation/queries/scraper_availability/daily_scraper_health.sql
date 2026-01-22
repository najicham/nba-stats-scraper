-- File: validation/queries/scraper_availability/daily_scraper_health.sql
-- ============================================================================
-- Daily Scraper Health Check
-- ============================================================================
-- Purpose: Check scraper data availability and latency for yesterday's games.
--          Run as part of daily validation to catch late/missing data.
--
-- Created: January 22, 2026
-- Usage: Run after morning_recovery workflow (after 6 AM ET)
--
-- Expected Thresholds:
--   nbac_gamebook:      100% coverage, <4h P90 latency
--   bdl_box_scores:     90% coverage, <12h P90 latency
--   oddsa_player_props: 80% coverage, <6h P90 latency
-- ============================================================================

-- Query 1: Daily scraper health summary
SELECT
  scraper_name,
  total_games,
  games_with_data,
  coverage_pct,
  latency_p50_hours AS p50_hours,
  latency_p90_hours AS p90_hours,
  never_available_count AS missing_games,
  health_score,
  CASE
    WHEN scraper_name = 'nbac_gamebook' AND coverage_pct < 100 THEN '🔴 CRITICAL'
    WHEN scraper_name = 'bdl_box_scores' AND coverage_pct < 90 THEN '🟡 WARNING'
    WHEN scraper_name = 'oddsa_player_props' AND coverage_pct < 80 THEN '🟡 WARNING'
    WHEN health_score < 50 THEN '🟡 WARNING'
    ELSE '✅ OK'
  END AS status
FROM `nba-props-platform.nba_orchestration.v_scraper_latency_daily`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY coverage_pct ASC;


-- Query 2: Games missing critical data (NBAC or all sources)
/*
SELECT
  game_date,
  matchup,
  nbac_status,
  bdl_status,
  odds_status,
  availability_status
FROM `nba-props-platform.nba_orchestration.v_game_data_timeline`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND availability_status != 'OK'
ORDER BY home_team;
*/


-- Query 3: Games needing BDL catch-up retry
/*
SELECT
  game_date,
  matchup,
  is_west_coast,
  nbac_latency_minutes AS nbac_mins,
  bdl_status
FROM `nba-props-platform.nba_orchestration.v_game_data_timeline`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND bdl_status = 'NEVER_AVAILABLE'
  AND nbac_status != 'NEVER_AVAILABLE'
ORDER BY game_date DESC;
*/


-- Query 4: Scraper latency trend (last 7 days)
/*
SELECT
  game_date,
  scraper_name,
  coverage_pct,
  latency_p50_hours,
  health_score
FROM `nba-props-platform.nba_orchestration.v_scraper_latency_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY scraper_name, game_date;
*/
