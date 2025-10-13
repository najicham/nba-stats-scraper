-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/daily_check_yesterday.sql
-- ============================================================================
-- Purpose: Daily morning check to verify yesterday's games were captured
-- Usage: Run every morning as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM (after scraper/processor complete)
--   2. Set up alerts for status != "✅ Complete" or "✅ No games scheduled"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all games captured
--   - status = "✅ No games scheduled" on off days
--   - status = "❌ CRITICAL" requires immediate investigation
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Get per-game event counts and quality metrics
game_event_counts AS (
  SELECT
    game_id,
    COUNT(*) as events_per_game,
    COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shots_per_game,
    COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as shots_with_coords,
    MIN(event_sequence) as first_sequence,
    MAX(event_sequence) as last_sequence,
    COUNT(DISTINCT away_player_1_lookup) + COUNT(DISTINCT home_player_1_lookup) as unique_players
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY game_id
),

-- Get overall stats
yesterday_pbp AS (
  SELECT
    (SELECT COUNT(DISTINCT game_id) FROM game_event_counts) as games_with_data,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bigdataball_play_by_play` 
     WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as total_events,
    ROUND(AVG(events_per_game), 1) as avg_events_per_game,
    MIN(events_per_game) as min_events_per_game,
    MAX(events_per_game) as max_events_per_game,
    ROUND(AVG(shots_per_game), 1) as avg_shots_per_game,
    ROUND(AVG(shots_with_coords * 100.0 / NULLIF(shots_per_game, 0)), 1) as pct_shots_with_coords,
    MIN(unique_players) as min_players
  FROM game_event_counts
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  s.scheduled_games,
  p.games_with_data,
  p.total_events,
  p.avg_events_per_game,
  p.min_events_per_game,
  p.max_events_per_game,
  p.avg_shots_per_game,
  p.pct_shots_with_coords,
  p.min_players,
  CASE
    WHEN s.scheduled_games = 0 THEN '✅ No games scheduled'
    WHEN p.games_with_data = s.scheduled_games 
     AND p.min_events_per_game >= 400
     AND p.pct_shots_with_coords >= 70
     AND p.min_players >= 15
    THEN '✅ Complete'
    WHEN p.games_with_data = 0 THEN '❌ CRITICAL: No play-by-play data'
    WHEN p.min_events_per_game < 300 THEN '❌ CRITICAL: Very low event count'
    WHEN p.min_events_per_game < 400 THEN '⚠️ WARNING: Low event count'
    WHEN p.pct_shots_with_coords < 70 THEN '⚠️ WARNING: Poor coordinate coverage'
    WHEN p.min_players < 15 THEN '⚠️ WARNING: Low player coverage'
    ELSE CONCAT('⚠️ WARNING: ', CAST(s.scheduled_games - p.games_with_data AS STRING), ' games missing')
  END as status
FROM yesterday_schedule s
CROSS JOIN yesterday_pbp p;

-- Quality Thresholds:
-- ✅ Complete: 400+ events, 70%+ coord coverage, 15+ players
-- ⚠️ Warning: 300-399 events OR <70% coords OR <15 players
-- ❌ Critical: <300 events OR no data at all
