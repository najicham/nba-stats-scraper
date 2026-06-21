-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/data_quality_check.sql
-- Purpose: Comprehensive data quality validation for player list
-- Usage: Run regularly to detect duplicates, NULLs, and data integrity issues
-- ============================================================================
-- Instructions:
--   1. All quality checks should return 0 issues
--   2. Any non-zero counts require investigation
--   3. Duplicates on player_lookup are CRITICAL (primary key violation)
-- ============================================================================
-- Expected Results:
--   - All checks should show "✅ Pass" status
--   - Duplicate player_lookup: 0
--   - NULL critical fields: 0
--   - Invalid data: 0
-- ============================================================================

WITH
-- Check for duplicate player_lookup values (PRIMARY KEY violation)
duplicate_players AS (
  SELECT
    player_lookup,
    COUNT(*) as duplicate_count,
    STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY player_lookup
  HAVING COUNT(*) > 1
),

-- Check for duplicate player_id values
duplicate_player_ids AS (
  SELECT
    player_id,
    COUNT(*) as duplicate_count,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name) as names
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
    AND player_id IS NOT NULL
  GROUP BY player_id
  HAVING COUNT(*) > 1
),

-- Check for NULL critical fields
null_checks AS (
  SELECT
    COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_player_lookup,
    COUNT(CASE WHEN player_id IS NULL THEN 1 END) as null_player_id,
    COUNT(CASE WHEN player_full_name IS NULL THEN 1 END) as null_full_name,
    COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as null_team_abbr,
    COUNT(CASE WHEN is_active IS NULL THEN 1 END) as null_is_active,
    COUNT(CASE WHEN season_year IS NULL THEN 1 END) as null_season_year,
    COUNT(CASE WHEN last_seen_date IS NULL THEN 1 END) as null_last_seen,
    COUNT(*) as total_records
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
),

-- Check for invalid/suspicious data
data_validation AS (
  SELECT
    COUNT(CASE WHEN LENGTH(team_abbr) != 3 THEN 1 END) as invalid_team_abbr,
    COUNT(CASE WHEN season_year < 2020 OR season_year > 2030 THEN 1 END) as invalid_season,
    COUNT(CASE WHEN last_seen_date > CURRENT_DATE() THEN 1 END) as future_dates,
    COUNT(CASE WHEN last_seen_date < DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY) THEN 1 END) as very_old_dates,
    COUNT(CASE WHEN jersey_number IS NOT NULL AND (CAST(jersey_number AS INT64) < 0 OR CAST(jersey_number AS INT64) > 99) THEN 1 END) as invalid_jersey
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
),

-- Summary metrics
quality_summary AS (
  SELECT
    (SELECT COUNT(*) FROM duplicate_players) as duplicate_player_lookup_count,
    (SELECT COUNT(*) FROM duplicate_player_ids) as duplicate_player_id_count,
    n.null_player_lookup,
    n.null_team_abbr,
    n.null_is_active,
    n.null_last_seen,
    d.invalid_team_abbr,
    d.invalid_season,
    d.future_dates,
    d.very_old_dates,
    n.total_records
  FROM null_checks n
  CROSS JOIN data_validation d
)

-- Output: Quality report
SELECT
  '=== PRIMARY KEY VALIDATION ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'Duplicate player_lookup' as section,
  'Primary key uniqueness' as check_name,
  CAST(duplicate_player_lookup_count AS STRING) as issues_found,
  CASE
    WHEN duplicate_player_lookup_count = 0 THEN '✅ Pass'
    ELSE '🔴 CRITICAL: Primary key violation'
  END as status
FROM quality_summary

UNION ALL

SELECT
  'Duplicate player_id' as section,
  'NBA.com ID uniqueness' as check_name,
  CAST(duplicate_player_id_count AS STRING) as issues_found,
  CASE
    WHEN duplicate_player_id_count = 0 THEN '✅ Pass'
    ELSE '🟡 WARNING: Investigate duplicates'
  END as status
FROM quality_summary

UNION ALL

SELECT
  '' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  '=== NULL FIELD CHECKS ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'NULL player_lookup' as section,
  'Critical field' as check_name,
  CAST(null_player_lookup AS STRING) as issues_found,
  CASE WHEN null_player_lookup = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL team_abbr' as section,
  'Team assignment' as check_name,
  CAST(null_team_abbr AS STRING) as issues_found,
  CASE WHEN null_team_abbr = 0 THEN '✅ Pass' ELSE '🟡 WARNING: Free agents?' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL is_active' as section,
  'Roster status' as check_name,
  CAST(null_is_active AS STRING) as issues_found,
  CASE WHEN null_is_active = 0 THEN '✅ Pass' ELSE '🟡 WARNING' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL last_seen_date' as section,
  'Update tracking' as check_name,
  CAST(null_last_seen AS STRING) as issues_found,
  CASE WHEN null_last_seen = 0 THEN '✅ Pass' ELSE '🟡 WARNING' END as status
FROM quality_summary

UNION ALL

SELECT
  '' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  '=== DATA VALIDATION ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'Invalid team_abbr' as section,
  'Must be 3 letters' as check_name,
  CAST(invalid_team_abbr AS STRING) as issues_found,
  CASE WHEN invalid_team_abbr = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'Invalid season_year' as section,
  'Reasonable range' as check_name,
  CAST(invalid_season AS STRING) as issues_found,
  CASE WHEN invalid_season = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'Future dates' as section,
  'last_seen_date > today' as check_name,
  CAST(future_dates AS STRING) as issues_found,
  CASE WHEN future_dates = 0 THEN '✅ Pass' ELSE '🟡 WARNING' END as status
FROM quality_summary

UNION ALL

SELECT
  'Very old dates' as section,
  'last_seen_date > 1 year old' as check_name,
  CAST(very_old_dates AS STRING) as issues_found,
  CASE WHEN very_old_dates = 0 THEN '✅ Pass' ELSE '🟡 WARNING: Stale data?' END as status
FROM quality_summary

UNION ALL

SELECT
  '' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  '=== SUMMARY ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'Total Records' as section,
  '' as check_name,
  CAST(total_records AS STRING) as issues_found,
  '' as status
FROM quality_summary

UNION ALL

SELECT
  'Overall Status' as section,
  '' as check_name,
  '' as issues_found,
  CASE
    WHEN duplicate_player_lookup_count > 0 OR null_player_lookup > 0 OR invalid_team_abbr > 0 OR invalid_season > 0
    THEN '🔴 CRITICAL: Action required'
    WHEN null_team_abbr > 0 OR duplicate_player_id_count > 0 OR very_old_dates > 0
    THEN '🟡 WARNING: Review recommended'
    ELSE '✅ All checks passed'
  END as status
FROM quality_summary;
