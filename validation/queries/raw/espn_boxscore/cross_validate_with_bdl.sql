-- ============================================================================
-- File: validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql
-- ESPN Boxscore: Cross-Validation with Ball Don't Lie
-- Purpose: Compare ESPN backup data against BDL primary source
-- Critical: ESPN serves as validation checkpoint - stats must match BDL
-- ============================================================================

-- CRITICAL: Must use date + team joins, NOT game_id
-- ESPN game_id format: 20250115_HOU_PHI
-- BDL game_id format:   20250115_HOU_PHI (SAME!)
-- This means we CAN join on game_id between ESPN and BDL

WITH espn_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= '2020-01-01'
),

bdl_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2020-01-01'
),

-- Game-level comparison
game_comparison AS (
  SELECT 
    COALESCE(e.game_date, b.game_date) as game_date,
    COALESCE(e.game_id, b.game_id) as game_id,
    CASE 
      WHEN e.game_id IS NOT NULL AND b.game_id IS NULL THEN 'ESPN Only'
      WHEN e.game_id IS NULL AND b.game_id IS NOT NULL THEN 'BDL Only'
      ELSE 'Both Sources'
    END as source_status,
    e.game_id as espn_game_id,
    b.game_id as bdl_game_id
  FROM espn_games e
  FULL OUTER JOIN bdl_games b 
    ON e.game_date = b.game_date 
    AND e.game_id = b.game_id
),

-- Player-level stat comparison (only for games in both sources)
player_stat_comparison AS (
  SELECT 
    e.game_date,
    e.game_id,
    e.player_lookup,
    e.player_full_name as espn_name,
    b.player_full_name as bdl_name,
    
    -- Compare key stats
    e.points as espn_points,
    b.points as bdl_points,
    ABS(e.points - b.points) as points_diff,
    
    e.rebounds as espn_rebounds,
    b.rebounds as bdl_rebounds,
    ABS(COALESCE(e.rebounds, 0) - COALESCE(b.rebounds, 0)) as rebounds_diff,
    
    e.assists as espn_assists,
    b.assists as bdl_assists,
    ABS(COALESCE(e.assists, 0) - COALESCE(b.assists, 0)) as assists_diff,
    
    -- Team check
    e.team_abbr as espn_team,
    b.team_abbr as bdl_team,
    e.team_abbr != b.team_abbr as team_mismatch
    
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
    AND e.player_lookup = b.player_lookup
  WHERE e.game_date >= '2020-01-01'
    AND b.game_date >= '2020-01-01'
),

-- Summary statistics
validation_summary AS (
  SELECT 
    COUNT(*) as total_player_comparisons,
    
    -- Points validation
    COUNT(CASE WHEN points_diff = 0 THEN 1 END) as points_exact_match,
    COUNT(CASE WHEN points_diff > 0 AND points_diff <= 2 THEN 1 END) as points_minor_diff,
    COUNT(CASE WHEN points_diff > 2 THEN 1 END) as points_major_diff,
    
    -- Rebounds validation  
    COUNT(CASE WHEN rebounds_diff = 0 THEN 1 END) as rebounds_exact_match,
    COUNT(CASE WHEN rebounds_diff > 2 THEN 1 END) as rebounds_major_diff,
    
    -- Assists validation
    COUNT(CASE WHEN assists_diff = 0 THEN 1 END) as assists_exact_match,
    COUNT(CASE WHEN assists_diff > 2 THEN 1 END) as assists_major_diff,
    
    -- Team validation
    COUNT(CASE WHEN team_mismatch THEN 1 END) as team_mismatches,
    
    -- Overall accuracy (use SAFE_DIVIDE to prevent division by zero)
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN points_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as points_accuracy_pct,
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN rebounds_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as rebounds_accuracy_pct,
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN assists_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as assists_accuracy_pct
    
  FROM player_stat_comparison
)

-- Output results in sections
(
  -- Game source comparison
  SELECT 
    'GAME SOURCE COMPARISON' as result_type,
    source_status as metric,
    CAST(COUNT(*) AS STRING) as value,
    CASE source_status
      WHEN 'Both Sources' THEN '✅ Ideal - Can cross-validate'
      WHEN 'BDL Only' THEN '⚪ Normal - BDL is primary source'
      WHEN 'ESPN Only' THEN '⚠️ Investigate - Why no BDL data?'
    END as interpretation
  FROM game_comparison
  WHERE source_status IS NOT NULL
  GROUP BY source_status
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY (POINTS)' as result_type,
    'Exact Matches' as metric,
    CASE 
      WHEN points_exact_match = 0 AND total_player_comparisons = 0 
      THEN 'N/A (no overlapping games)'
      ELSE CAST(points_exact_match AS STRING) || ' / ' || CAST(total_player_comparisons AS STRING) || 
           ' (' || CAST(COALESCE(points_accuracy_pct, 0) AS STRING) || '%)'
    END as value,
    CASE 
      WHEN total_player_comparisons = 0 THEN 'N/A - No overlapping games'
      WHEN points_accuracy_pct >= 95 THEN '✅ Excellent accuracy'
      WHEN points_accuracy_pct >= 90 THEN '⚪ Good accuracy'
      ELSE '🔴 Poor accuracy - investigate'
    END as interpretation
  FROM validation_summary
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY (REBOUNDS)' as result_type,
    'Exact Matches' as metric,
    CASE 
      WHEN rebounds_exact_match = 0 AND total_player_comparisons = 0 
      THEN 'N/A (no overlapping games)'
      ELSE CAST(rebounds_exact_match AS STRING) || ' / ' || CAST(total_player_comparisons AS STRING) || 
           ' (' || CAST(COALESCE(rebounds_accuracy_pct, 0) AS STRING) || '%)'
    END as value,
    CASE 
      WHEN total_player_comparisons = 0 THEN 'N/A - No overlapping games'
      WHEN rebounds_accuracy_pct >= 95 THEN '✅ Excellent accuracy'
      WHEN rebounds_accuracy_pct >= 90 THEN '⚪ Good accuracy'
      ELSE '🔴 Poor accuracy - investigate'
    END as interpretation
  FROM validation_summary
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY (ASSISTS)' as result_type,
    'Exact Matches' as metric,
    CASE 
      WHEN assists_exact_match = 0 AND total_player_comparisons = 0 
      THEN 'N/A (no overlapping games)'
      ELSE CAST(assists_exact_match AS STRING) || ' / ' || CAST(total_player_comparisons AS STRING) || 
           ' (' || CAST(COALESCE(assists_accuracy_pct, 0) AS STRING) || '%)'
    END as value,
    CASE 
      WHEN total_player_comparisons = 0 THEN 'N/A - No overlapping games'
      WHEN assists_accuracy_pct >= 95 THEN '✅ Excellent accuracy'
      WHEN assists_accuracy_pct >= 90 THEN '⚪ Good accuracy'
      ELSE '🔴 Poor accuracy - investigate'
    END as interpretation
  FROM validation_summary
  
  UNION ALL
  
  SELECT 
    'DATA QUALITY ISSUES' as result_type,
    'Team Mismatches' as metric,
    CAST(team_mismatches AS STRING) as value,
    CASE 
      WHEN team_mismatches = 0 THEN '✅ No issues'
      ELSE '🔴 CRITICAL - Team assignments differ'
    END as interpretation
  FROM validation_summary
  
  UNION ALL
  
  SELECT 
    'DATA QUALITY ISSUES' as result_type,
    'Major Points Differences (>2)' as metric,
    CAST(points_major_diff AS STRING) as value,
    CASE 
      WHEN points_major_diff = 0 THEN '✅ No major differences'
      WHEN points_major_diff <= 2 THEN '⚪ Minor discrepancies'
      ELSE '⚠️ Investigate large differences'
    END as interpretation
  FROM validation_summary
)

ORDER BY 
  CASE result_type
    WHEN 'GAME SOURCE COMPARISON' THEN 1
    WHEN 'STAT ACCURACY (POINTS)' THEN 2
    WHEN 'STAT ACCURACY (REBOUNDS)' THEN 3
    WHEN 'STAT ACCURACY (ASSISTS)' THEN 4
    WHEN 'DATA QUALITY ISSUES' THEN 5
  END,
  metric;

-- ============================================================================
-- DETAILED DISCREPANCIES (if any found, uncomment to investigate)
-- ============================================================================
/*
SELECT 
  game_date,
  game_id,
  player_lookup,
  espn_name,
  bdl_name,
  espn_points,
  bdl_points,
  points_diff,
  espn_rebounds,
  bdl_rebounds,
  rebounds_diff,
  espn_team,
  bdl_team,
  CASE 
    WHEN team_mismatch THEN '🔴 TEAM MISMATCH'
    WHEN points_diff > 5 THEN '🔴 MAJOR POINTS DIFF'
    WHEN rebounds_diff > 3 THEN '⚠️ REBOUNDS DIFF'
    ELSE '⚪ Minor differences'
  END as issue_severity
FROM player_stat_comparison
WHERE points_diff > 0 
   OR rebounds_diff > 0 
   OR assists_diff > 0 
   OR team_mismatch
ORDER BY 
  points_diff DESC,
  game_date DESC;
*/

-- ============================================================================
-- EXPECTED RESULTS (as of Oct 2025):
-- 
-- Game Source Comparison:
--   - BDL Only: 227 games (primary source has comprehensive coverage)
--   - ESPN Only: 1 game (backup collected this game)
--   - Both Sources: 0 games (no overlap currently)
--
-- Stat Accuracy: N/A (no overlapping games to compare)
--
-- INTERPRETATION:
-- ✅ Normal pattern: BDL has comprehensive coverage, ESPN is sparse backup
-- ⚠️ If ESPN Only games appear: Investigate why BDL missed these games
-- 
-- When overlapping games exist, expect >95% stat accuracy
-- ============================================================================
