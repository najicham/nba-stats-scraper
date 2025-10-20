-- File: validation/queries/raw/espn_rosters/registry_coverage_check.sql
-- ============================================================================
-- Purpose: Check how many ESPN roster players are in the player registry
-- Usage: Run to determine registry coverage and identify missing players
-- ============================================================================
-- Expected Results:
--   - Coverage should be >95% for established players
--   - Missing players are typically rookies or recent signees
--   - Use this to identify players that need registry entries or aliases
-- ============================================================================

WITH
-- Get latest ESPN roster
latest_espn AS (
  SELECT MAX(roster_date) as latest_date
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date >= '2025-01-01'
),

espn_players AS (
  SELECT DISTINCT
    e.player_lookup,
    e.player_full_name,
    e.team_abbr
  FROM `nba-props-platform.nba_raw.espn_team_rosters` e
  CROSS JOIN latest_espn l
  WHERE e.roster_date = l.latest_date
    AND e.roster_date >= '2025-01-01'
),

-- Join with registry
registry_match AS (
  SELECT
    e.player_lookup,
    e.player_full_name,
    e.team_abbr,
    r.universal_player_id,
    r.player_name as registry_name,
    CASE
      WHEN r.universal_player_id IS NOT NULL THEN 'in_registry'
      ELSE 'missing'
    END as status
  FROM espn_players e
  LEFT JOIN `nba-props-platform.nba_players_registry` r
    ON e.player_lookup = r.player_lookup
    AND r.season = '2024-25'
)

-- Summary
SELECT
  '=== REGISTRY COVERAGE SUMMARY ===' as section,
  '' as status,
  '' as count,
  '' as percentage,
  '' as details

UNION ALL

SELECT
  'Total ESPN Players' as section,
  '' as status,
  CAST(COUNT(*) AS STRING) as count,
  '' as percentage,
  '' as details
FROM registry_match

UNION ALL

SELECT
  'In Registry' as section,
  'in_registry' as status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM registry_match), 1) AS STRING),
    '%'
  ) as percentage,
  '✅ Has universal_player_id' as details
FROM registry_match
WHERE status = 'in_registry'

UNION ALL

SELECT
  'Missing from Registry' as section,
  'missing' as status,
  CAST(COUNT(*) AS STRING) as count,
  CONCAT(
    CAST(ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM registry_match), 1) AS STRING),
    '%'
  ) as percentage,
  '❌ Needs registry entry or alias' as details
FROM registry_match
WHERE status = 'missing'

UNION ALL

SELECT
  '' as section,
  '' as status,
  '' as count,
  '' as percentage,
  '' as details

UNION ALL

SELECT
  '=== MISSING PLAYERS DETAIL ===' as section,
  '' as status,
  '' as count,
  '' as percentage,
  '' as details

UNION ALL

-- Show missing players
SELECT
  player_lookup as section,
  'missing' as status,
  player_full_name as count,
  team_abbr as percentage,
  'Add to registry or create alias' as details
FROM registry_match
WHERE status = 'missing'
ORDER BY
  CASE section
    WHEN '=== REGISTRY COVERAGE SUMMARY ===' THEN 0
    WHEN '' THEN 2
    WHEN '=== MISSING PLAYERS DETAIL ===' THEN 3
    ELSE 4
  END,
  section
LIMIT 100;
