-- File: validation/queries/raw/espn_rosters/team_coverage_check.sql
-- ============================================================================
-- Purpose: Verify all 30 NBA teams have roster data
-- Usage: Run daily or after backfills to ensure complete team coverage
-- ============================================================================
-- Instructions:
--   1. Update date range to check specific period
--   2. All 30 teams should appear with 15-23 players each
--   3. Missing teams or unusual player counts indicate data issues
-- ============================================================================
-- Expected Results:
--   - All 30 teams present with player counts between 15-23
--   - Most teams have ~18-21 players (standard NBA roster + two-way)
--   - <15 or >23 players = investigate (injuries, G-League assignments, etc.)
-- ============================================================================

WITH
-- Team roster counts
team_rosters AS (
  SELECT
    team_abbr,
    ANY_VALUE(team_display_name) as team_name,
    COUNT(DISTINCT player_lookup) as player_count,
    COUNT(*) as total_records,
    MAX(roster_date) as latest_update
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = (
      SELECT MAX(roster_date) 
      FROM `nba-props-platform.nba_raw.espn_team_rosters`
      WHERE roster_date >= '2025-01-01'
    )
    AND roster_date >= '2025-01-01'  -- Partition filter
  GROUP BY team_abbr
),

-- Calculate league stats
league_stats AS (
  SELECT
    COUNT(*) as teams_with_data,
    AVG(player_count) as avg_players,
    MIN(player_count) as min_players,
    MAX(player_count) as max_players,
    STDDEV(player_count) as stddev_players
  FROM team_rosters
)

-- Output: Team coverage summary
SELECT
  '=== LEAGUE SUMMARY ===' as section,
  '' as team_abbr,
  '' as team_name,
  '' as player_count,
  '' as status

UNION ALL

SELECT
  CONCAT('Teams Found: ', CAST(teams_with_data AS STRING), '/30') as section,
  '' as team_abbr,
  '' as team_name,
  CONCAT(
    'Avg: ', CAST(ROUND(avg_players, 1) AS STRING),
    ' | Range: ', CAST(min_players AS STRING),
    '-', CAST(max_players AS STRING)
  ) as player_count,
  CASE
    WHEN teams_with_data = 30 THEN '✅ Complete'
    ELSE '🔴 MISSING TEAMS'
  END as status
FROM league_stats

UNION ALL

SELECT
  '' as section,
  '' as team_abbr,
  '' as team_name,
  '' as player_count,
  '' as status

UNION ALL

SELECT
  '=== TEAM DETAILS ===' as section,
  '' as team_abbr,
  '' as team_name,
  '' as player_count,
  '' as status

UNION ALL

-- Team details
SELECT
  team_abbr as section,
  team_abbr,
  team_name,
  CAST(player_count AS STRING) as player_count,
  CASE
    WHEN player_count < 15 THEN '🔴 CRITICAL: Too few players'
    WHEN player_count > 23 THEN '🟡 WARNING: Unusually high count'
    WHEN player_count BETWEEN 15 AND 23 THEN '✅ Normal'
    ELSE '?'
  END as status
FROM team_rosters
ORDER BY
  CASE section
    WHEN '=== LEAGUE SUMMARY ===' THEN 0
    WHEN '' THEN 2
    WHEN '=== TEAM DETAILS ===' THEN 3
    ELSE 4
  END,
  team_abbr;