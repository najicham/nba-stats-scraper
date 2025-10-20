-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/daily_freshness_check.sql
-- Purpose: Daily morning check - verify BDL active players updated recently
-- Usage: Run every morning at ~9 AM as part of automated monitoring
-- ============================================================================
-- UPDATED: Season-aware thresholds that adjust for training camp, regular season, playoffs
-- ============================================================================
-- Expected Results:
--   - status = "✅ Updated" when data refreshed within 48 hours
--   - status = "⚠️ Stale" if 48-96 hours since update
--   - status = "🔴 CRITICAL" if >96 hours since update
--   - All 30 teams should be present
--   - Player counts vary by season phase:
--     * Oct-Nov (Training Camp): 620-720 players
--     * Dec-Apr (Regular Season): 540-620 players
--     * Apr-Jun (Playoffs): 450-550 players
-- ============================================================================

WITH
-- Determine current season phase for dynamic thresholds
season_phase AS (
  SELECT
    EXTRACT(MONTH FROM CURRENT_DATE()) as current_month,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 'training_camp'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 'regular_season'
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 'playoffs'
      ELSE 'offseason'
    END as phase,
    -- Dynamic player count thresholds based on season phase
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 620  -- Training camp min
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 540  -- Regular season min
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 450  -- Playoffs min
      ELSE 500  -- Offseason min
    END as min_players,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 720  -- Training camp max
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 620  -- Regular season max
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 550  -- Playoffs max
      ELSE 650  -- Offseason max
    END as max_players,
    -- Validation rate expectations (higher is better!)
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 50  -- Training camp: more G-League movement
      ELSE 55  -- Regular season/playoffs: more stable rosters
    END as min_validation_pct
),

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

-- Determine status based on update recency and season phase
status_check AS (
  SELECT
    l.*,
    s.phase,
    s.min_players,
    s.max_players,
    s.min_validation_pct,
    CASE
      WHEN l.hours_since_update <= 48 THEN '✅ Updated'
      WHEN l.hours_since_update <= 96 THEN '⚠️ Stale (check scraper)'
      WHEN l.hours_since_update > 96 THEN '🔴 CRITICAL: Not updating'
      ELSE '❓ Unknown'
    END as update_status,
    CASE
      WHEN l.unique_teams = 30 THEN '✅ All teams present'
      WHEN l.unique_teams < 30 THEN '🔴 CRITICAL: Missing teams'
      WHEN l.unique_teams > 30 THEN '🟡 WARNING: Extra teams'
      ELSE '❓ Unknown'
    END as team_status,
    CASE
      WHEN l.unique_players BETWEEN s.min_players AND s.max_players THEN '✅ Normal range'
      WHEN l.unique_players BETWEEN (s.min_players - 50) AND (s.max_players + 50) THEN '🟡 Outside typical range'
      WHEN l.unique_players < (s.min_players - 50) THEN '🔴 CRITICAL: Low player count'
      WHEN l.unique_players > (s.max_players + 50) THEN '🔴 CRITICAL: High player count'
      ELSE '❓ Unknown'
    END as player_count_status,
    -- Allow for 1-2 name collisions (Jaylin Williams, etc.)
    CASE
      WHEN ABS(l.unique_players - l.unique_bdl_ids) <= 2 THEN '✅ IDs match (allowing name collisions)'
      WHEN ABS(l.unique_players - l.unique_bdl_ids) <= 5 THEN '🟡 Minor ID mismatch'
      ELSE '🔴 CRITICAL: ID mismatch'
    END as id_consistency_status,
    -- FIXED: Higher validation rate is BETTER, not worse!
    CASE
      WHEN l.pct_validated >= 80 THEN '✅ Excellent validation'
      WHEN l.pct_validated >= 70 THEN '✅ Good validation'
      WHEN l.pct_validated >= s.min_validation_pct THEN '✅ Acceptable validation'
      WHEN l.pct_validated >= (s.min_validation_pct - 10) THEN '🟡 Low validation'
      ELSE '🔴 Very low validation'
    END as validation_status_check
  FROM last_update_check l
  CROSS JOIN season_phase s
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
  'Season Phase' as section,
  phase as metric,
  CONCAT('Expected: ', CAST(min_players AS STRING), '-', CAST(max_players AS STRING), ' players') as value,
  '📅 Context' as status
FROM status_check

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
  CONCAT('Expected: ', CAST(min_players AS STRING), '-', CAST(max_players AS STRING), ' (', phase, ')') as value,
  player_count_status as status
FROM status_check

UNION ALL

SELECT
  'BDL Player IDs' as section,
  CAST(unique_bdl_ids AS STRING) as metric,
  'Allows 1-2 name collisions' as value,
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
  'Higher is better! 80%+ excellent' as value,
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
    -- Critical conditions (only truly bad things)
    WHEN hours_since_update > 96 THEN '🔴 CRITICAL: Data not updating'
    WHEN unique_teams != 30 THEN '🔴 CRITICAL: Missing teams'
    WHEN unique_players < (min_players - 50) THEN '🔴 CRITICAL: Very low player count'
    WHEN unique_players > (max_players + 50) THEN '🔴 CRITICAL: Very high player count'
    WHEN ABS(unique_players - unique_bdl_ids) > 5 THEN '🔴 CRITICAL: Significant ID mismatch'
    -- Warning conditions
    WHEN hours_since_update > 48 THEN '🟡 WARNING: Data getting stale'
    WHEN pct_validated < (min_validation_pct - 10) THEN '🟡 WARNING: Low validation rate'
    WHEN ROUND(100.0 * missing_nba_com / unique_players, 1) > 40 THEN '🟡 WARNING: High missing rate'
    -- All good!
    ELSE '✅ All systems operational'
  END as status
FROM status_check;
