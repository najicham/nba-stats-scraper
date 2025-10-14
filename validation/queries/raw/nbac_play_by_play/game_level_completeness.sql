-- File: validation/queries/raw/nbac_play_by_play/game_level_completeness.sql
-- ============================================================================
-- Game-Level Completeness Check
-- Purpose: Verify play-by-play games have expected event volume and player coverage
-- Pattern: Pattern 3 - Variable events per game, validate reasonable ranges
-- ============================================================================

WITH game_summary AS (
  SELECT 
    game_date,
    game_id,
    nba_game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as total_events,
    COUNT(DISTINCT player_1_id) as unique_players,
    COUNT(DISTINCT CASE WHEN player_1_team_abbr = home_team_abbr THEN player_1_lookup END) as home_players,
    COUNT(DISTINCT CASE WHEN player_1_team_abbr = away_team_abbr THEN player_1_lookup END) as away_players,
    COUNT(DISTINCT period) as periods_played,
    MAX(score_home) as final_home_score,
    MAX(score_away) as final_away_score,
    COUNT(CASE WHEN shot_made IS NOT NULL THEN 1 END) as shot_events,
    COUNT(CASE WHEN event_type = 'foul' THEN 1 END) as foul_events,
    COUNT(CASE WHEN event_type = 'rebound' THEN 1 END) as rebound_events,
    MIN(event_sequence) as first_event,
    MAX(event_sequence) as last_event
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'  -- Partition filter required
  GROUP BY game_date, game_id, nba_game_id, home_team_abbr, away_team_abbr
)

SELECT 
  game_date,
  game_id,
  home_team_abbr || ' vs ' || away_team_abbr as matchup,
  total_events,
  unique_players,
  home_players,
  away_players,
  periods_played,
  final_home_score,
  final_away_score,
  shot_events,
  -- Validation flags
  CASE 
    WHEN total_events < 400 THEN '🔴 CRITICAL: Too few events (<400)'
    WHEN total_events < 450 THEN '⚠️ WARNING: Low event count (<450)'
    WHEN total_events > 700 THEN '⚠️ WARNING: High event count (>700, verify OT)'
    ELSE '✅ Good'
  END as event_count_status,
  CASE 
    WHEN unique_players < 15 THEN '🔴 CRITICAL: Too few players (<15)'
    WHEN unique_players < 16 THEN '⚠️ WARNING: Low player count (<16)'
    WHEN unique_players > 25 THEN '⚠️ INFO: Many players (>25, lots of rotation)'
    ELSE '✅ Good'
  END as player_coverage_status,
  CASE
    WHEN home_players < 7 THEN '⚠️ WARNING: Low home player count'
    WHEN away_players < 7 THEN '⚠️ WARNING: Low away player count'
    ELSE '✅ Good'
  END as team_coverage_status,
  CASE
    WHEN periods_played > 4 THEN '🏀 Overtime Game'
    WHEN periods_played < 4 THEN '🔴 CRITICAL: Incomplete game (<4 periods)'
    ELSE '✅ Regulation'
  END as period_status
FROM game_summary
ORDER BY game_date DESC;
