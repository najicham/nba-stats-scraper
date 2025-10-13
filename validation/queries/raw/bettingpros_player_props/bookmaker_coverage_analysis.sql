-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/bookmaker_coverage_analysis.sql
-- Purpose: Analyze which bookmakers are providing BettingPros data
-- Usage: Run to understand bookmaker participation and coverage trends
-- ============================================================================
-- Expected Results:
--   - 15-20 active bookmakers in recent data
--   - DraftKings, FanDuel, BetMGM, Caesars should be consistent
--   - Drops in coverage may indicate API issues or market changes
-- ============================================================================

WITH recent_bookmaker_stats AS (
  SELECT
    bookmaker,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as dates_covered,
    COUNT(DISTINCT player_lookup) as unique_players,
    MIN(game_date) as first_seen,
    MAX(game_date) as last_seen,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    COUNT(CASE WHEN validation_confidence >= 0.7 THEN 1 END) as high_confidence_records
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)  -- Last 30 days
  GROUP BY bookmaker
),

daily_bookmaker_count AS (
  SELECT
    game_date,
    COUNT(DISTINCT bookmaker) as active_bookmakers
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY game_date
)

(
-- Bookmaker summary with daily trend
SELECT
  'BOOKMAKER' as result_type,
  bookmaker as detail1,
  CAST(total_records AS STRING) as detail2,
  CAST(dates_covered AS STRING) as detail3,
  CAST(unique_players AS STRING) as detail4,
  CAST(avg_confidence AS STRING) as detail5,
  CAST(DATE_DIFF(CURRENT_DATE(), last_seen, DAY) AS STRING) as detail6,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), last_seen, DAY) > 7 THEN
      CONCAT('🔴 MISSING: Last seen ', CAST(DATE_DIFF(CURRENT_DATE(), last_seen, DAY) AS STRING), ' days ago')
    WHEN DATE_DIFF(CURRENT_DATE(), last_seen, DAY) > 3 THEN
      CONCAT('🟡 WARNING: Last seen ', CAST(DATE_DIFF(CURRENT_DATE(), last_seen, DAY) AS STRING), ' days ago')
    WHEN total_records < 100 THEN '🟡 Low volume bookmaker'
    ELSE '✅ Active'
  END as status
FROM recent_bookmaker_stats

UNION ALL

-- Section separator
SELECT
  'SEPARATOR' as result_type,
  'Daily Trend (Last 30 Days)' as detail1,
  '---' as detail2,
  '' as detail3,
  '' as detail4,
  '' as detail5,
  '' as detail6,
  '' as status

UNION ALL

-- Daily bookmaker trend
SELECT
  'DAILY' as result_type,
  CAST(game_date AS STRING) as detail1,
  FORMAT_DATE('%A', game_date) as detail2,
  CAST(active_bookmakers AS STRING) as detail3,
  '' as detail4,
  '' as detail5,
  '' as detail6,
  CASE
    WHEN active_bookmakers < 10 THEN '🔴 CRITICAL: Low bookmaker coverage'
    WHEN active_bookmakers < 15 THEN '🟡 WARNING: Below normal coverage'
    ELSE '✅ Good coverage'
  END as status
FROM daily_bookmaker_count
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY result_type, detail1 DESC
LIMIT 50
);