-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/daily_freshness_check.sql
-- Purpose: Daily morning check - verify BDL active players updated recently
-- Usage: Run every morning at ~9 AM as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily after scraper/processor complete
--   2. Alert if status != "✅ Updated" or update_age_hours > 48
--   3. No date parameters needed - automatically checks recent updates
-- ============================================================================
-- Expected Results:
--   - status = "✅ Updated" when data refreshed within 48 hours
--   - status = "⚠️ Stale" if 48-96 hours since update
--   - status = "🔴 CRITICAL" if >96 hours since update
--   - All 30 teams should be present
--   - ~550-600 players total
-- ============================================================================

WITH
-- Check when data was last updated
last_update_check AS (
  SELECT
    MAX(last_seen_date) as last_update_date,
    MAX(processed_at) as last_processed_timestamp,
    DATE_DIFF(CURRENT_DATE(), MAX(last_seen_date), DAY) as days_since_update,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since_update,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bdl_player_id) as unique_bdl_ids,
    COUNT(DISTINCT team_abbr) as unique_teams,
    COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) as validated_players,
    COUNT(CASE WHEN validation_status = 'missing_nba_com' THEN 1 END) as missing_nba_com,
    COUNT(CASE WHEN validation_status = 'team_mismatch' THEN 1 END) as team_mismatches,
    ROUND(100.0 * COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) / COUNT(*), 1) as pct_validated
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Determine status based on update recency
status_check AS (
  SELECT
    *,
    CASE
      WHEN hours_since_update <= 48 THEN '✅ Updated'
      WHEN hours_since_update <= 96 THEN '⚠️ Stale (check scraper)'
      WHEN hours_since_update > 96 THEN '🔴 CRITICAL: Not updating'
      ELSE '❓ Unknown'
    END as update_status,
    CASE
      WHEN unique_teams = 30 THEN '✅ All teams present'
      WHEN unique_teams < 30 THEN '🔴 CRITICAL: Missing teams'
      WHEN unique_teams > 30 THEN '🟡 WARNING: Extra teams'
      ELSE '❓ Unknown'
    END as team_status,
    CASE
      WHEN unique_players BETWEEN 550 AND 600 THEN '✅ Normal range'
      WHEN unique_players BETWEEN 500 AND 650 THEN '🟡 Outside typical range'
      WHEN unique_players < 500 THEN '🔴 CRITICAL: Low player count'
      WHEN unique_players > 650 THEN '🔴 CRITICAL: High player count'
      ELSE '❓ Unknown'
    END as player_count_status,
    CASE
      WHEN unique_players = unique_bdl_ids THEN '✅ IDs match'
      ELSE '🔴 CRITICAL: ID mismatch'
    END as id_consistency_status,
    CASE
      WHEN pct_validated >= 55 AND pct_validated <= 65 THEN '✅ Healthy'
      WHEN pct_validated >= 45 AND pct_validated <= 75 THEN '🟡 Acceptable'
      ELSE '🔴 Low validation rate'
    END as validation_status_check
  FROM last_update_check
)

-- Output: Daily freshness report
SELECT
  '=== DAILY CHECK: BDL ACTIVE PLAYERS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Check Date' as section,
  CAST(CURRENT_DATE() AS STRING) as metric,
  FORMAT_DATE('%A', CURRENT_DATE()) as value,
  '' as status

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== UPDATE STATUS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Last Update' as section,
  CAST(last_update_date AS STRING) as metric,
  CONCAT(CAST(days_since_update AS STRING), ' days ago') as value,
  update_status as status
FROM status_check

UNION ALL

SELECT
  'Last Processed' as section,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M UTC', last_processed_timestamp) as metric,
  CONCAT(CAST(hours_since_update AS STRING), ' hours ago') as value,
  '' as status
FROM status_check

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== DATA COMPLETENESS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Teams' as section,
  CONCAT(CAST(unique_teams AS STRING), ' of 30') as metric,
  '' as value,
  team_status as status
FROM status_check

UNION ALL

SELECT
  'Total Players' as section,
  CAST(unique_players AS STRING) as metric,
  'Expected: ~550-600' as value,
  player_count_status as status
FROM status_check

UNION ALL

SELECT
  'BDL Player IDs' as section,
  CAST(unique_bdl_ids AS STRING) as metric,
  'Should match player count' as value,
  id_consistency_status as status
FROM status_check

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== VALIDATION QUALITY ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Validated Players' as section,
  CONCAT(CAST(validated_players AS STRING), ' (', CAST(pct_validated AS STRING), '%)') as metric,
  'Expected: 55-65%' as value,
  validation_status_check as status
FROM status_check

UNION ALL

SELECT
  'Missing from NBA.com' as section,
  CONCAT(CAST(missing_nba_com AS STRING), ' (', CAST(ROUND(100.0 * missing_nba_com / unique_players, 1) AS STRING), '%)') as metric,
  'G-League, two-way contracts' as value,
  CASE
    WHEN ROUND(100.0 * missing_nba_com / unique_players, 1) <= 30 THEN '✅ Expected'
    WHEN ROUND(100.0 * missing_nba_com / unique_players, 1) <= 40 THEN '🟡 High but acceptable'
    ELSE '🔴 Too many missing'
  END as status
FROM status_check

UNION ALL

SELECT
  'Team Mismatches' as section,
  CONCAT(CAST(team_mismatches AS STRING), ' (', CAST(ROUND(100.0 * team_mismatches / unique_players, 1) AS STRING), '%)') as metric,
  'Recent trades, timing differences' as value,
  CASE
    WHEN ROUND(100.0 * team_mismatches / unique_players, 1) <= 20 THEN '✅ Normal'
    WHEN ROUND(100.0 * team_mismatches / unique_players, 1) <= 30 THEN '🟡 Review trades'
    ELSE '🔴 Excessive mismatches'
  END as status
FROM status_check

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== OVERALL STATUS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Daily Check Result' as section,
  '' as metric,
  '' as value,
  CASE
    WHEN hours_since_update > 96 OR unique_teams != 30 OR unique_players < 500 OR unique_players > 650 OR unique_players != unique_bdl_ids
    THEN '🔴 CRITICAL: Immediate action required'
    WHEN hours_since_update > 48 OR pct_validated < 45 OR ROUND(100.0 * missing_nba_com / unique_players, 1) > 40
    THEN '🟡 WARNING: Investigation recommended'
    ELSE '✅ All systems operational'
  END as status
FROM status_check;
