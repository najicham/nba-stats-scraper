-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/discovery/discovery_query_2_event_volume.sql
-- ============================================================================
-- BigDataBall Play-by-Play Discovery Query 2: Event Volume by Date
-- Purpose: Understand event density and identify anomalies
-- ============================================================================
-- Look for:
--   - Consistent volume across dates? (400-600 events per game expected)
--   - Any dates with suspiciously low counts?
--   - Day-of-week patterns?
-- ============================================================================

WITH daily_stats AS (
  SELECT 
    game_date,
    COUNT(DISTINCT game_id) as games,
    COUNT(*) as total_events,
    ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_events_per_game,
    MIN(event_sequence) as min_sequence,
    MAX(event_sequence) as max_sequence,
    COUNT(DISTINCT player_1_lookup) as unique_players,
    FORMAT_DATE('%A', game_date) as day_of_week
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date >= '2024-01-01'  -- Adjust based on Discovery Query 1 results
  GROUP BY game_date
)
SELECT 
  game_date,
  day_of_week,
  games,
  total_events,
  avg_events_per_game,
  min_sequence,
  max_sequence,
  unique_players,
  CASE
    WHEN avg_events_per_game < 300 THEN '🔴 CRITICALLY LOW'
    WHEN avg_events_per_game < 400 THEN '⚠️ LOW'
    WHEN avg_events_per_game > 700 THEN '⚠️ UNUSUALLY HIGH'
    ELSE '✅ Normal'
  END as status
FROM daily_stats
ORDER BY game_date DESC
LIMIT 100;

-- Red Flags:
-- 🔴 avg_events_per_game < 300: Incomplete data
-- ⚠️ avg_events_per_game < 400: Possible data quality issue
-- ⚠️ avg_events_per_game > 700: Check for overtime games or duplicates
