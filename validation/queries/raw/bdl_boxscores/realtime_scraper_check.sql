-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/realtime_scraper_check.sql
-- Purpose: Real-time check to verify scraper is running for today's games
-- Usage: Run during game days to monitor live data collection
-- ============================================================================
-- Instructions:
--   1. Run this query after games complete (typically 11 PM - 1 AM ET)
--   2. Check if completed games have box score data
--   3. Alert if completed games missing data
-- ============================================================================
-- Expected Results:
--   - Completed games should have box score data within 30-90 minutes
--   - In-progress games may not have data yet (normal)
--   - Scheduled games should not have data (normal)
-- ============================================================================

WITH todays_schedule AS (
  SELECT
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
    game_status,
    game_status_text,
    CASE
      WHEN game_status = 3 THEN 'completed'
      WHEN game_status = 2 THEN 'in_progress'
      WHEN game_status = 1 THEN 'scheduled'
      ELSE 'unknown'
    END as game_state
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

todays_boxscores AS (
  SELECT
    game_id,
    COUNT(DISTINCT player_lookup) as total_players,
    COUNT(DISTINCT team_abbr) as teams_with_data,
    MAX(processed_at) as last_processed_at
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = CURRENT_DATE()
  GROUP BY game_id
)

SELECT
  s.matchup,
  s.game_state,
  s.game_status_text,
  COALESCE(b.total_players, 0) as total_players,
  COALESCE(b.teams_with_data, 0) as teams_with_data,
  b.last_processed_at,
  CASE
    -- Completed games
    WHEN s.game_state = 'completed' AND b.total_players >= 20 THEN '✅ Data captured'
    WHEN s.game_state = 'completed' AND b.total_players > 0 AND b.total_players < 20 THEN '⚠️ Incomplete data'
    WHEN s.game_state = 'completed' AND b.total_players IS NULL THEN '❌ CRITICAL: Missing data'
    
    -- In-progress games
    WHEN s.game_state = 'in_progress' AND b.total_players > 0 THEN '🔵 Live data available'
    WHEN s.game_state = 'in_progress' THEN '⚪ In progress (no data yet - normal)'
    
    -- Scheduled games
    WHEN s.game_state = 'scheduled' AND b.total_players > 0 THEN '⚠️ Unexpected: Data before game'
    WHEN s.game_state = 'scheduled' THEN '⚪ Scheduled (no data - normal)'
    
    ELSE '⚠️ Unknown state'
  END as status,
  
  -- Recommendations
  CASE
    WHEN s.game_state = 'completed' AND b.total_players IS NULL 
    THEN 'Run scraper for this game immediately'
    WHEN s.game_state = 'completed' AND b.total_players < 20 
    THEN 'Check scraper logs - incomplete data'
    WHEN s.game_state = 'in_progress' AND b.total_players > 0 
    THEN 'Live data detected - scraper working'
    ELSE 'No action needed'
  END as recommendation

FROM todays_schedule s
LEFT JOIN todays_boxscores b ON s.game_id = b.game_id
ORDER BY 
  CASE 
    WHEN s.game_state = 'completed' THEN 1
    WHEN s.game_state = 'in_progress' THEN 2
    WHEN s.game_state = 'scheduled' THEN 3
  END,
  s.matchup;
