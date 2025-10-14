-- ============================================================================
-- File: validation/queries/raw/espn_boxscore/player_stats_comparison.sql
-- ESPN Boxscore: Detailed Player Stats Comparison with BDL
-- Purpose: Compare individual player statistics between ESPN and BDL
-- Use: Investigate specific stat discrepancies when both sources exist
-- ============================================================================

WITH player_comparison AS (
  SELECT 
    e.game_date,
    e.game_id,
    e.home_team_abbr || ' vs ' || e.away_team_abbr as matchup,
    
    -- Player identification
    e.player_lookup,
    e.player_full_name as espn_name,
    b.player_full_name as bdl_name,
    e.team_abbr as espn_team,
    b.team_abbr as bdl_team,
    
    -- Core stats comparison
    e.points as espn_points,
    b.points as bdl_points,
    ABS(e.points - b.points) as points_diff,
    
    e.rebounds as espn_rebounds,
    b.rebounds as bdl_rebounds,
    ABS(COALESCE(e.rebounds, 0) - COALESCE(b.rebounds, 0)) as rebounds_diff,
    
    e.assists as espn_assists,
    b.assists as bdl_assists,
    ABS(COALESCE(e.assists, 0) - COALESCE(b.assists, 0)) as assists_diff,
    
    -- Detailed shooting stats
    e.field_goals_made as espn_fgm,
    b.field_goals_made as bdl_fgm,
    ABS(COALESCE(e.field_goals_made, 0) - COALESCE(b.field_goals_made, 0)) as fgm_diff,
    
    e.three_pointers_made as espn_3pm,
    b.three_pointers_made as bdl_3pm,
    ABS(COALESCE(e.three_pointers_made, 0) - COALESCE(b.three_pointers_made, 0)) as threepm_diff,
    
    e.free_throws_made as espn_ftm,
    b.free_throws_made as bdl_ftm,
    ABS(COALESCE(e.free_throws_made, 0) - COALESCE(b.free_throws_made, 0)) as ftm_diff,
    
    -- Additional stats
    e.steals as espn_steals,
    b.steals as bdl_steals,
    e.blocks as espn_blocks,
    b.blocks as bdl_blocks,
    e.turnovers as espn_turnovers,
    b.turnovers as bdl_turnovers,
    
    -- Playing time
    e.minutes as espn_minutes,
    b.minutes as bdl_minutes,
    
    -- Overall match quality
    CASE 
      WHEN e.points != b.points THEN 'Points Mismatch'
      WHEN COALESCE(e.rebounds, 0) != COALESCE(b.rebounds, 0) THEN 'Rebounds Mismatch'
      WHEN COALESCE(e.assists, 0) != COALESCE(b.assists, 0) THEN 'Assists Mismatch'
      ELSE 'Perfect Match'
    END as match_status,
    
    -- Issue severity
    CASE 
      WHEN e.team_abbr != b.team_abbr THEN '🔴 CRITICAL: Team Mismatch'
      WHEN ABS(e.points - b.points) > 5 THEN '🔴 CRITICAL: Major Points Diff'
      WHEN ABS(e.points - b.points) > 2 THEN '⚠️ WARNING: Moderate Points Diff'
      WHEN ABS(COALESCE(e.rebounds, 0) - COALESCE(b.rebounds, 0)) > 3 THEN '⚠️ WARNING: Rebounds Diff'
      WHEN ABS(COALESCE(e.assists, 0) - COALESCE(b.assists, 0)) > 3 THEN '⚠️ WARNING: Assists Diff'
      WHEN e.points = b.points 
           AND COALESCE(e.rebounds, 0) = COALESCE(b.rebounds, 0)
           AND COALESCE(e.assists, 0) = COALESCE(b.assists, 0) THEN '✅ Perfect Match'
      ELSE '⚪ Minor Differences'
    END as severity
    
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id  
    AND e.player_lookup = b.player_lookup
  WHERE e.game_date >= '2020-01-01'  -- Include all ESPN data
    AND b.game_date >= '2020-01-01'  -- Include all BDL data
),

match_quality_summary AS (
  SELECT 
    COUNT(*) as total_comparisons,
    COUNT(CASE WHEN match_status = 'Perfect Match' THEN 1 END) as perfect_matches,
    COUNT(CASE WHEN points_diff > 0 THEN 1 END) as points_mismatches,
    COUNT(CASE WHEN rebounds_diff > 0 THEN 1 END) as rebounds_mismatches,
    COUNT(CASE WHEN assists_diff > 0 THEN 1 END) as assists_mismatches,
    COUNT(CASE WHEN severity LIKE '🔴%' THEN 1 END) as critical_issues,
    COUNT(CASE WHEN severity LIKE '⚠️%' THEN 1 END) as warnings,
    
    -- Accuracy percentages (use SAFE_DIVIDE to prevent division by zero)
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN match_status = 'Perfect Match' THEN 1 END), NULLIF(COUNT(*), 0)), 1) as perfect_match_pct,
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN points_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as points_accuracy_pct,
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN rebounds_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as rebounds_accuracy_pct,
    ROUND(SAFE_DIVIDE(100.0 * COUNT(CASE WHEN assists_diff = 0 THEN 1 END), NULLIF(COUNT(*), 0)), 1) as assists_accuracy_pct
  FROM player_comparison
)

-- Summary Report
(
  SELECT 
    'COMPARISON SUMMARY' as section,
    'Total Player Comparisons' as metric,
    CAST(total_comparisons AS STRING) as value,
    'Players in both ESPN and BDL' as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'COMPARISON SUMMARY' as section,
    'Perfect Matches (All Stats)' as metric,
    CAST(perfect_matches AS STRING) || ' (' || CAST(COALESCE(perfect_match_pct, 0) AS STRING) || '%)' as value,
    CASE 
      WHEN perfect_match_pct IS NULL THEN 'N/A - No overlapping games'
      WHEN perfect_match_pct >= 90 THEN '✅ Excellent'
      WHEN perfect_match_pct >= 75 THEN '⚪ Good'
      ELSE '⚠️ Needs investigation'
    END as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY' as section,
    'Points Match Rate' as metric,
    CAST(COALESCE(points_accuracy_pct, 0) AS STRING) || '%' as value,
    CASE 
      WHEN points_accuracy_pct IS NULL THEN 'N/A - No overlapping games'
      WHEN points_accuracy_pct >= 95 THEN '✅ Excellent'
      WHEN points_accuracy_pct >= 90 THEN '⚪ Good'
      ELSE '⚠️ Investigate'
    END as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY' as section,
    'Rebounds Match Rate' as metric,
    CAST(COALESCE(rebounds_accuracy_pct, 0) AS STRING) || '%' as value,
    CASE 
      WHEN rebounds_accuracy_pct IS NULL THEN 'N/A - No overlapping games'
      WHEN rebounds_accuracy_pct >= 95 THEN '✅ Excellent'
      WHEN rebounds_accuracy_pct >= 90 THEN '⚪ Good'
      ELSE '⚠️ Investigate'
    END as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT ACCURACY' as section,
    'Assists Match Rate' as metric,
    CAST(COALESCE(assists_accuracy_pct, 0) AS STRING) || '%' as value,
    CASE 
      WHEN assists_accuracy_pct IS NULL THEN 'N/A - No overlapping games'
      WHEN assists_accuracy_pct >= 95 THEN '✅ Excellent'
      WHEN assists_accuracy_pct >= 90 THEN '⚪ Good'
      ELSE '⚠️ Investigate'
    END as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'ISSUES FOUND' as section,
    'Critical Issues' as metric,
    CAST(critical_issues AS STRING) as value,
    CASE 
      WHEN critical_issues = 0 THEN '✅ None'
      ELSE '🔴 Investigate immediately'
    END as notes
  FROM match_quality_summary
  
  UNION ALL
  
  SELECT 
    'ISSUES FOUND' as section,
    'Warnings' as metric,
    CAST(warnings AS STRING) as value,
    CASE 
      WHEN warnings = 0 THEN '✅ None'
      ELSE '⚠️ Review these players'
    END as notes
  FROM match_quality_summary
)

ORDER BY 
  CASE section
    WHEN 'COMPARISON SUMMARY' THEN 1
    WHEN 'STAT ACCURACY' THEN 2
    WHEN 'ISSUES FOUND' THEN 3
  END,
  metric;

-- ============================================================================
-- DETAILED DISCREPANCIES (uncomment to investigate specific players)
-- ============================================================================
/*
SELECT 
  game_date,
  matchup,
  player_lookup,
  espn_name,
  bdl_name,
  espn_team,
  bdl_team,
  
  -- Core stats side-by-side
  espn_points,
  bdl_points,
  points_diff,
  
  espn_rebounds,
  bdl_rebounds,
  rebounds_diff,
  
  espn_assists,
  bdl_assists,
  assists_diff,
  
  -- Shooting breakdown
  espn_fgm,
  bdl_fgm,
  espn_3pm,
  bdl_3pm,
  espn_ftm,
  bdl_ftm,
  
  severity,
  match_status

FROM player_comparison
WHERE severity NOT LIKE '✅%'  -- Only show problems
ORDER BY 
  CASE 
    WHEN severity LIKE '🔴%' THEN 1
    WHEN severity LIKE '⚠️%' THEN 2
    ELSE 3
  END,
  game_date DESC,
  points_diff DESC;
*/

-- ============================================================================
-- EXPECTED RESULTS (as of Oct 2025):
-- 
-- With Current Data (1 ESPN game, 0 overlap with BDL):
-- - Total Comparisons: 0 (no overlapping games)
-- - Status: N/A (cannot compare without overlap)
--
-- When Overlapping Games Exist (Expected Future State):
-- - Perfect Match Rate: >90% (ESPN should closely match BDL)
-- - Points Accuracy: >95% (core stat, must be accurate)
-- - Rebounds/Assists: >90% (minor scoring differences acceptable)
-- - Critical Issues: 0 (team mismatches, major point diffs)
--
-- INTERPRETATION GUIDE:
-- ✅ Perfect Match = All stats identical (ideal state)
-- ⚪ Minor Differences = 1-2 point variance (acceptable)
-- ⚠️ Warnings = 3-5 point variance (review)
-- 🔴 Critical = >5 point variance or team mismatch (investigate immediately)
-- ============================================================================
