-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/player_count_check.sql
-- Purpose: Verify expected player counts across teams and validation status
-- Usage: Run daily to ensure basic data volume is correct
-- ============================================================================
-- Instructions:
--   1. Should find ~550-600 players across 30 teams
--   2. Each team should have 13-20 players (typical)
--   3. ~60% should be 'validated' status (healthy)
-- ============================================================================
-- Expected Results:
--   - Total players: 550-600
--   - Teams found: 30
--   - Players per team: 13-20 (average ~19)
--   - Validation rate: 55-65%
-- ============================================================================

WITH
-- Calculate overall metrics
overall_metrics AS (
  SELECT
    COUNT(DISTINCT player_lookup) as total_players,
    COUNT(DISTINCT bdl_player_id) as unique_bdl_ids,
    COUNT(DISTINCT team_abbr) as teams_found,
    COUNT(*) as total_records,
    COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) as validated_count,
    COUNT(CASE WHEN has_validation_issues = TRUE THEN 1 END) as has_issues_count,
    ROUND(100.0 * COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) / COUNT(*), 1) as pct_validated,
    MAX(last_seen_date) as last_update_date,
    MAX(processed_at) as last_processed
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Players per team
team_counts AS (
  SELECT
    team_abbr,
    team_full_name,
    COUNT(DISTINCT player_lookup) as player_count,
    COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) as validated_players,
    ROUND(100.0 * COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) / COUNT(*), 1) as pct_validated
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  GROUP BY team_abbr, team_full_name
),

-- Team count statistics
team_stats AS (
  SELECT
    AVG(player_count) as avg_players_per_team,
    MIN(player_count) as min_players,
    MAX(player_count) as max_players,
    STDDEV(player_count) as stddev_players,
    COUNT(CASE WHEN player_count < 13 THEN 1 END) as teams_low,
    COUNT(CASE WHEN player_count > 20 THEN 1 END) as teams_high
  FROM team_counts
)

-- Output: Summary metrics
SELECT
  '=== OVERALL METRICS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Total Players' as section,
  'Unique player_lookup values' as metric,
  CAST(total_players AS STRING) as value,
  CASE
    WHEN total_players BETWEEN 550 AND 600 THEN '✅ Expected range'
    WHEN total_players BETWEEN 500 AND 650 THEN '🟡 Outside typical range'
    ELSE '🔴 CRITICAL: Investigate count'
  END as status
FROM overall_metrics

UNION ALL

SELECT
  'Unique BDL IDs' as section,
  'Should match player count' as metric,
  CAST(unique_bdl_ids AS STRING) as value,
  CASE
    WHEN unique_bdl_ids = total_players THEN '✅ Match'
    ELSE '🔴 CRITICAL: Mismatch detected'
  END as status
FROM overall_metrics

UNION ALL

SELECT
  'Teams Found' as section,
  'All NBA teams' as metric,
  CONCAT(CAST(teams_found AS STRING), ' of 30') as value,
  CASE
    WHEN teams_found = 30 THEN '✅ Complete'
    WHEN teams_found < 30 THEN '🔴 CRITICAL: Missing teams'
    ELSE '🔴 CRITICAL: Too many teams'
  END as status
FROM overall_metrics

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== VALIDATION STATUS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Validated Players' as section,
  'has_validation_issues = FALSE' as metric,
  CONCAT(CAST(validated_count AS STRING), ' (', CAST(pct_validated AS STRING), '%)') as value,
  CASE
    WHEN pct_validated >= 55 AND pct_validated <= 65 THEN '✅ Healthy range'
    WHEN pct_validated >= 45 AND pct_validated <= 75 THEN '🟡 Acceptable'
    ELSE '🔴 Investigate validation logic'
  END as status
FROM overall_metrics

UNION ALL

SELECT
  'Players with Issues' as section,
  'has_validation_issues = TRUE' as metric,
  CONCAT(CAST(has_issues_count AS STRING), ' (', CAST(ROUND(100.0 - pct_validated, 1) AS STRING), '%)') as value,
  CASE
    WHEN has_issues_count <= total_records * 0.45 THEN '✅ Expected'
    ELSE '🟡 High issue rate'
  END as status
FROM overall_metrics

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== TEAM DISTRIBUTION ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Average Players/Team' as section,
  '' as metric,
  CAST(ROUND(avg_players_per_team, 1) AS STRING) as value,
  CASE
    WHEN avg_players_per_team BETWEEN 17 AND 20 THEN '✅ Typical'
    ELSE '🟡 Check distribution'
  END as status
FROM team_stats

UNION ALL

SELECT
  'Range' as section,
  'Min to Max' as metric,
  CONCAT(CAST(min_players AS STRING), ' - ', CAST(max_players AS STRING)) as value,
  CASE
    WHEN min_players >= 13 AND max_players <= 20 THEN '✅ Normal'
    WHEN min_players < 13 THEN '🟡 Some teams low'
    WHEN max_players > 20 THEN '🟡 Some teams high'
    ELSE '🟡 Review outliers'
  END as status
FROM team_stats

UNION ALL

SELECT
  'Teams with Issues' as section,
  'Low (<13) or High (>20) rosters' as metric,
  CONCAT('Low: ', CAST(teams_low AS STRING), ' | High: ', CAST(teams_high AS STRING)) as value,
  CASE
    WHEN teams_low = 0 AND teams_high = 0 THEN '✅ All teams normal'
    WHEN teams_low + teams_high <= 3 THEN '🟡 Few outliers'
    ELSE '🔴 Many outliers'
  END as status
FROM team_stats

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  '=== DATA FRESHNESS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Last Update' as section,
  CAST(last_update_date AS STRING) as metric,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M UTC', last_processed) as value,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), last_update_date, DAY) <= 2 THEN '✅ Fresh'
    WHEN DATE_DIFF(CURRENT_DATE(), last_update_date, DAY) <= 7 THEN '🟡 Stale'
    ELSE '🔴 Very old'
  END as status
FROM overall_metrics;
