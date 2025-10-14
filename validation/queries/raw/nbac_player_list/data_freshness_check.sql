-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/data_freshness_check.sql
-- Purpose: Verify player list is being updated regularly (current-state table)
-- Usage: Run daily to ensure scraper/processor are functioning
-- ============================================================================
-- Instructions:
--   1. Schedule to run daily at ~9 AM (after morning scraper completes)
--   2. Alert if status != "✅ Fresh" or hours_since_update > 36
--   3. No parameters needed - checks current state automatically
-- ============================================================================
-- Expected Results:
--   - last_update within 24 hours = "✅ Fresh"
--   - last_update 24-36 hours = "⚠️ Stale"
--   - last_update >36 hours = "🔴 CRITICAL"
--   - All 30 teams present with ~13-17 active players each
-- ============================================================================

WITH
-- Get freshness metrics
freshness_metrics AS (
  SELECT
    MAX(last_seen_date) as last_update_date,
    MAX(processed_at) as last_processed_timestamp,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since_update,
    COUNT(*) as total_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_players,
    COUNT(CASE WHEN team_abbr IS NULL THEN 1 END) as null_teams,
    MAX(season_year) as current_season
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024  -- Partition filter for current data
),

-- Determine status
status_check AS (
  SELECT
    *,
    CASE
      WHEN hours_since_update <= 24 THEN '✅ Fresh'
      WHEN hours_since_update <= 36 THEN '⚠️ Stale (check scraper)'
      WHEN hours_since_update > 36 THEN '🔴 CRITICAL: Data not updating'
      ELSE '❓ Unknown'
    END as freshness_status,
    CASE
      WHEN unique_teams < 30 THEN '🔴 CRITICAL: Missing teams'
      WHEN unique_teams > 30 THEN '🟡 WARNING: Extra teams'
      WHEN unique_teams = 30 THEN '✅ All teams present'
      ELSE '❓ Unknown'
    END as team_status,
    CASE
      WHEN active_players < 390 THEN '🟡 WARNING: Low player count'
      WHEN active_players > 550 THEN '🟡 WARNING: High player count'
      ELSE '✅ Normal range'
    END as player_count_status,
    CASE
      WHEN null_teams > 0 THEN '🔴 CRITICAL: Players without teams'
      ELSE '✅ No NULL teams'
    END as data_quality_status
  FROM freshness_metrics
)

-- Output: Freshness report
SELECT
  '=== DATA FRESHNESS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Last Update Date' as section,
  CAST(last_update_date AS STRING) as metric,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', last_processed_timestamp) as value,
  freshness_status as status
FROM status_check

UNION ALL

SELECT
  'Hours Since Update' as section,
  CAST(hours_since_update AS STRING) as metric,
  CASE
    WHEN hours_since_update <= 24 THEN 'Within expected range'
    ELSE 'Investigate scraper/processor'
  END as value,
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
  '=== DATA VOLUME ===' as section,
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
  'NULL Teams' as section,
  CAST(null_teams AS STRING) as metric,
  '' as value,
  data_quality_status as status
FROM status_check

UNION ALL

SELECT
  'Season Year' as section,
  CAST(current_season AS STRING) as metric,
  CONCAT(CAST(current_season AS STRING), '-', CAST(current_season + 1 - 2000 AS STRING)) as value,
  '' as status
FROM status_check;