-- File: validation/queries/raw/nbac_play_by_play/daily_check_yesterday.sql
-- ============================================================================
-- Daily Check - Yesterday's Play-by-Play
-- Purpose: Quick validation for most recent games processed
-- Run every morning to verify yesterday's collection
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT 
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND game_status_text IN ('Final', 'Completed')
    AND is_playoffs = FALSE
),

yesterday_pbp AS (
  SELECT 
    COUNT(DISTINCT game_id) as processed_games,
    SUM(CASE WHEN total_events >= 450 THEN 1 ELSE 0 END) as games_with_good_count,
    SUM(CASE WHEN unique_players >= 15 THEN 1 ELSE 0 END) as games_with_good_coverage
  FROM (
    SELECT 
      game_id,
      COUNT(*) as total_events,
      COUNT(DISTINCT player_1_id) as unique_players
    FROM `nba-props-platform.nba_raw.nbac_play_by_play`
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    GROUP BY game_id
  )
)

SELECT 
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  COALESCE(p.processed_games, 0) as processed_games,
  COALESCE(p.games_with_good_count, 0) as games_with_good_count,
  COALESCE(p.games_with_good_coverage, 0) as games_with_good_coverage,
  CASE
    WHEN s.scheduled_games = 0 THEN '⚪ No games scheduled'
    WHEN COALESCE(p.processed_games, 0) = 0 THEN '🔴 CRITICAL: No play-by-play data'
    WHEN COALESCE(p.processed_games, 0) < s.scheduled_games THEN '⚠️ WARNING: Missing games'
    WHEN COALESCE(p.games_with_good_count, 0) < p.processed_games THEN '⚠️ WARNING: Some games have low event counts'
    ELSE '✅ Complete'
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_pbp p;
