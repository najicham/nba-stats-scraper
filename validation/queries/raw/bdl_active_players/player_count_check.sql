-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/player_count_check.sql
-- Purpose: Verify expected player counts across teams and validation status
-- Usage: Run daily to ensure basic data volume is correct
-- ============================================================================
-- UPDATED: Season-aware thresholds that adjust for training camp, regular season, playoffs
-- ============================================================================
-- Expected Results by Season Phase:
--   Training Camp (Oct-Nov):
--     - Total players: 620-720
--     - Teams found: 30
--     - Players per team: 17-26 (average ~22)
--     - Validation rate: 50%+ (higher is better!)
--   
--   Regular Season (Dec-Apr):
--     - Total players: 540-620
--     - Teams found: 30
--     - Players per team: 15-21 (average ~19)
--     - Validation rate: 55%+ (higher is better!)
--   
--   Playoffs (May-Jun):
--     - Total players: 450-550
--     - Teams found: 16-30 (decreasing as teams eliminated)
--     - Players per team: 13-18
--     - Validation rate: 60%+ (higher is better!)
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
    -- Player count thresholds
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 620
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 540
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 450
      ELSE 500
    END as min_players,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 720
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 620
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (5, 6) THEN 550
      ELSE 650
    END as max_players,
    -- Team roster size thresholds
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 17  -- Training camp
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 15  -- Regular season
      ELSE 13  -- Playoffs/offseason
    END as min_team_players,
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 26  -- Training camp
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (12, 1, 2, 3, 4) THEN 21  -- Regular season
      ELSE 18  -- Playoffs/offseason
    END as max_team_players,
    -- Validation rate (higher is better!)
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (10, 11) THEN 50
      ELSE 55
    END as min_validation_pct
),

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
    s.min_team_players,
    s.max_team_players,
    COUNT(CASE WHEN player_count < s.min_team_players THEN 1 END) as teams_low,
    COUNT(CASE WHEN player_count > s.max_team_players THEN 1 END) as teams_high
  FROM team_counts
  CROSS JOIN season_phase s
  GROUP BY s.min_team_players, s.max_team_players
)

-- Output: Summary metrics
SELECT
  '=== OVERALL METRICS ===' as section,
  '' as metric,
  '' as value,
  '' as status

UNION ALL

SELECT
  'Season Phase' as section,
  s.phase as metric,
  CONCAT('Expected: ', CAST(s.min_players AS STRING), '-', CAST(s.max_players AS STRING), ' players') as value,
  '📅 Context' as status
FROM season_phase s

UNION ALL

SELECT
  'Total Players' as section,
  'Unique player_lookup values' as metric,
  CAST(m.total_players AS STRING) as value,
  CASE
    WHEN m.total_players BETWEEN s.min_players AND s.max_players THEN '✅ Expected range'
    WHEN m.total_players BETWEEN (s.min_players - 50) AND (s.max_players + 50) THEN '🟡 Outside typical range'
    ELSE '🔴 CRITICAL: Investigate count'
  END as status
FROM overall_metrics m
CROSS JOIN season_phase s

UNION ALL

SELECT
  'Unique BDL IDs' as section,
  'Should match player count' as metric,
  CAST(unique_bdl_ids AS STRING) as value,
  CASE
    WHEN ABS(total_players - unique_bdl_ids) <= 2 THEN '✅ Match (allowing name collisions)'
    WHEN ABS(total_players - unique_bdl_ids) <= 5 THEN '🟡 Minor mismatch'
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
  CONCAT(CAST(m.validated_count AS STRING), ' (', CAST(m.pct_validated AS STRING), '%)') as value,
  CASE
    WHEN m.pct_validated >= 80 THEN '✅ Excellent (80%+)'
    WHEN m.pct_validated >= 70 THEN '✅ Good (70%+)'
    WHEN m.pct_validated >= s.min_validation_pct THEN '✅ Acceptable'
    WHEN m.pct_validated >= (s.min_validation_pct - 10) THEN '🟡 Low validation'
    ELSE '🔴 Very low validation'
  END as status
FROM overall_metrics m
CROSS JOIN season_phase s

UNION ALL

SELECT
  'Players with Issues' as section,
  'has_validation_issues = TRUE' as metric,
  CONCAT(CAST(has_issues_count AS STRING), ' (', CAST(ROUND(100.0 - pct_validated, 1) AS STRING), '%)') as value,
  CASE
    WHEN has_issues_count <= total_records * 0.50 THEN '✅ Expected'
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
    WHEN avg_players_per_team BETWEEN min_team_players AND max_team_players THEN '✅ Typical'
    ELSE '🟡 Check distribution'
  END as status
FROM team_stats

UNION ALL

SELECT
  'Range' as section,
  'Min to Max' as metric,
  CONCAT(CAST(ts.min_players AS STRING), ' - ', CAST(ts.max_players AS STRING)) as value,
  CASE
    WHEN ts.min_players >= ts.min_team_players AND ts.max_players <= ts.max_team_players THEN '✅ Normal'
    WHEN ts.min_players < ts.min_team_players THEN '🟡 Some teams low'
    WHEN ts.max_players > ts.max_team_players THEN '🟡 Some teams high'
    ELSE '🟡 Review outliers'
  END as status
FROM team_stats ts

UNION ALL

SELECT
  'Teams with Issues' as section,
  CONCAT('Low (<', CAST(min_team_players AS STRING), ') or High (>', CAST(max_team_players AS STRING), ') rosters') as metric,
  CONCAT('Low: ', CAST(teams_low AS STRING), ' | High: ', CAST(teams_high AS STRING)) as value,
  CASE
    WHEN teams_low = 0 AND teams_high = 0 THEN '✅ All teams normal'
    WHEN teams_low + teams_high <= 3 THEN '🟡 Few outliers'
    WHEN teams_low + teams_high <= 10 THEN '🟡 Moderate outliers'
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
