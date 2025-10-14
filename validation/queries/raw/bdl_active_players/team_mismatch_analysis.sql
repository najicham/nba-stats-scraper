-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/team_mismatch_analysis.sql
-- Purpose: Deep dive into validation_status = 'team_mismatch' cases
-- Usage: Run when team mismatch rate is high (>20%) to investigate
-- ============================================================================
-- Instructions:
--   1. Shows BDL team vs NBA.com team for each mismatch
--   2. Groups by team to find patterns (recent trades, timing issues)
--   3. Parses validation_details JSON for specific reasons
-- ============================================================================
-- Expected Results:
--   - ~10-20% of players should have team mismatches
--   - Common causes: recent trades, roster timing differences
--   - Some teams may have higher mismatch rates (active trade deadline)
-- ============================================================================

WITH
-- Get all team mismatch cases
team_mismatches AS (
  SELECT
    player_lookup,
    player_full_name,
    team_abbr as bdl_team,
    team_full_name as bdl_team_name,
    nba_com_team_abbr as nbac_team,
    validation_status,
    validation_details,
    last_seen_date,
    processed_at
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  WHERE validation_status = 'team_mismatch'
),

-- Mismatch counts by BDL team
bdl_team_mismatches AS (
  SELECT
    bdl_team,
    bdl_team_name,
    COUNT(*) as mismatch_count,
    STRING_AGG(player_full_name ORDER BY player_full_name LIMIT 5) as sample_players
  FROM team_mismatches
  GROUP BY bdl_team, bdl_team_name
),

-- Common team pair mismatches (trades)
team_pair_mismatches AS (
  SELECT
    bdl_team,
    nbac_team,
    COUNT(*) as mismatch_count,
    STRING_AGG(player_full_name ORDER BY player_full_name) as players
  FROM team_mismatches
  GROUP BY bdl_team, nbac_team
),

-- Overall stats
overall_stats AS (
  SELECT
    COUNT(*) as total_mismatches,
    COUNT(DISTINCT bdl_team) as teams_with_mismatches_bdl,
    COUNT(DISTINCT nbac_team) as teams_with_mismatches_nbac,
    MAX(last_seen_date) as most_recent_update,
    MIN(last_seen_date) as oldest_update
  FROM team_mismatches
)

-- Output: Mismatch analysis
SELECT
  '=== TEAM MISMATCH SUMMARY ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  'Total Mismatches' as section,
  '' as metric,
  CAST(total_mismatches AS STRING) as count,
  '' as details,
  CASE
    WHEN total_mismatches <= (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_active_players_current`) * 0.20
    THEN '✅ Normal range (<20%)'
    WHEN total_mismatches <= (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_active_players_current`) * 0.30
    THEN '🟡 High (20-30%)'
    ELSE '🔴 Very high (>30%)'
  END as status
FROM overall_stats

UNION ALL

SELECT
  'Teams Affected (BDL)' as section,
  '' as metric,
  CONCAT(CAST(teams_with_mismatches_bdl AS STRING), ' of 30') as count,
  '' as details,
  '' as status
FROM overall_stats

UNION ALL

SELECT
  'Teams Affected (NBA.com)' as section,
  '' as metric,
  CONCAT(CAST(teams_with_mismatches_nbac AS STRING), ' of 30') as count,
  '' as details,
  '' as status
FROM overall_stats

UNION ALL

SELECT
  'Data Recency' as section,
  CAST(most_recent_update AS STRING) as metric,
  CONCAT('Oldest: ', CAST(oldest_update AS STRING)) as count,
  '' as details,
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), most_recent_update, DAY) <= 2 THEN '✅ Fresh'
    ELSE '🟡 May be stale'
  END as status
FROM overall_stats

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  '=== TEAMS WITH MOST MISMATCHES ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  bdl_team as section,
  bdl_team_name as metric,
  CAST(mismatch_count AS STRING) as count,
  sample_players as details,
  CASE
    WHEN mismatch_count >= 5 THEN '🔴 High mismatch count'
    WHEN mismatch_count >= 3 THEN '🟡 Review these players'
    ELSE '✅ Low'
  END as status
FROM bdl_team_mismatches

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  '=== COMMON TRADE PAIRS ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  CONCAT(bdl_team, ' → ', nbac_team) as section,
  'Possible trade or timing difference' as metric,
  CAST(mismatch_count AS STRING) as count,
  players as details,
  CASE
    WHEN mismatch_count >= 3 THEN '🔍 Investigate recent trades'
    ELSE '🟡 Monitor'
  END as status
FROM team_pair_mismatches;

