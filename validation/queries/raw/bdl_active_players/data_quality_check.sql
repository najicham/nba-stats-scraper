-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/data_quality_check.sql
-- Purpose: Comprehensive data quality validation for BDL active players
-- Usage: Run regularly to detect duplicates, NULLs, and data integrity issues
-- ============================================================================
-- Instructions:
--   1. All quality checks should return 0 issues
--   2. Any non-zero counts require investigation
--   3. Duplicates on player_lookup or bdl_player_id are CRITICAL
-- ============================================================================
-- Expected Results:
--   - All checks should show "✅ Pass" status
--   - Duplicate player_lookup: 0 (PRIMARY KEY violation)
--   - Duplicate bdl_player_id: 0 (unique constraint violation)
--   - NULL required fields: 0
--   - Invalid validation_status values: 0
-- ============================================================================

WITH
-- Check for duplicate player_lookup values (PRIMARY KEY violation)
duplicate_players AS (
  SELECT
    player_lookup,
    COUNT(*) as duplicate_count,
    STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name) as names
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  GROUP BY player_lookup
  HAVING COUNT(*) > 1
),

-- Check for duplicate bdl_player_id values
duplicate_bdl_ids AS (
  SELECT
    bdl_player_id,
    COUNT(*) as duplicate_count,
    STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name) as names,
    STRING_AGG(DISTINCT player_lookup ORDER BY player_lookup) as lookups
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  GROUP BY bdl_player_id
  HAVING COUNT(*) > 1
),

-- Check for NULL required fields
null_checks AS (
  SELECT
    COUNT(CASE WHEN player_lookup IS NULL THEN 1 END) as null_player_lookup,
    COUNT(CASE WHEN bdl_player_id IS NULL THEN 1 END) as null_bdl_player_id,
    COUNT(CASE WHEN player_full_name IS NULL THEN 1 END) as null_full_name,
    COUNT(CASE WHEN has_validation_issues IS NULL THEN 1 END) as null_has_issues,
    COUNT(CASE WHEN validation_status IS NULL THEN 1 END) as null_validation_status,
    COUNT(CASE WHEN processed_at IS NULL THEN 1 END) as null_processed_at,
    COUNT(CASE WHEN last_seen_date IS NULL THEN 1 END) as null_last_seen,
    COUNT(*) as total_records
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Check for invalid/suspicious data
data_validation AS (
  SELECT
    COUNT(CASE WHEN team_abbr IS NOT NULL AND LENGTH(team_abbr) != 3 THEN 1 END) as invalid_team_abbr,
    COUNT(CASE WHEN validation_status NOT IN ('validated', 'missing_nba_com', 'team_mismatch', 'data_quality_issue') THEN 1 END) as invalid_validation_status,
    COUNT(CASE WHEN last_seen_date > CURRENT_DATE() THEN 1 END) as future_dates,
    COUNT(CASE WHEN last_seen_date < DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY) THEN 1 END) as very_old_dates,
    COUNT(CASE WHEN processed_at > CURRENT_TIMESTAMP() THEN 1 END) as future_timestamps,
    -- Validation consistency check
    COUNT(CASE 
      WHEN has_validation_issues = FALSE AND validation_status != 'validated' THEN 1
      WHEN has_validation_issues = TRUE AND validation_status = 'validated' THEN 1
    END) as validation_logic_mismatch
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Summary metrics
quality_summary AS (
  SELECT
    (SELECT COUNT(*) FROM duplicate_players) as duplicate_player_lookup_count,
    (SELECT COUNT(*) FROM duplicate_bdl_ids) as duplicate_bdl_id_count,
    n.null_player_lookup,
    n.null_bdl_player_id,
    n.null_has_issues,
    n.null_validation_status,
    n.null_processed_at,
    d.invalid_team_abbr,
    d.invalid_validation_status,
    d.future_dates,
    d.very_old_dates,
    d.future_timestamps,
    d.validation_logic_mismatch,
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
  'Duplicate bdl_player_id' as section,
  'BDL ID uniqueness' as check_name,
  CAST(duplicate_bdl_id_count AS STRING) as issues_found,
  CASE
    WHEN duplicate_bdl_id_count = 0 THEN '✅ Pass'
    ELSE '🔴 CRITICAL: Duplicate BDL IDs'
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
  '=== REQUIRED FIELD CHECKS ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'NULL player_lookup' as section,
  'Critical field (primary key)' as check_name,
  CAST(null_player_lookup AS STRING) as issues_found,
  CASE WHEN null_player_lookup = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL bdl_player_id' as section,
  'Critical field (unique ID)' as check_name,
  CAST(null_bdl_player_id AS STRING) as issues_found,
  CASE WHEN null_bdl_player_id = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL has_validation_issues' as section,
  'Critical field (boolean)' as check_name,
  CAST(null_has_issues AS STRING) as issues_found,
  CASE WHEN null_has_issues = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL validation_status' as section,
  'Critical field (status)' as check_name,
  CAST(null_validation_status AS STRING) as issues_found,
  CASE WHEN null_validation_status = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'NULL processed_at' as section,
  'Critical field (timestamp)' as check_name,
  CAST(null_processed_at AS STRING) as issues_found,
  CASE WHEN null_processed_at = 0 THEN '✅ Pass' ELSE '🟡 WARNING' END as status
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
  'Invalid validation_status' as section,
  'Must be valid enum value' as check_name,
  CAST(invalid_validation_status AS STRING) as issues_found,
  CASE WHEN invalid_validation_status = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'Future last_seen_date' as section,
  'Date cannot be in future' as check_name,
  CAST(future_dates AS STRING) as issues_found,
  CASE WHEN future_dates = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  'Very old last_seen_date' as section,
  'Date > 90 days old' as check_name,
  CAST(very_old_dates AS STRING) as issues_found,
  CASE WHEN very_old_dates = 0 THEN '✅ Pass' ELSE '🟡 WARNING: Stale data?' END as status
FROM quality_summary

UNION ALL

SELECT
  'Future processed_at' as section,
  'Timestamp cannot be in future' as check_name,
  CAST(future_timestamps AS STRING) as issues_found,
  CASE WHEN future_timestamps = 0 THEN '✅ Pass' ELSE '🔴 CRITICAL' END as status
FROM quality_summary

UNION ALL

SELECT
  '' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  '=== VALIDATION LOGIC CONSISTENCY ===' as section,
  '' as check_name,
  '' as issues_found,
  '' as status

UNION ALL

SELECT
  'Validation logic mismatch' as section,
  'has_issues vs validation_status consistency' as check_name,
  CAST(validation_logic_mismatch AS STRING) as issues_found,
  CASE
    WHEN validation_logic_mismatch = 0 THEN '✅ Pass'
    ELSE '🔴 CRITICAL: Logic inconsistency'
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
    WHEN duplicate_player_lookup_count > 0 
      OR duplicate_bdl_id_count > 0
      OR null_player_lookup > 0 
      OR null_bdl_player_id > 0
      OR null_has_issues > 0
      OR null_validation_status > 0
      OR invalid_team_abbr > 0 
      OR invalid_validation_status > 0
      OR future_dates > 0
      OR future_timestamps > 0
      OR validation_logic_mismatch > 0
    THEN '🔴 CRITICAL: Action required'
    WHEN very_old_dates > 0 OR null_processed_at > 0
    THEN '🟡 WARNING: Review recommended'
    ELSE '✅ All checks passed'
  END as status
FROM quality_summary;
