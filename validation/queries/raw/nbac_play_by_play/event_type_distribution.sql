-- File: validation/queries/raw/nbac_play_by_play/event_type_distribution.sql
-- ============================================================================
-- Event Type Distribution Analysis
-- Purpose: Monitor event type coverage and detect data quality issues
-- Validates all expected event types are being captured
-- ============================================================================

WITH event_stats AS (
  SELECT 
    game_date,
    game_id,
    event_type,
    event_action_type,
    COUNT(*) as event_count,
    COUNT(CASE WHEN player_1_id IS NOT NULL THEN 1 END) as events_with_player,
    COUNT(CASE WHEN shot_made = true THEN 1 END) as shots_made,
    COUNT(CASE WHEN shot_made = false THEN 1 END) as shots_missed
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
  GROUP BY game_date, game_id, event_type, event_action_type
)

SELECT 
  event_type,
  event_action_type,
  SUM(event_count) as total_events,
  COUNT(DISTINCT game_id) as games_with_event,
  ROUND(AVG(event_count), 1) as avg_per_game,
  SUM(events_with_player) as events_with_player,
  SUM(shots_made) as total_made,
  SUM(shots_missed) as total_missed,
  -- Calculate shooting percentage for shot events
  CASE 
    WHEN event_type IN ('2pt', '3pt', 'freethrow') AND (SUM(shots_made) + SUM(shots_missed)) > 0 
    THEN ROUND(100.0 * SUM(shots_made) / (SUM(shots_made) + SUM(shots_missed)), 1)
    ELSE NULL
  END as shot_pct
FROM event_stats
GROUP BY event_type, event_action_type
ORDER BY total_events DESC;
