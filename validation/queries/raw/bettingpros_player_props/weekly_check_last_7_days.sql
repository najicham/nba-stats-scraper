-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/weekly_check_last_7_days.sql
-- Purpose: Review BettingPros props coverage trends over the last 7 days
-- Usage: Run weekly to monitor data quality and identify trends
-- ============================================================================
-- Expected Results:
--   - Consistent coverage across game days
--   - 30-60 props per game in regular season
--   - 15-20 active bookmakers per day
-- ============================================================================

WITH last_7_days AS (
  SELECT
    game_date,
    FORMAT_DATE('%A', game_date) as day_of_week,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bookmaker) as unique_bookmakers,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    COUNT(CASE WHEN validation_confidence >= 0.7 THEN 1 END) as high_confidence_records,
    COUNT(CASE WHEN validation_confidence = 0.3 THEN 1 END) as medium_confidence_records,
    COUNT(CASE WHEN validation_confidence = 0.1 THEN 1 END) as low_confidence_records,
    MIN(points_line) as min_line,
    MAX(points_line) as max_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
  GROUP BY game_date
),

scheduled_games AS (
  SELECT
    game_date,
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
    AND is_playoffs = FALSE
  GROUP BY game_date
)

(
-- Daily details with weekly summary
SELECT
  'DAILY' as result_type,
  CAST(l.game_date AS STRING) as detail1,
  l.day_of_week as detail2,
  CAST(COALESCE(s.scheduled_games, 0) AS STRING) as detail3,
  CAST(l.total_records AS STRING) as detail4,
  CAST(l.high_confidence_records AS STRING) as detail5,
  CAST(l.unique_bookmakers AS STRING) as detail6,
  CASE
    WHEN l.total_records IS NULL THEN '⚪ No games scheduled'
    WHEN l.high_confidence_records = 0 THEN '🔴 CRITICAL: No high-confidence data'
    WHEN l.avg_confidence < 0.6 THEN
      CONCAT('🟡 WARNING: Low confidence (', CAST(l.avg_confidence AS STRING), ')')
    WHEN l.total_records < 100 AND s.scheduled_games > 0 THEN
      '🟡 WARNING: Low record count'
    WHEN l.unique_bookmakers < 10 THEN
      CONCAT('🟡 WARNING: Low bookmaker coverage (', CAST(l.unique_bookmakers AS STRING), ')')
    ELSE '✅ Good'
  END as status
FROM last_7_days l
LEFT JOIN scheduled_games s ON l.game_date = s.game_date

UNION ALL

-- Section separator
SELECT
  'SEPARATOR' as result_type,
  'Weekly Summary' as detail1,
  '---' as detail2,
  '' as detail3,
  '' as detail4,
  '' as detail5,
  '' as detail6,
  '' as status

UNION ALL

-- Weekly summary
SELECT
  'SUMMARY' as result_type,
  'Week Total' as detail1,
  CAST(COUNT(DISTINCT game_date) AS STRING) as detail2,
  CAST(SUM(total_records) AS STRING) as detail3,
  CAST(ROUND(AVG(total_records), 1) AS STRING) as detail4,
  CAST(ROUND(AVG(unique_bookmakers), 1) AS STRING) as detail5,
  CAST(ROUND(AVG(avg_confidence), 2) AS STRING) as detail6,
  CASE
    WHEN AVG(avg_confidence) < 0.6 THEN '🟡 Low confidence week'
    WHEN AVG(unique_bookmakers) < 10 THEN '🟡 Low bookmaker coverage'
    ELSE '✅ Good week'
  END as status
FROM last_7_days
ORDER BY result_type DESC, detail1 DESC
);