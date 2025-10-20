-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/compare_recent_stats_espn_bdl.sql
-- ============================================================================
-- Compare individual player stats between ESPN and BDL for recent games
-- Use this to verify stat accuracy when both sources have the same game
-- ============================================================================

-- First, show if there are any overlapping games
WITH overlap_check AS (
  SELECT
    COUNT(DISTINCT e.game_id) as overlapping_games,
    COUNT(*) as overlapping_players
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
    AND e.player_lookup = b.player_lookup
  WHERE e.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND b.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  '=== OVERLAP CHECK ===' as section,
  CASE 
    WHEN overlapping_games = 0 THEN '⚪ NO OVERLAPPING GAMES (Normal for sparse backup)'
    ELSE CONCAT('✅ ', CAST(overlapping_games AS STRING), ' games with both sources')
  END as status,
  CAST(overlapping_players AS STRING) as players_to_compare
FROM overlap_check;

-- If there are overlaps, show detailed comparison
-- (Otherwise this will return no rows)
WITH recent_comparisons AS (
  SELECT
    e.game_date,
    e.game_id,
    CONCAT(e.away_team_abbr, ' @ ', e.home_team_abbr) as matchup,
    e.player_lookup,
    e.player_full_name as espn_name,
    b.player_full_name as bdl_name,
    
    -- Core stats comparison
    e.points as espn_pts,
    b.points as bdl_pts,
    ABS(e.points - b.points) as pts_diff,
    
    e.rebounds as espn_reb,
    b.rebounds as bdl_reb,
    ABS(COALESCE(e.rebounds, 0) - COALESCE(b.rebounds, 0)) as reb_diff,
    
    e.assists as espn_ast,
    b.assists as bdl_ast,
    ABS(COALESCE(e.assists, 0) - COALESCE(b.assists, 0)) as ast_diff,
    
    -- Minutes for context
    e.minutes as espn_min,
    b.minutes as bdl_min,
    
    -- Assessment
    CASE
      WHEN ABS(e.points - b.points) > 5 THEN '🔴 CRITICAL: >5 point diff'
      WHEN ABS(e.points - b.points) BETWEEN 3 AND 5 THEN '⚠️ WARNING: 3-5 point diff'
      WHEN ABS(e.points - b.points) BETWEEN 1 AND 2 THEN '⚪ Minor: 1-2 point diff'
      WHEN e.points = b.points THEN '✅ Perfect match'
      ELSE 'Review'
    END as assessment
    
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
    AND e.player_lookup = b.player_lookup
  WHERE e.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND b.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  game_date,
  matchup,
  player_lookup,
  espn_name,
  bdl_name,
  espn_pts,
  bdl_pts,
  pts_diff,
  espn_reb,
  bdl_reb,
  reb_diff,
  espn_ast,
  bdl_ast,
  ast_diff,
  espn_min,
  bdl_min,
  assessment
FROM recent_comparisons
WHERE pts_diff > 0 OR reb_diff > 0 OR ast_diff > 0
ORDER BY 
  CASE
    WHEN assessment LIKE '🔴%' THEN 1
    WHEN assessment LIKE '⚠️%' THEN 2
    WHEN assessment LIKE '⚪%' THEN 3
    ELSE 4
  END,
  pts_diff DESC,
  game_date DESC
LIMIT 50;

-- ============================================================================
-- INTERPRETATION:
-- - If you see only "NO OVERLAPPING GAMES" = Normal (sparse backup)
-- - If you see player rows = Compare stats for accuracy
-- - Perfect match rate >90% = Excellent
-- - Critical diffs (>5 pts) = Investigate both sources
-- ============================================================================
