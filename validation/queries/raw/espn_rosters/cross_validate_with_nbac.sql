-- File: validation/queries/raw/espn_rosters/cross_validate_with_nbac.sql
-- ============================================================================
-- Purpose: Compare ESPN rosters with NBA.com Player List (primary source)
-- Usage: Run to identify discrepancies between backup and primary sources
-- ============================================================================
-- Instructions:
--   1. Compares most recent ESPN roster with NBA.com current player list
--   2. Identifies players in one source but not the other
--   3. Team mismatches indicate trades or data timing issues
-- ============================================================================
-- Expected Results:
--   - High match rate (>90%) indicates healthy cross-validation
--   - Mismatches often due to timing (ESPN updates vs NBA.com updates)
--   - Recent trades may appear in one source before the other
-- ============================================================================

WITH
-- Get latest ESPN roster date
latest_espn AS (
  SELECT MAX(roster_date) as latest_date
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date >= '2025-01-01'  -- Partition filter
),

-- ESPN players
espn_players AS (
  SELECT DISTINCT
    e.player_lookup,
    e.player_full_name as espn_name,
    e.team_abbr as espn_team,
    e.roster_date
  FROM `nba-props-platform.nba_raw.espn_team_rosters` e
  CROSS JOIN latest_espn l
  WHERE e.roster_date = l.latest_date
    AND e.roster_date >= '2025-01-01'  -- Partition filter
),

-- NBA.com players (primary source)
nbac_players AS (
  SELECT DISTINCT
    player_lookup,
    player_full_name as nbac_name,
    team_abbr as nbac_team
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE is_active = TRUE
),

-- Compare sources
comparison AS (
  SELECT
    COALESCE(e.player_lookup, n.player_lookup) as player_lookup,
    e.espn_name,
    n.nbac_name,
    e.espn_team,
    n.nbac_team,
    CASE
      WHEN e.player_lookup IS NULL THEN 'nba_only'
      WHEN n.player_lookup IS NULL THEN 'espn_only'
      WHEN e.espn_team != n.nbac_team THEN 'team_mismatch'
      ELSE 'match'
    END as match_status
  FROM espn_players e
  FULL OUTER JOIN nbac_players n
    ON e.player_lookup = n.player_lookup
)

-- Output: Summary + details
SELECT
  '=== SUMMARY ===' as section,
  '' as match_status,
  '' as count,
  '' as percentage,
  '' as notes

UNION ALL

SELECT
  'Total ESPN Players' as section,
  '' as match_status,
  CAST(COUNT(DISTINCT CASE WHEN match_status IN ('match', 'espn_only', 'team_mismatch') THEN player_lookup END) AS STRING) as count,
  '' as percentage,
  '' as notes
FROM comparison

UNION ALL

SELECT
  'Total NBA.com Players' as section,
  '' as match_status,
  CAST(COUNT(DISTINCT CASE WHEN match_status IN ('match', 'nba_only', 'team_mismatch') THEN player_lookup END) AS STRING) as count,
  '' as percentage,
  '' as notes
FROM comparison

UNION ALL

SELECT
  'Perfect Matches' as section,
  'match' as match_status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / 
      (SELECT COUNT(*) FROM comparison WHERE match_status IN ('match', 'espn_only', 'nba_only', 'team_mismatch')), 1) 
    AS STRING), '%'
  ) as percentage,
  '✅' as notes
FROM comparison
WHERE match_status = 'match'

UNION ALL

SELECT
  'Team Mismatches' as section,
  'team_mismatch' as match_status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / 
      (SELECT COUNT(*) FROM comparison WHERE match_status IN ('match', 'espn_only', 'nba_only', 'team_mismatch')), 1) 
    AS STRING), '%'
  ) as percentage,
  '⚠️  Check trades' as notes
FROM comparison
WHERE match_status = 'team_mismatch'

UNION ALL

SELECT
  'Only in ESPN' as section,
  'espn_only' as match_status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / 
      (SELECT COUNT(*) FROM comparison WHERE match_status IN ('match', 'espn_only', 'nba_only', 'team_mismatch')), 1) 
    AS STRING), '%'
  ) as percentage,
  '🔍 Review' as notes
FROM comparison
WHERE match_status = 'espn_only'

UNION ALL

SELECT
  'Only in NBA.com' as section,
  'nba_only' as match_status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / 
      (SELECT COUNT(*) FROM comparison WHERE match_status IN ('match', 'espn_only', 'nba_only', 'team_mismatch')), 1) 
    AS STRING), '%'
  ) as percentage,
  '📊 Normal variance' as notes
FROM comparison
WHERE match_status = 'nba_only'

UNION ALL

SELECT
  '' as section,
  '' as match_status,
  '' as count,
  '' as percentage,
  '' as notes

UNION ALL

SELECT
  '=== DISCREPANCIES ===' as section,
  '' as match_status,
  '' as count,
  '' as percentage,
  '' as notes

UNION ALL

-- Show actual mismatches
SELECT
  player_lookup as section,
  match_status,
  COALESCE(espn_name, nbac_name) as count,
  CONCAT('ESPN: ', COALESCE(espn_team, 'N/A'), ' | NBA.com: ', COALESCE(nbac_team, 'N/A')) as percentage,
  '' as notes
FROM comparison
WHERE match_status != 'match'
ORDER BY
  CASE section
    WHEN '=== SUMMARY ===' THEN 0
    WHEN '' THEN 2
    WHEN '=== DISCREPANCIES ===' THEN 3
    ELSE 4
  END,
  match_status,
  section
LIMIT 100;