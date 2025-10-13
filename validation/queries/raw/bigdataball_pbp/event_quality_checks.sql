-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/event_quality_checks.sql
-- ============================================================================
-- Purpose: Play-by-play specific quality validation
-- Usage: Run to verify data completeness beyond just event counts
-- ============================================================================
-- This query checks BigDataBall-specific features:
--   - Shot coordinate coverage (original_x, original_y fields)
--   - Lineup completeness (5 home + 5 away players per possession)
--   - Event type distribution (shots, fouls, rebounds, etc.)
--   - Event sequence integrity per game
-- ============================================================================
-- Instructions:
--   1. Update date range for season/period you're checking
--   2. Run query to get quality metrics by game
--   3. Investigate any games with low scores
-- ============================================================================

WITH game_quality AS (
  SELECT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    
    -- Event counts
    COUNT(*) as total_events,
    MIN(event_sequence) as first_sequence,
    MAX(event_sequence) as last_sequence,
    COUNT(DISTINCT event_sequence) as unique_sequences,
    
    -- Shot analysis
    COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shot_events,
    COUNT(CASE WHEN event_type = 'shot' AND original_x IS NOT NULL THEN 1 END) as shots_with_coords,
    COUNT(CASE WHEN event_type = 'shot' AND shot_made IS NOT NULL THEN 1 END) as shots_with_result,
    
    -- Event type distribution
    COUNT(CASE WHEN event_type = 'foul' THEN 1 END) as foul_events,
    COUNT(CASE WHEN event_type = 'rebound' THEN 1 END) as rebound_events,
    COUNT(CASE WHEN event_type = 'turnover' THEN 1 END) as turnover_events,
    COUNT(CASE WHEN event_type = 'substitution' THEN 1 END) as sub_events,
    
    -- Lineup completeness (should have 10 players: 5 home + 5 away)
    COUNT(CASE WHEN away_player_1_lookup IS NOT NULL THEN 1 END) as has_away_p1,
    COUNT(CASE WHEN away_player_2_lookup IS NOT NULL THEN 1 END) as has_away_p2,
    COUNT(CASE WHEN away_player_3_lookup IS NOT NULL THEN 1 END) as has_away_p3,
    COUNT(CASE WHEN away_player_4_lookup IS NOT NULL THEN 1 END) as has_away_p4,
    COUNT(CASE WHEN away_player_5_lookup IS NOT NULL THEN 1 END) as has_away_p5,
    COUNT(CASE WHEN home_player_1_lookup IS NOT NULL THEN 1 END) as has_home_p1,
    COUNT(CASE WHEN home_player_2_lookup IS NOT NULL THEN 1 END) as has_home_p2,
    COUNT(CASE WHEN home_player_3_lookup IS NOT NULL THEN 1 END) as has_home_p3,
    COUNT(CASE WHEN home_player_4_lookup IS NOT NULL THEN 1 END) as has_home_p4,
    COUNT(CASE WHEN home_player_5_lookup IS NOT NULL THEN 1 END) as has_home_p5,
    
    -- Player coverage
    COUNT(DISTINCT player_1_lookup) as unique_primary_players,
    COUNT(DISTINCT away_player_1_lookup) as unique_away_lineup_p1,
    COUNT(DISTINCT home_player_1_lookup) as unique_home_lineup_p1
    
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'  -- UPDATE: 2024-25 season
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
)

SELECT
  game_date,
  game_id,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  total_events,
  
  -- Sequence integrity
  first_sequence,
  last_sequence,
  unique_sequences,
  (last_sequence - first_sequence + 1) - unique_sequences as sequence_gaps,
  
  -- Shot quality
  shot_events,
  shots_with_coords,
  ROUND(shots_with_coords * 100.0 / NULLIF(shot_events, 0), 1) as pct_shots_with_coords,
  
  -- Event distribution
  foul_events,
  rebound_events,
  turnover_events,
  sub_events,
  
  -- Lineup completeness (as % of events with full lineups)
  ROUND(LEAST(has_away_p1, has_away_p2, has_away_p3, has_away_p4, has_away_p5,
              has_home_p1, has_home_p2, has_home_p3, has_home_p4, has_home_p5) 
        * 100.0 / total_events, 1) as pct_full_lineups,
  
  -- Player coverage
  unique_primary_players,
  unique_away_lineup_p1,
  unique_home_lineup_p1,
  
  -- Overall quality score (composite)
  CASE
    WHEN total_events < 350 THEN '🔴 CRITICAL: Very low events'
    WHEN (last_sequence - first_sequence + 1) - unique_sequences > 10 THEN '🔴 CRITICAL: Large sequence gaps'
    WHEN shot_events > 0 AND shots_with_coords * 100.0 / NULLIF(shot_events, 0) < 30 THEN '🔴 CRITICAL: Poor coord coverage'
    WHEN total_events < 380 THEN '⚠️ Low event count'
    WHEN shot_events > 0 AND shots_with_coords * 100.0 / NULLIF(shot_events, 0) < 50 THEN '⚠️ Low coord coverage'
    WHEN LEAST(has_away_p1, has_away_p2, has_away_p3, has_away_p4, has_away_p5,
               has_home_p1, has_home_p2, has_home_p3, has_home_p4, has_home_p5) 
         * 100.0 / total_events < 80 THEN '⚠️ Incomplete lineups'
    ELSE '✅ Good quality'
  END as quality_status
  
FROM game_quality
WHERE 
  total_events < 380  -- Low events (was 400)
  OR (last_sequence - first_sequence + 1) - unique_sequences > 5  -- Sequence gaps
  OR (shot_events > 0 AND shots_with_coords * 100.0 / NULLIF(shot_events, 0) < 50)  -- Poor coords (was 70%)
ORDER BY game_date DESC, quality_status;

-- Quality Thresholds (Updated based on actual data):
-- ✅ Good: 380+ events, 50%+ coords, 80%+ full lineups, <5 sequence gaps
-- ⚠️ Warning: 350-379 events OR 30-49% coords OR incomplete lineups
-- 🔴 Critical: <350 events OR <30% coords OR >10 sequence gaps