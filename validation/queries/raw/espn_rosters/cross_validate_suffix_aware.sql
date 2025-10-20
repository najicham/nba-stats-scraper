-- File: validation/queries/raw/espn_rosters/cross_validate_suffix_aware.sql
-- ============================================================================
-- Purpose: Compare ESPN rosters with NBA.com (accounting for suffix differences)
-- This query normalizes player_lookup to handle Jr/II/III suffix variations
-- ============================================================================
-- Expected Results:
--   - Should show >95% match rate (vs 83.9% without normalization)
--   - Remaining mismatches are genuine discrepancies
-- ============================================================================

WITH
-- Get latest ESPN roster date
latest_espn AS (
  SELECT MAX(roster_date) as latest_date
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date >= '2025-01-01'
),

-- ESPN players with normalized lookups (strip suffixes)
espn_players AS (
  SELECT DISTINCT
    e.player_lookup,
    -- Normalize by removing common suffixes
    REGEXP_REPLACE(
      LOWER(e.player_lookup),
      r'(jr|ii|iii|iv|sr)$',
      ''
    ) as normalized_lookup,
    e.player_full_name as espn_name,
    e.team_abbr as espn_team,
    e.roster_date
  FROM `nba-props-platform.nba_raw.espn_team_rosters` e
  CROSS JOIN latest_espn l
  WHERE e.roster_date = l.latest_date
    AND e.roster_date >= '2025-01-01'
),

-- NBA.com players with normalized lookups
nbac_players AS (
  SELECT DISTINCT
    player_lookup,
    -- Normalize by removing common suffixes
    REGEXP_REPLACE(
      LOWER(player_lookup),
      r'(jr|ii|iii|iv|sr)$',
      ''
    ) as normalized_lookup,
    player_full_name as nbac_name,
    team_abbr as nbac_team
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE is_active = TRUE
),

-- Compare using NORMALIZED lookups
comparison AS (
  SELECT
    COALESCE(e.normalized_lookup, n.normalized_lookup) as normalized_lookup,
    e.player_lookup as espn_raw_lookup,
    n.player_lookup as nbac_raw_lookup,
    e.espn_name,
    n.nbac_name,
    e.espn_team,
    n.nbac_team,
    CASE
      WHEN e.normalized_lookup IS NULL THEN 'nba_only'
      WHEN n.normalized_lookup IS NULL THEN 'espn_only'
      WHEN e.espn_team != n.nbac_team THEN 'team_mismatch'
      ELSE 'match'
    END as match_status
  FROM espn_players e
  FULL OUTER JOIN nbac_players n
    ON e.normalized_lookup = n.normalized_lookup
)

-- Output: Summary + details
SELECT
  '=== SUMMARY (SUFFIX-AWARE MATCHING) ===' as section,
  '' as match_status,
  '' as count,
  '' as percentage,
  '' as notes

UNION ALL

SELECT
  'Total ESPN Players' as section,
  '' as match_status,
  CAST(COUNT(DISTINCT CASE WHEN match_status IN ('match', 'espn_only', 'team_mismatch') THEN normalized_lookup END) AS STRING) as count,
  '' as percentage,
  '' as notes
FROM comparison

UNION ALL

SELECT
  'Total NBA.com Players' as section,
  '' as match_status,
  CAST(COUNT(DISTINCT CASE WHEN match_status IN ('match', 'nba_only', 'team_mismatch') THEN normalized_lookup END) AS STRING) as count,
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
  '✅ Same player, same team' as notes
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
  '⚠️  Same player, different team (trades?)' as notes
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
  '🔍 Genuinely missing from NBA.com' as notes
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
  '📊 Genuinely missing from ESPN' as notes
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
  '=== GENUINE DISCREPANCIES ===' as section,
  '' as match_status,
  '' as count,
  '' as percentage,
  '' as notes

UNION ALL

-- Show actual mismatches (after normalization)
SELECT
  normalized_lookup as section,
  match_status,
  COALESCE(espn_name, nbac_name) as count,
  CONCAT(
    'ESPN: ', COALESCE(espn_team, 'N/A'), 
    ' (', COALESCE(espn_raw_lookup, 'N/A'), ')',
    ' | NBA.com: ', COALESCE(nbac_team, 'N/A'),
    ' (', COALESCE(nbac_raw_lookup, 'N/A'), ')'
  ) as percentage,
  '' as notes
FROM comparison
WHERE match_status != 'match'
ORDER BY
  CASE section
    WHEN '=== SUMMARY (SUFFIX-AWARE MATCHING) ===' THEN 0
    WHEN '' THEN 2
    WHEN '=== GENUINE DISCREPANCIES ===' THEN 3
    ELSE 4
  END,
  match_status,
  section
LIMIT 100;
