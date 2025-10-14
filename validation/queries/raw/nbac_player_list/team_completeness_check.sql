-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/team_completeness_check.sql
-- Purpose: Verify all 30 teams present with reasonable player counts
-- Usage: Run regularly to detect missing teams or unusual roster sizes
-- ============================================================================
-- Instructions:
--   1. All 30 NBA teams should be present
--   2. Each team should have ~13-17 active players (normal range)
--   3. Alert if any team missing or has <10 or >20 active players
-- ============================================================================
-- Expected Results:
--   - 30 teams total
--   - Active player count: 13-17 per team (typical)
--   - Inactive players: 0-3 per team (normal)
--   - Large deviations indicate data quality issues
-- ============================================================================

WITH
-- Get player counts by team
team_player_counts AS (
  SELECT
    team_abbr,
    COUNT(*) as total_players,
    COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_players,
    COUNT(CASE WHEN is_active = FALSE THEN 1 END) as inactive_players,
    COUNT(DISTINCT position) as unique_positions,
    MAX(last_seen_date) as last_update,
    STRING_AGG(DISTINCT roster_status ORDER BY roster_status) as roster_statuses
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024  -- Partition filter
  GROUP BY team_abbr
),

-- Calculate league statistics
league_stats AS (
  SELECT
    COUNT(*) as teams_found,
    AVG(active_players) as avg_active_players,
    STDDEV(active_players) as stddev_active,
    MAX(active_players) as max_active,
    MIN(active_players) as min_active,
    SUM(active_players) as total_active_players
  FROM team_player_counts
),

-- Analyze each team
team_analysis AS (
  SELECT
    t.team_abbr,
    t.total_players,
    t.active_players,
    t.inactive_players,
    t.unique_positions,
    t.last_update,
    l.avg_active_players,
    t.active_players - l.avg_active_players as active_diff,
    CASE
      WHEN t.active_players < 10 THEN '🔴 CRITICAL: Very low roster (<10)'
      WHEN t.active_players < 13 THEN '🟡 WARNING: Low roster (10-12)'
      WHEN t.active_players > 20 THEN '🔴 CRITICAL: Very high roster (>20)'
      WHEN t.active_players > 17 THEN '🟡 WARNING: High roster (18-20)'
      ELSE '✅ Normal'
    END as status,
    RANK() OVER (ORDER BY t.active_players DESC) as rank_most_players,
    RANK() OVER (ORDER BY t.active_players ASC) as rank_fewest_players
  FROM team_player_counts t
  CROSS JOIN league_stats l
)

-- Output: League summary then team details
SELECT
  '=== LEAGUE SUMMARY ===' as section,
  '' as team,
  '' as total_players,
  '' as active,
  '' as inactive,
  '' as positions,
  '' as status

UNION ALL

SELECT
  'Teams Found' as section,
  CAST(teams_found AS STRING) as team,
  CONCAT('Expected: 30') as total_players,
  '' as active,
  '' as inactive,
  '' as positions,
  CASE
    WHEN teams_found < 30 THEN '🔴 CRITICAL: Missing teams'
    WHEN teams_found > 30 THEN '🟡 WARNING: Extra teams'
    ELSE '✅ Complete'
  END as status
FROM league_stats

UNION ALL

SELECT
  'Active Players (League)' as section,
  CAST(total_active_players AS STRING) as team,
  CONCAT('Avg per team: ', CAST(ROUND(avg_active_players, 1) AS STRING)) as total_players,
  CONCAT('Range: ', CAST(min_active AS STRING), '-', CAST(max_active AS STRING)) as active,
  '' as inactive,
  '' as positions,
  '' as status
FROM league_stats

UNION ALL

SELECT
  '' as section,
  '' as team,
  '' as total_players,
  '' as active,
  '' as inactive,
  '' as positions,
  '' as status

UNION ALL

SELECT
  '=== TEAM DETAILS ===' as section,
  '' as team,
  '' as total_players,
  '' as active,
  '' as inactive,
  '' as positions,
  '' as status

UNION ALL

SELECT
  team_abbr as section,
  team_abbr as team,
  CAST(total_players AS STRING) as total_players,
  CAST(active_players AS STRING) as active,
  CAST(inactive_players AS STRING) as inactive,
  CAST(unique_positions AS STRING) as positions,
  status
FROM team_analysis
ORDER BY
  CASE section
    WHEN '=== LEAGUE SUMMARY ===' THEN 0
    WHEN 'Teams Found' THEN 1
    WHEN 'Active Players (League)' THEN 2
    WHEN '' THEN 3
    WHEN '=== TEAM DETAILS ===' THEN 4
    ELSE 5
  END,
  CAST(active AS INT64) DESC;  -- Sort teams by active player count