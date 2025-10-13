-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/daily_check_yesterday.sql
-- Purpose: Daily morning check to verify yesterday's BettingPros props coverage
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Focus: High-confidence data (>= 0.7) for betting relevance
-- Expected: 30-60 props/game regular season, 40-50 props/game playoffs
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_playoffs = FALSE  -- Set to TRUE during playoffs
),

yesterday_props_all AS (
  SELECT
    COUNT(DISTINCT game_date) as dates_with_props,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as total_unique_players,
    COUNT(DISTINCT bookmaker) as total_unique_bookmakers,
    ROUND(AVG(validation_confidence), 2) as avg_confidence,
    COUNT(CASE WHEN validation_confidence >= 0.7 THEN 1 END) as high_confidence_records,
    COUNT(CASE WHEN validation_confidence < 0.3 THEN 1 END) as low_confidence_records
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

yesterday_props_per_game AS (
  SELECT
    ROUND(AVG(props_per_game), 1) as avg_props_per_game,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(props_per_game) as min_props_per_game,
    MAX(props_per_game) as max_props_per_game
  FROM (
    SELECT
      game_date,
      COUNT(*) as props_per_game,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
      AND validation_confidence >= 0.7  -- Focus on high-confidence data
    GROUP BY game_date
  )
),

bookmaker_coverage AS (
  SELECT
    COUNT(DISTINCT bookmaker) as active_bookmakers,
    STRING_AGG(DISTINCT bookmaker ORDER BY bookmaker LIMIT 5) as top_bookmakers
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND validation_confidence >= 0.7
),

games_with_low_coverage AS (
  SELECT
    COUNT(*) as low_coverage_games
  FROM (
    SELECT
      game_date,
      COUNT(*) as props_per_game
    FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
      AND validation_confidence >= 0.7
    GROUP BY game_date
    HAVING COUNT(*) < 30
  )
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  pa.dates_with_props as games_with_props,
  pa.total_records,
  pa.high_confidence_records,
  pa.low_confidence_records,
  pa.total_unique_players,
  pa.avg_confidence,
  pg.avg_props_per_game,
  pg.avg_players_per_game,
  pg.min_props_per_game,
  pg.max_props_per_game,
  b.active_bookmakers,
  l.low_coverage_games,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN pa.dates_with_props = 0 THEN '❌ CRITICAL: No props data at all'
    WHEN pa.high_confidence_records = 0 THEN '🔴 CRITICAL: No high-confidence data'
    WHEN pg.avg_props_per_game < 30.0 THEN
      CONCAT('🟡 WARNING: Low coverage (', CAST(pg.avg_props_per_game AS STRING), ' props/game)')
    WHEN pa.avg_confidence < 0.6 THEN
      CONCAT('🟡 WARNING: Low confidence avg (', CAST(pa.avg_confidence AS STRING), ')')
    WHEN l.low_coverage_games > 0 THEN
      CONCAT('⚠️ WARNING: ', CAST(l.low_coverage_games AS STRING), ' games with <30 props')
    ELSE '✅ Complete'
  END as status,
  CASE
    WHEN b.active_bookmakers < 10 THEN
      CONCAT('⚠️ Low bookmaker coverage (', CAST(b.active_bookmakers AS STRING), ' books)')
    WHEN b.active_bookmakers >= 15 THEN
      CONCAT('✅ Excellent coverage (', CAST(b.active_bookmakers AS STRING), ' books)')
    ELSE
      CONCAT('✅ Good coverage (', CAST(b.active_bookmakers AS STRING), ' books)')
  END as bookmaker_status,
  b.top_bookmakers
FROM yesterday_schedule s
CROSS JOIN yesterday_props_all pa
CROSS JOIN yesterday_props_per_game pg
CROSS JOIN bookmaker_coverage b
CROSS JOIN games_with_low_coverage l;
