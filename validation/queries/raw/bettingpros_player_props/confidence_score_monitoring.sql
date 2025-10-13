-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/confidence_score_monitoring.sql
-- Purpose: Monitor BettingPros validation confidence scores by date
-- Usage: Run to understand data freshness and betting relevance
-- ============================================================================
-- Confidence Score Meanings:
--   0.95 = Same-day games (maximum betting confidence)
--   0.70 = Games within 1 month (high relevance)
--   0.30 = Games within 1 year (trend analysis)
--   0.10 = Games >1 year old (historical analysis only)
-- ============================================================================
-- Expected Results:
--   - Recent dates should have primarily 0.95 confidence
--   - Historical dates should show 0.1-0.3 confidence
--   - Sudden drops may indicate processing timing issues
-- ============================================================================

WITH daily_confidence AS (
  SELECT
    game_date,
    validation_confidence,
    COUNT(*) as record_count,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bookmaker) as unique_bookmakers,
    MIN(points_line) as min_line,
    MAX(points_line) as max_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)  -- Last 90 days
  GROUP BY game_date, validation_confidence
),

daily_summary AS (
  SELECT
    game_date,
    FORMAT_DATE('%A', game_date) as day_of_week,
    SUM(record_count) as total_records,
    SUM(CASE WHEN validation_confidence >= 0.7 THEN record_count ELSE 0 END) as high_confidence_records,
    SUM(CASE WHEN validation_confidence = 0.3 THEN record_count ELSE 0 END) as medium_confidence_records,
    SUM(CASE WHEN validation_confidence = 0.1 THEN record_count ELSE 0 END) as low_confidence_records,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    MAX(unique_players) as max_players,
    MAX(unique_bookmakers) as max_bookmakers
  FROM daily_confidence
  GROUP BY game_date
)

SELECT
  game_date,
  day_of_week,
  total_records,
  high_confidence_records,
  medium_confidence_records,
  low_confidence_records,
  avg_confidence,
  max_players,
  max_bookmakers,
  ROUND(100.0 * high_confidence_records / NULLIF(total_records, 0), 1) as high_conf_pct,
  CASE
    WHEN total_records = 0 THEN '⚪ No data'
    WHEN high_confidence_records = 0 THEN '🔴 CRITICAL: No high-confidence data'
    WHEN avg_confidence < 0.5 THEN
      CONCAT('🟡 WARNING: Low avg confidence (', CAST(avg_confidence AS STRING), ')')
    WHEN high_confidence_records < total_records * 0.8 THEN
      '🟡 Mixed confidence - review processing timing'
    ELSE '✅ Good confidence distribution'
  END as status,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), game_date, DAY) = 0 THEN 'Expected: 0.95'
    WHEN DATE_DIFF(CURRENT_DATE(), game_date, DAY) <= 30 THEN 'Expected: 0.70-0.95'
    WHEN DATE_DIFF(CURRENT_DATE(), game_date, DAY) <= 365 THEN 'Expected: 0.30'
    ELSE 'Expected: 0.10'
  END as expected_confidence
FROM daily_summary
ORDER BY game_date DESC
LIMIT 100;
