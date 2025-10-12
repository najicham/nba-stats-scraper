-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/schedule_horizon_check.sql
-- Purpose: Check how far ahead we have schedule data (freshness check)
-- Usage: Run regularly to ensure schedule updates are being captured
-- ============================================================================
-- Instructions:
--   1. No parameters needed - automatically checks from today forward
--   2. Monitors both regular season and playoff schedule data
--   3. Alerts if we have less than 7 days of future schedule
-- ============================================================================
-- Expected Results:
--   - During season: Should have 2-4 weeks of future schedule
--   - Off-season: May have limited data (only confirmed games)
--   - Playoffs: Schedule released series-by-series (shorter horizon normal)
-- ============================================================================

WITH
-- Get future schedule data
future_schedule AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    is_playoffs,
    is_regular_season,
    playoff_round
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date >= CURRENT_DATE()
    AND game_date >= CURRENT_DATE()  -- Partition filter
),

-- Calculate horizon metrics
horizon_stats AS (
  SELECT
    COUNT(DISTINCT game_id) as total_future_games,
    MIN(game_date) as nearest_game_date,
    MAX(game_date) as furthest_game_date,
    DATE_DIFF(MIN(game_date), CURRENT_DATE(), DAY) as days_to_next_game,
    DATE_DIFF(MAX(game_date), CURRENT_DATE(), DAY) as days_ahead,
    COUNT(DISTINCT CASE WHEN is_regular_season = TRUE THEN game_id END) as regular_season_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games,
    COUNT(DISTINCT game_date) as unique_game_dates
  FROM future_schedule
),

-- Get recent past for trend analysis
recent_past AS (
  SELECT
    COUNT(DISTINCT game_id) as games_last_7_days,
    MIN(game_date) as oldest_recent_game,
    MAX(game_date) as newest_recent_game
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)  -- Partition filter
),

-- Weekly breakdown of future schedule
weekly_breakdown AS (
  SELECT
    DATE_TRUNC(game_date, WEEK) as week_start,
    COUNT(DISTINCT game_id) as games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games,
    COUNT(DISTINCT CASE WHEN is_regular_season = TRUE THEN game_id END) as regular_games
  FROM future_schedule
  WHERE game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 28 DAY)  -- Next 4 weeks
  GROUP BY week_start
),

-- Determine health status
health_check AS (
  SELECT
    total_future_games,
    days_ahead,
    days_to_next_game,
    CASE
      WHEN total_future_games = 0 THEN '🔴 CRITICAL: No future games scheduled'
      WHEN days_ahead < 7 THEN '🔴 CRITICAL: Less than 1 week ahead'
      WHEN days_ahead < 14 THEN '🟡 WARNING: Less than 2 weeks ahead'
      WHEN days_ahead < 21 THEN '✅ OK: 2-3 weeks ahead'
      ELSE '✅ GOOD: 3+ weeks ahead'
    END as status,
    CASE
      WHEN days_to_next_game > 3 THEN '🟡 WARNING: >3 days until next game'
      WHEN days_to_next_game < 0 THEN '🔴 CRITICAL: No games today or upcoming'
      ELSE '✅ Normal'
    END as next_game_status
  FROM horizon_stats
)

-- Output 1: Overall horizon summary
SELECT
  '=== SCHEDULE HORIZON ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Current Date' as section,
  CAST(CURRENT_DATE() AS STRING) as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Future Games' as section,
  CAST(h.total_future_games AS STRING) as metric,
  CONCAT(CAST(hs.regular_season_games AS STRING), ' regular + ', CAST(hs.playoff_games AS STRING), ' playoff') as value,
  '' as status
FROM health_check h, horizon_stats hs

UNION ALL

SELECT
  'Next Game' as section,
  CAST(hs.nearest_game_date AS STRING) as metric,
  CONCAT('In ', CAST(hs.days_to_next_game AS STRING), ' days') as value,
  h.next_game_status as status
FROM health_check h, horizon_stats hs

UNION ALL

SELECT
  'Furthest Game' as section,
  CAST(hs.furthest_game_date AS STRING) as metric,
  CONCAT(CAST(h.days_ahead AS STRING), ' days ahead') as value,
  h.status as status
FROM health_check h, horizon_stats hs

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

-- Output 2: Recent activity
SELECT
  '=== RECENT ACTIVITY ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Last 7 Days' as section,
  CAST(games_last_7_days AS STRING) as metric,
  CONCAT('From ', CAST(oldest_recent_game AS STRING), ' to ', CAST(newest_recent_game AS STRING)) as value,
  CASE
    WHEN games_last_7_days = 0 THEN '⚪ Off-season or break'
    WHEN games_last_7_days < 20 THEN '🟡 Light schedule'
    ELSE '✅ Normal'
  END as status
FROM recent_past

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

-- Output 3: Weekly breakdown
SELECT
  '=== NEXT 4 WEEKS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  CONCAT('Week of ', CAST(week_start AS STRING)) as section,
  CAST(games AS STRING) as metric,
  CONCAT(CAST(regular_games AS STRING), ' regular + ', CAST(playoff_games AS STRING), ' playoff') as value,
  CASE
    WHEN games = 0 THEN '⚪ No games'
    WHEN games < 20 THEN '🟡 Light week'
    ELSE '✅ Normal'
  END as status
FROM weekly_breakdown;