-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/daily_check_yesterday.sql
-- Purpose: Daily morning check - verify player list updated yesterday
-- Usage: Run every morning at ~9 AM as part of automated monitoring
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily after scraper/processor complete
--   2. Alert if status != "✅ Updated" or update_age_hours > 36
--   3. No date parameters needed - automatically checks recent updates
-- ============================================================================
-- Expected Results:
--   - status = "✅ Updated" when data refreshed within 24 hours
--   - status = "⚠️ Stale" if 24-36 hours since update
--   - status = "🔴 CRITICAL" if >36 hours since update
--   - All 30 teams should be present
-- ============================================================================

WITH
-- Check when data was last updated
last_update_check AS (
  SELECT
    MAX(last_seen_date) as last_update_date,
    MAX(processed_at) as last_processed_timestamp,
    DATE_DIFF(CURRENT_DATE(), MAX(last_seen_date)) as days_since_update,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since_update,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_players,
    COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as players_no_team,
    MAX(season_year) as current_season
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024  -- Partition filter
),

-- Determine status based on update recency
status_check AS (
  SELECT
    *,
    CASE
      WHEN hours_since_update <= 24 THEN '✅ Updated'
      WHEN hours_since_update <= 36 THEN '⚠️ Stale (check scraper)'
      WHEN hours_since_update > 36 THEN '🔴 CRITICAL: Not updating'
      ELSE '❓ Unknown'
    END as update_status,
    CASE
      WHEN unique_teams = 30 THEN '✅ All teams present'
      WHEN unique_teams < 30 THEN '🔴 CRITICAL: Missing teams'
      WHEN unique_teams > 30 THEN '🟡 WARNING: Extra teams'
      ELSE '❓ Unknown'
    END as team_status,
    CASE
      WHEN active_players BETWEEN 390 AND 550 THEN '✅ Normal range'
      WHEN active_players < 390 THEN '🟡 WARNING: Low player count'
      WHEN active_players > 550 THEN '🟡 WARNING: High player count'
      ELSE '❓ Unknown'
    END as player_count_status,
    CASE
      WHEN players_no_team = 0 THEN '✅ No issues'
      ELSE '🟡 WARNING: Players without teams'
    END as data_quality_status
  FROM last_update_check
)

-- Output: Yesterday's update status
SELECT
  '=== DAILY CHECK: PLAYER LIST ===' as section,
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
  'Active Players' as section,
  CAST(active_players AS STRING) as metric,
  'Expected: ~390-550' as value,
  player_count_status as status
FROM status_check

UNION ALL

SELECT
  'Unique Players' as section,
  CAST(unique_players AS STRING) as metric,
  'Total in table' as value,
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
  '=== DATA QUALITY ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Players Without Teams' as section,
  CAST(players_no_team AS STRING) as metric,
  '' as value,
  data_quality_status as status
FROM status_check

UNION ALL

SELECT
  'Season Year' as section,
  CAST(current_season AS STRING) as metric,
  CONCAT(CAST(current_season AS STRING), '-', CAST(current_season + 1 - 2000 AS STRING)) as value,
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
    WHEN hours_since_update > 36 OR unique_teams != 30 THEN '🔴 CRITICAL: Immediate action required'
    WHEN hours_since_update > 24 OR active_players NOT BETWEEN 390 AND 550 THEN '🟡 WARNING: Investigation recommended'
    ELSE '✅ All systems operational'
  END as status
FROM status_check;
