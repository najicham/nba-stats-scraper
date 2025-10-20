-- File: validation/queries/raw/espn_rosters/generate_alias_inserts.sql
-- ============================================================================
-- Purpose: Generate INSERT statements to create missing player aliases
-- Usage: Run this query, copy the INSERT statements, and execute them
-- ============================================================================
-- Instructions:
--   1. Run this query to generate INSERT statements
--   2. Review the output carefully
--   3. Copy the INSERT statements from the 'insert_statement' column
--   4. Execute them in BigQuery to create the aliases
--   5. Re-run cross_validate_with_nbac.sql to verify improvement
-- ============================================================================
-- Expected Results:
--   - Generates ~49 INSERT statements (based on your validation results)
--   - Each maps ESPN lookup to NBA.com canonical lookup
--   - After inserting, cross-validation should improve to >95%
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
    player_full_name as nbac_name
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE is_active = TRUE
),

-- Find matches by base name (suffix-agnostic)
matches AS (
  SELECT
    e.espn_lookup,
    n.nbac_lookup,
    e.espn_name,
    -- Detect what kind of suffix difference
    CASE
      WHEN e.espn_lookup LIKE '%jr' OR n.nbac_lookup LIKE '%jr' THEN 'Jr suffix'
      WHEN e.espn_lookup LIKE '%ii' OR n.nbac_lookup LIKE '%ii' THEN 'II suffix'
      WHEN e.espn_lookup LIKE '%iii' OR n.nbac_lookup LIKE '%iii' THEN 'III suffix'
      WHEN e.espn_lookup LIKE '%iv' OR n.nbac_lookup LIKE '%iv' THEN 'IV suffix'
      ELSE 'Other'
    END as suffix_type
  FROM espn_players e
  CROSS JOIN nbac_players n
  WHERE REGEXP_REPLACE(LOWER(e.espn_lookup), r'(jr|ii|iii|iv|sr)$', '') = 
        REGEXP_REPLACE(LOWER(n.nbac_lookup), r'(jr|ii|iii|iv|sr)$', '')
    AND e.espn_lookup != n.nbac_lookup  -- Different lookups
),

-- Exclude existing aliases
new_aliases AS (
  SELECT 
    m.*,
    ROW_NUMBER() OVER (PARTITION BY m.espn_lookup ORDER BY m.nbac_lookup) as rn
  FROM matches m
  LEFT JOIN `nba-props-platform.player_aliases` a
    ON m.espn_lookup = a.alias_lookup
    AND m.nbac_lookup = a.nba_canonical_lookup
  WHERE a.alias_lookup IS NULL
)

-- Generate INSERT statements
SELECT
  CONCAT(
    'INSERT INTO `nba-props-platform.player_aliases` ',
    '(alias_lookup, nba_canonical_lookup, alias_type, is_active, created_date) ',
    'VALUES (',
    '"', espn_lookup, '", ',
    '"', nbac_lookup, '", ',
    '"suffix_difference", ',
    'TRUE, ',
    'CURRENT_DATE()',
    ');'
  ) as insert_statement,
  espn_name as player_name,
  CONCAT(espn_lookup, ' → ', nbac_lookup) as mapping,
  suffix_type
FROM new_aliases
WHERE rn = 1  -- Avoid duplicates if multiple matches
ORDER BY suffix_type, espn_lookup;
