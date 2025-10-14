-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/missing_players_analysis.sql
-- Purpose: Deep dive into validation_status = 'missing_nba_com' cases
-- Usage: Run when missing rate is high (>30%) to investigate
-- ============================================================================
-- Instructions:
--   1. Shows players in BDL but NOT in NBA.com
--   2. Expected: G-League players, two-way contracts, recent signings
--   3. Parse validation_details for specific reasons
-- ============================================================================
-- Expected Results:
--   - ~20-30% of players should be missing from NBA.com
--   - Common causes: G-League assignments, two-way contracts, recent signings
--   - Some teams may have higher rates (heavy G-League usage)
-- ============================================================================

WITH
-- Get all missing from NBA.com cases
missing_players AS (
  SELECT
    player_lookup,
    player_full_name,
    first_name,
    last_name,
    team_abbr as bdl_team,
    team_full_name as bdl_team_name,
    bdl_player_id,
    position,
    height,
    weight,
    validation_status,
    validation_details,
    last_seen_date,
    processed_at
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  WHERE validation_status = 'missing_nba_com'
),

-- Missing counts by team
team_missing_counts AS (
  SELECT
    bdl_team,
    bdl_team_name,
    COUNT(*) as missing_count,
    STRING_AGG(player_full_name ORDER BY player_full_name LIMIT 8) as sample_players
  FROM missing_players
  GROUP BY bdl_team, bdl_team_name
),

-- Missing by position
position_distribution AS (
  SELECT
    COALESCE(position, 'Unknown') as position,
    COUNT(*) as missing_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_missing
  FROM missing_players
  GROUP BY position
),

-- Overall stats
overall_stats AS (
  SELECT
    COUNT(*) as total_missing,
    COUNT(DISTINCT bdl_team) as teams_with_missing,
    COUNT(DISTINCT position) as positions_represented,
    MAX(last_seen_date) as most_recent_update,
    MIN(last_seen_date) as oldest_update,
    (SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_active_players_current`) as total_bdl_players
  FROM missing_players
)

-- Output: Missing players analysis
SELECT
  '=== MISSING FROM NBA.COM SUMMARY ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  'Total Missing' as section,
  '' as metric,
  CONCAT(CAST(total_missing AS STRING), ' of ', CAST(total_bdl_players AS STRING)) as count,
  CONCAT(CAST(ROUND(100.0 * total_missing / total_bdl_players, 1) AS STRING), '%') as details,
  CASE
    WHEN ROUND(100.0 * total_missing / total_bdl_players, 1) <= 30 THEN '✅ Expected (G-League, two-way)'
    WHEN ROUND(100.0 * total_missing / total_bdl_players, 1) <= 40 THEN '🟡 High but acceptable'
    ELSE '🔴 Too many missing from NBA.com'
  END as status
FROM overall_stats

UNION ALL

SELECT
  'Teams Affected' as section,
  '' as metric,
  CONCAT(CAST(teams_with_missing AS STRING), ' of 30') as count,
  '' as details,
  CASE
    WHEN teams_with_missing >= 25 THEN '✅ Widespread (expected)'
    WHEN teams_with_missing >= 20 THEN '🟡 Moderate'
    ELSE '🔴 Investigate - should be more teams'
  END as status
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
  '=== COMMON REASONS ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  'Expected Reasons' as section,
  '1. G-League assignments (two-way contracts)' as metric,
  '' as count,
  'Players on NBA roster but currently in G-League' as details,
  '✅ Normal' as status

UNION ALL

SELECT
  '' as section,
  '2. Recent signings or call-ups' as metric,
  '' as count,
  'BDL updates faster than NBA.com sometimes' as details,
  '✅ Normal' as status

UNION ALL

SELECT
  '' as section,
  '3. Timing differences between sources' as metric,
  '' as count,
  'Scrapers run at different times' as details,
  '✅ Normal' as status

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  '=== TEAMS WITH MOST MISSING PLAYERS ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  bdl_team as section,
  bdl_team_name as metric,
  CAST(missing_count AS STRING) as count,
  sample_players as details,
  CASE
    WHEN missing_count >= 8 THEN '🟡 High (heavy G-League usage?)'
    WHEN missing_count >= 5 THEN '🟡 Moderate'
    ELSE '✅ Low'
  END as status
FROM team_missing_counts

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  '=== POSITION DISTRIBUTION ===' as section,
  '' as metric,
  '' as count,
  '' as details,
  '' as status

UNION ALL

SELECT
  position as section,
  'Missing players by position' as metric,
  CAST(missing_count AS STRING) as count,
  CONCAT(CAST(pct_of_missing AS STRING), '% of missing') as details,
  '📊 Distribution' as status
FROM position_distribution;
