-- File: validation/queries/raw/espn_rosters/player_count_distribution.sql
-- ============================================================================
-- Purpose: Analyze roster size distribution across teams
-- Usage: Run to understand normal roster size patterns
-- ============================================================================
-- Expected Results:
--   - Most teams: 18-21 players (standard roster + two-way contracts)
--   - Minimum: 15 players (NBA minimum)
--   - Maximum: 23 players (including exhibit 10, training camp invites)
-- ============================================================================

WITH
latest_rosters AS (
  SELECT
    team_abbr,
    COUNT(DISTINCT player_lookup) as player_count
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = (
      SELECT MAX(roster_date) 
      FROM `nba-props-platform.nba_raw.espn_team_rosters`
      WHERE roster_date >= '2025-01-01'  -- Partition filter
    )
    AND roster_date >= '2025-01-01'  -- Partition filter
  GROUP BY team_abbr
)

SELECT
  player_count,
  COUNT(*) as teams_with_this_count,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM latest_rosters), 1) as percentage,
  STRING_AGG(team_abbr ORDER BY team_abbr) as teams
FROM latest_rosters
GROUP BY player_count
ORDER BY player_count DESC;