-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/daily_freshness_check.sql
-- Purpose: Daily morning check to verify yesterday's games are in schedule
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when yesterday's games present
--   - status = "✅ No games scheduled" on off days (All-Star break, etc.)
--   - status = "❌ CRITICAL" requires immediate investigation
-- ============================================================================

WITH 
-- Check if yesterday had games (look at historical pattern + schedule table)
yesterday_games AS (
  SELECT
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
    COUNT(DISTINCT game_id) as games_found,
    COUNT(DISTINCT CASE WHEN is_regular_season = TRUE THEN game_id END) as regular_season_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games,
    COUNT(DISTINCT home_team_tricode) as home_teams,
    COUNT(DISTINCT away_team_tricode) as away_teams,
    -- Enhanced field checks
    COUNT(CASE WHEN is_primetime IS NULL THEN 1 END) as null_primetime,
    COUNT(CASE WHEN primary_network IS NULL THEN 1 END) as null_network,
    -- Special event detection
    MAX(CASE WHEN is_christmas = TRUE THEN 1 ELSE 0 END) as is_christmas_day,
    MAX(CASE WHEN is_mlk_day = TRUE THEN 1 ELSE 0 END) as is_mlk_day,
    MAX(CASE WHEN is_all_star = TRUE THEN 1 ELSE 0 END) as is_all_star
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Partition filter
),

-- Get today's games for context
today_games AS (
  SELECT
    COUNT(DISTINCT game_id) as games_today
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
    AND game_date >= CURRENT_DATE()  -- Partition filter
),

-- Get tomorrow's games for horizon check
tomorrow_games AS (
  SELECT
    COUNT(DISTINCT game_id) as games_tomorrow
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
    AND game_date >= CURRENT_DATE()  -- Partition filter
),

-- Historical average for this day of week
day_of_week_average AS (
  SELECT
    AVG(daily_games) as avg_games_for_dow
  FROM (
    SELECT 
      game_date,
      COUNT(DISTINCT game_id) as daily_games
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE FORMAT_DATE('%A', game_date) = FORMAT_DATE('%A', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
      AND is_regular_season = TRUE
      AND game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY) AND CURRENT_DATE()
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)  -- Partition filter
    GROUP BY game_date
  )
),

-- Determine status
status_check AS (
  SELECT
    y.check_date,
    y.games_found,
    y.regular_season_games,
    y.playoff_games,
    d.avg_games_for_dow,
    t.games_today,
    tm.games_tomorrow,
    -- Primary status
    CASE
      WHEN y.games_found = 0 AND d.avg_games_for_dow > 5 THEN '❌ CRITICAL: Expected games but found none'
      WHEN y.games_found = 0 AND d.avg_games_for_dow <= 5 THEN '✅ No games scheduled (expected)'
      WHEN y.games_found > 0 AND y.null_primetime > 0 THEN '🟡 WARNING: Games found but missing enhanced fields'
      WHEN y.games_found > 0 THEN '✅ Complete'
      ELSE '❓ Unknown status'
    END as status,
    -- Data quality status
    CASE
      WHEN y.null_primetime > 0 OR y.null_network > y.games_found * 0.5 
      THEN '🔴 Enhanced fields incomplete'
      ELSE '✅ Enhanced fields OK'
    END as field_quality_status,
    -- Context
    CASE
      WHEN y.is_christmas_day = 1 THEN '🎄 Christmas Day'
      WHEN y.is_mlk_day = 1 THEN '✊ MLK Day'
      WHEN y.is_all_star = 1 THEN '⭐ All-Star'
      WHEN y.playoff_games > 0 THEN '🏀 Playoff Games'
      ELSE 'Regular Day'
    END as day_context
  FROM yesterday_games y
  CROSS JOIN day_of_week_average d
  CROSS JOIN today_games t
  CROSS JOIN tomorrow_games tm
)

-- Output: Yesterday's status with context
SELECT
  '=== YESTERDAY CHECK ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Date' as section,
  CAST(check_date AS STRING) as metric,
  FORMAT_DATE('%A', check_date) as value,
  day_context as status
FROM status_check

UNION ALL

SELECT
  'Games Found' as section,
  CAST(games_found AS STRING) as metric,
  CONCAT(
    CAST(regular_season_games AS STRING), ' regular + ',
    CAST(playoff_games AS STRING), ' playoff'
  ) as value,
  status as status
FROM status_check

UNION ALL

SELECT
  'Enhanced Fields' as section,
  field_quality_status as metric,
  '' as value,
  '' as status
FROM status_check

UNION ALL

SELECT
  'Historical Average' as section,
  CONCAT('~', CAST(ROUND(avg_games_for_dow, 0) AS STRING), ' games') as metric,
  CONCAT('For ', FORMAT_DATE('%A', check_date), 's') as value,
  '' as status
FROM status_check

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

-- Output 2: Today and tomorrow context
SELECT
  '=== UPCOMING ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Today' as section,
  CAST(CURRENT_DATE() AS STRING) as metric,
  CONCAT(CAST(games_today AS STRING), ' games scheduled') as value,
  CASE 
    WHEN games_today = 0 THEN '⚪ Off day'
    ELSE '✅'
  END as status
FROM status_check

UNION ALL

SELECT
  'Tomorrow' as section,
  CAST(DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY) AS STRING) as metric,
  CONCAT(CAST(games_tomorrow AS STRING), ' games scheduled') as value,
  CASE 
    WHEN games_tomorrow = 0 THEN '⚪ Off day'
    ELSE '✅'
  END as status
FROM status_check;
