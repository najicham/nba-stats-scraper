-- File: validation/queries/raw/nbac_play_by_play/weekly_check_last_7_days.sql
-- ============================================================================
-- Weekly Trend Check
-- Purpose: Monitor play-by-play data collection over past 7 days
-- Tracks daily collection consistency and identifies gaps
-- ============================================================================

SELECT 
  game_date,
  FORMAT_DATE('%A', game_date) as day_of_week,
  COUNT(DISTINCT game_id) as games_collected,
  SUM(event_count) as total_events,
  ROUND(AVG(event_count), 0) as avg_events_per_game,
  ROUND(AVG(unique_players), 1) as avg_players_per_game,
  ROUND(AVG(shot_events), 0) as avg_shots_per_game
FROM (
  SELECT 
    game_date,
    game_id,
    COUNT(*) as event_count,
    COUNT(DISTINCT player_1_id) as unique_players,
    COUNT(CASE WHEN shot_made IS NOT NULL THEN 1 END) as shot_events
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date, game_id
)
GROUP BY game_date
ORDER BY game_date DESC;
