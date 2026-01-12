-- File: bin/patches/patch_player_lookup_normalization.sql
-- Purpose: Fix player_lookup normalization to KEEP suffixes (Jr., Sr., II, III)
-- Issue: ESPN rosters and BettingPros removed suffixes, causing JOIN failures with Odds API props
-- See: docs/08-projects/.../data-quality/2026-01-12-PLAYER-LOOKUP-NORMALIZATION-MISMATCH.md
--
-- IMPORTANT: Run these in order. Each UPDATE should complete before running the next.
-- Estimated time: ~5-10 minutes per table depending on size
--
-- CRITICAL: The SQL must match Python's normalize_name() function:
--   1. LOWER first
--   2. NORMALIZE(NFD) to decompose accented characters
--   3. REGEXP_REPLACE to remove non-alphanumeric (including combining marks)
--
-- Python equivalent:
--   normalized = name.lower()
--   normalized = ''.join(c for c in unicodedata.normalize('NFD', normalized) if unicodedata.category(c) != 'Mn')
--   normalized = re.sub(r"['\.\-\s]+", '', normalized)
--   normalized = re.sub(r'[^a-z0-9]', '', normalized)

-- ============================================================================
-- STEP 0: VERIFY THE PROBLEM (Run these first to understand scope)
-- ============================================================================

-- Check suffix players in ESPN rosters (should show suffix removed - BUG)
SELECT player_full_name, player_lookup
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE player_full_name LIKE '%Jr.%'
   OR player_full_name LIKE '%Sr.%'
   OR player_full_name LIKE '%II%'
   OR player_full_name LIKE '%III%'
LIMIT 20;

-- Check suffix players in Odds API props (should show suffix KEPT - CORRECT)
SELECT player_name, player_lookup
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE player_name LIKE '%Jr.%'
   OR player_name LIKE '%Sr.%'
   OR player_name LIKE '%II%'
   OR player_name LIKE '%III%'
LIMIT 20;

-- Count affected rows in ESPN rosters
SELECT COUNT(*) as affected_rows
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE player_full_name LIKE '%Jr.%'
   OR player_full_name LIKE '%Sr.%'
   OR player_full_name LIKE '%II%'
   OR player_full_name LIKE '%III%'
   OR player_full_name LIKE '%IV%'
   OR player_full_name LIKE '%V%';

-- ============================================================================
-- STEP 1: BACKFILL ESPN ROSTERS
-- ============================================================================

-- Preview what will change (DRY RUN)
-- CRITICAL: Order is LOWER -> NORMALIZE -> REGEXP_REPLACE
SELECT
    player_full_name,
    player_lookup as old_lookup,
    REGEXP_REPLACE(
        LOWER(NORMALIZE(player_full_name, NFD)),
        r'[^a-z0-9]', ''
    ) as new_lookup
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE player_full_name LIKE '%Jr.%'
   OR player_full_name LIKE '%Sr.%'
   OR player_full_name LIKE '%II%'
LIMIT 20;

-- ACTUAL UPDATE: Recompute player_lookup with correct normalization
-- This matches the normalize_name() function from name_utils.py:
-- 1. LOWER(x) - convert to lowercase FIRST
-- 2. NORMALIZE(x, NFD) - decompose accented characters
-- 3. REGEXP_REPLACE - remove non-alphanumeric (spaces, punctuation, combining marks)
UPDATE `nba-props-platform.nba_raw.espn_team_rosters`
SET player_lookup = REGEXP_REPLACE(
    LOWER(NORMALIZE(player_full_name, NFD)),
    r'[^a-z0-9]', ''
)
WHERE player_lookup IS NOT NULL
  AND player_full_name IS NOT NULL;

-- Verify ESPN rosters fix - suffixes should now be KEPT
SELECT player_full_name, player_lookup
FROM `nba-props-platform.nba_raw.espn_team_rosters`
WHERE player_full_name LIKE '%Jr.%'
   OR player_full_name LIKE '%Sr.%'
   OR player_full_name LIKE '%II%'
LIMIT 20;

-- ============================================================================
-- STEP 2: BACKFILL BETTINGPROS PROPS
-- ============================================================================

-- Preview what will change (DRY RUN)
SELECT
    player_name,
    player_lookup as old_lookup,
    REGEXP_REPLACE(
        LOWER(NORMALIZE(player_name, NFD)),
        r'[^a-z0-9]', ''
    ) as new_lookup
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE player_name LIKE '%Jr.%'
   OR player_name LIKE '%Sr.%'
   OR player_name LIKE '%II%'
LIMIT 20;

-- ACTUAL UPDATE: Recompute player_lookup with correct normalization
UPDATE `nba-props-platform.nba_raw.bettingpros_player_points_props`
SET player_lookup = REGEXP_REPLACE(
    LOWER(NORMALIZE(player_name, NFD)),
    r'[^a-z0-9]', ''
)
WHERE player_lookup IS NOT NULL
  AND player_name IS NOT NULL;

-- Verify BettingPros fix - suffixes should now be KEPT
SELECT player_name, player_lookup
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE player_name LIKE '%Jr.%'
   OR player_name LIKE '%Sr.%'
   OR player_name LIKE '%II%'
LIMIT 20;

-- ============================================================================
-- STEP 3: VERIFY JOINS NOW WORK
-- ============================================================================

-- Check if suffix players now match between ESPN rosters and Odds API props
WITH espn_suffix_players AS (
    SELECT DISTINCT player_lookup, player_full_name
    FROM `nba-props-platform.nba_raw.espn_team_rosters`
    WHERE roster_date >= '2025-11-01'
      AND (player_full_name LIKE '%Jr.%' OR player_full_name LIKE '%II%')
),
odds_suffix_players AS (
    SELECT DISTINCT player_lookup, player_name
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2025-11-01'
      AND (player_name LIKE '%Jr.%' OR player_name LIKE '%II%')
)
SELECT
    e.player_full_name as espn_name,
    e.player_lookup as espn_lookup,
    o.player_name as odds_name,
    o.player_lookup as odds_lookup,
    CASE WHEN o.player_lookup IS NOT NULL THEN 'MATCH' ELSE 'NO MATCH' END as status
FROM espn_suffix_players e
LEFT JOIN odds_suffix_players o ON e.player_lookup = o.player_lookup
ORDER BY status DESC, e.player_full_name
LIMIT 50;

-- Count matches vs mismatches
WITH espn_suffix_players AS (
    SELECT DISTINCT player_lookup
    FROM `nba-props-platform.nba_raw.espn_team_rosters`
    WHERE roster_date >= '2025-11-01'
      AND (player_full_name LIKE '%Jr.%' OR player_full_name LIKE '%II%'
           OR player_full_name LIKE '%Sr.%' OR player_full_name LIKE '%III%')
),
odds_suffix_players AS (
    SELECT DISTINCT player_lookup
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2025-11-01'
)
SELECT
    COUNT(*) as total_suffix_players,
    COUNTIF(o.player_lookup IS NOT NULL) as matched,
    COUNTIF(o.player_lookup IS NULL) as unmatched
FROM espn_suffix_players e
LEFT JOIN odds_suffix_players o ON e.player_lookup = o.player_lookup;

-- ============================================================================
-- STEP 4: TEST NORMALIZATION EQUIVALENCE (Run before UPDATE to verify)
-- ============================================================================

-- Test that SQL produces same output as Python for known values
-- Expected results:
--   "Michael Porter Jr." -> "michaelporterjr"
--   "Gary Payton II" -> "garypatonii"
--   "LeBron James" -> "lebronjames"
--   "Nikola Jokić" -> "nikolajokic"
--   "D'Angelo Russell" -> "dangelorussell"

SELECT
    name,
    REGEXP_REPLACE(LOWER(NORMALIZE(name, NFD)), r'[^a-z0-9]', '') as normalized
FROM UNNEST([
    'Michael Porter Jr.',
    'Gary Payton II',
    'LeBron James',
    'Nikola Jokić',
    "D'Angelo Russell",
    'P.J. Tucker',
    'Karl-Anthony Towns'
]) as name;

-- ============================================================================
-- STEP 5: REGENERATE DOWNSTREAM TABLES (After backfill)
-- ============================================================================

-- After backfill, regenerate upcoming_player_game_context for affected dates.
-- Run from command line:
--
-- python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
--   --start-date 2025-11-01 --end-date 2025-12-31
--
-- This will rebuild the context table with correct JOINs between rosters and props.

-- ============================================================================
-- ROLLBACK (if needed - NOT RECOMMENDED)
-- ============================================================================

-- To rollback ESPN rosters (removes suffixes again):
-- WARNING: This reintroduces the bug!
/*
UPDATE `nba-props-platform.nba_raw.espn_team_rosters`
SET player_lookup = REGEXP_REPLACE(
    REGEXP_REPLACE(
        LOWER(NORMALIZE(player_full_name, NFD)),
        r'\s*(jr|sr|ii|iii|iv|v)$', ''
    ),
    r'[^a-z0-9]', ''
)
WHERE player_lookup IS NOT NULL;
*/
