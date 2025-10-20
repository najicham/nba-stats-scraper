-- File: validation/queries/raw/espn_rosters/missing_aliases_check.sql
-- ============================================================================
-- Purpose: Find ESPN players that need aliases to match NBA.com canonical names
-- Usage: Identifies suffix differences (Jr/II/III) that need alias mappings
-- ============================================================================
-- Expected Results:
--   - Shows ESPN lookup → NBA.com canonical lookup mappings needed
--   - Typical pattern: "andrejackson" → "andrejacksonjr"
--   - Use output to create aliases via generate_alias_inserts.sql
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
    player_lookup as espn_lookup,
    player_full_name as espn_name,
    team_abbr
  FROM `nba-props-platform.nba_raw.espn_team_rosters` e
  CROSS JOIN latest_espn l
  WHERE e.roster_date = l.latest_date
    AND e.roster_date >= '2025-01-01'
),

nbac_players AS (
  SELECT DISTINCT
    player_lookup as nbac_lookup,
    player_full_name as nbac_name,
    team_abbr
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE is_active = TRUE
),

-- Normalize by removing suffixes to find potential matches
potential_matches AS (
  SELECT
    e.espn_lookup,
    e.espn_name,
    n.nbac_lookup,
    n.nbac_name,
    e.team_abbr,
    -- Check if base names match (removing jr/ii/iii/iv/sr)
    REGEXP_REPLACE(LOWER(e.espn_lookup), r'(jr|ii|iii|iv|sr)$', '') as espn_base,
    REGEXP_REPLACE(LOWER(n.nbac_lookup), r'(jr|ii|iii|iv|sr)$', '') as nbac_base
  FROM espn_players e
  CROSS JOIN nbac_players n
  WHERE REGEXP_REPLACE(LOWER(e.espn_lookup), r'(jr|ii|iii|iv|sr)$', '') = 
        REGEXP_REPLACE(LOWER(n.nbac_lookup), r'(jr|ii|iii|iv|sr)$', '')
    AND e.team_abbr = n.team_abbr
    AND e.espn_lookup != n.nbac_lookup  -- Different lookups (needs alias)
),

-- Check which don't have aliases yet
missing_aliases AS (
  SELECT
    pm.espn_lookup,
    pm.nbac_lookup,
    pm.espn_name,
    pm.nbac_name,
    pm.team_abbr,
    a.alias_lookup as existing_alias
  FROM potential_matches pm
  LEFT JOIN `nba-props-platform.player_aliases` a
    ON pm.espn_lookup = a.alias_lookup
    AND pm.nbac_lookup = a.nba_canonical_lookup
    AND a.is_active = TRUE
)

-- Output: Summary + details
SELECT
  '=== MISSING ALIASES SUMMARY ===' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  '' as player_name,
  '' as team,
  '' as status

UNION ALL

SELECT
  'Total Potential Aliases Needed' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  CAST(COUNT(*) AS STRING) as player_name,
  '' as team,
  'Suffix differences detected' as status
FROM missing_aliases

UNION ALL

SELECT
  'Already Have Aliases' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  CAST(COUNT(*) AS STRING) as player_name,
  '' as team,
  '✅ Already mapped' as status
FROM missing_aliases
WHERE existing_alias IS NOT NULL

UNION ALL

SELECT
  'NEED NEW ALIASES' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  CAST(COUNT(*) AS STRING) as player_name,
  '' as team,
  '❌ Need to create' as status
FROM missing_aliases
WHERE existing_alias IS NULL

UNION ALL

SELECT
  '' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  '' as player_name,
  '' as team,
  '' as status

UNION ALL

SELECT
  '=== ALIASES TO CREATE ===' as section,
  '' as espn_lookup,
  '' as nbac_canonical,
  '' as player_name,
  '' as team,
  '' as status

UNION ALL

-- Show missing aliases
SELECT
  espn_lookup as section,
  espn_lookup,
  nbac_lookup as nbac_canonical,
  espn_name as player_name,
  team_abbr as team,
  CONCAT('Map: ', espn_lookup, ' → ', nbac_lookup) as status
FROM missing_aliases
WHERE existing_alias IS NULL
ORDER BY
  CASE section
    WHEN '=== MISSING ALIASES SUMMARY ===' THEN 0
    WHEN '' THEN 2
    WHEN '=== ALIASES TO CREATE ===' THEN 3
    ELSE 4
  END,
  team,
  espn_lookup
LIMIT 100;
