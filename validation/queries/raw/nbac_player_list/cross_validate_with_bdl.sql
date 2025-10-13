-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/cross_validate_with_bdl.sql
-- Purpose: Compare NBA.com player list against Ball Don't Lie active players
-- Usage: Run weekly to detect discrepancies between data sources
-- ============================================================================
-- Instructions:
--   1. Both sources should have similar player counts (~60-70% overlap expected)
--   2. Large discrepancies indicate data quality issues
--   3. Team mismatches highlight recent trades or roster moves
-- ============================================================================
-- Expected Results:
--   - ~60-70% validated players (both sources agree)
--   - ~15-20% NBA.com only (expected - more comprehensive)
--   - ~10-15% BDL only (expected - timing differences)
--   - Team mismatches: ~5-10% (trades, roster moves)
-- ============================================================================

WITH
-- Get NBA.com current players
nbac_players AS (
  SELECT
    player_lookup,
    player_full_name,
    team_abbr as nbac_team,
    is_active as nbac_is_active,
    last_seen_date as nbac_last_seen
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
),

-- Get Ball Don't Lie active players
bdl_players AS (
  SELECT
    player_lookup,
    player_full_name,
    team_abbr as bdl_team,
    validation_status as bdl_validation_status,
    last_seen_date as bdl_last_seen
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Full outer join to find matches and mismatches
player_comparison AS (
  SELECT
    COALESCE(n.player_lookup, b.player_lookup) as player_lookup,
    COALESCE(n.player_full_name, b.player_full_name) as player_name,
    n.nbac_team,
    b.bdl_team,
    n.nbac_is_active,
    n.nbac_last_seen,
    b.bdl_last_seen,
    b.bdl_validation_status,
    CASE
      WHEN n.player_lookup IS NOT NULL AND b.player_lookup IS NOT NULL THEN 'both_sources'
      WHEN n.player_lookup IS NOT NULL AND b.player_lookup IS NULL THEN 'nbac_only'
      WHEN n.player_lookup IS NULL AND b.player_lookup IS NOT NULL THEN 'bdl_only'
    END as source_presence,
    CASE
      WHEN n.player_lookup IS NOT NULL AND b.player_lookup IS NOT NULL AND n.nbac_team = b.bdl_team THEN 'teams_match'
      WHEN n.player_lookup IS NOT NULL AND b.player_lookup IS NOT NULL AND n.nbac_team != b.bdl_team THEN 'team_mismatch'
      ELSE 'single_source'
    END as team_match_status
  FROM nbac_players n
  FULL OUTER JOIN bdl_players b
    ON n.player_lookup = b.player_lookup
),

-- Calculate summary statistics
validation_summary AS (
  SELECT
    COUNT(*) as total_players,
    COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END) as in_both_sources,
    COUNT(CASE WHEN source_presence = 'nbac_only' THEN 1 END) as nbac_only_count,
    COUNT(CASE WHEN source_presence = 'bdl_only' THEN 1 END) as bdl_only_count,
    COUNT(CASE WHEN team_match_status = 'teams_match' THEN 1 END) as teams_match,
    COUNT(CASE WHEN team_match_status = 'team_mismatch' THEN 1 END) as team_mismatch_count,
    ROUND(100.0 * COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END) / COUNT(*), 1) as pct_in_both,
    ROUND(100.0 * COUNT(CASE WHEN team_match_status = 'teams_match' THEN 1 END) / NULLIF(COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END), 0), 1) as pct_teams_match
  FROM player_comparison
)

-- Output: Summary then details
SELECT
  '=== VALIDATION SUMMARY ===' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Total Unique Players' as section,
  '' as metric,
  CAST(total_players AS STRING) as count,
  '100%' as percentage,
  '' as status
FROM validation_summary

UNION ALL

SELECT
  'In Both Sources' as section,
  'NBA.com + BDL' as metric,
  CAST(in_both_sources AS STRING) as count,
  CONCAT(CAST(pct_in_both AS STRING), '%') as percentage,
  CASE
    WHEN pct_in_both >= 60 THEN '✅ Good overlap'
    WHEN pct_in_both >= 50 THEN '🟡 Moderate overlap'
    ELSE '🔴 Low overlap'
  END as status
FROM validation_summary

UNION ALL

SELECT
  'NBA.com Only' as section,
  'Missing from BDL' as metric,
  CAST(nbac_only_count AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 * nbac_only_count / total_players, 1) AS STRING), '%') as percentage,
  CASE
    WHEN nbac_only_count < total_players * 0.30 THEN '✅ Expected'
    ELSE '🟡 High - investigate'
  END as status
FROM validation_summary

UNION ALL

SELECT
  'BDL Only' as section,
  'Missing from NBA.com' as metric,
  CAST(bdl_only_count AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 * bdl_only_count / total_players, 1) AS STRING), '%') as percentage,
  CASE
    WHEN bdl_only_count < total_players * 0.20 THEN '✅ Expected'
    ELSE '🟡 High - investigate'
  END as status
FROM validation_summary

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  '=== TEAM MATCHING ===' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Teams Match' as section,
  'Same team in both sources' as metric,
  CAST(teams_match AS STRING) as count,
  CONCAT(CAST(pct_teams_match AS STRING), '%') as percentage,
  CASE
    WHEN pct_teams_match >= 90 THEN '✅ Excellent'
    WHEN pct_teams_match >= 80 THEN '🟡 Good'
    ELSE '🔴 Investigate mismatches'
  END as status
FROM validation_summary

UNION ALL

SELECT
  'Team Mismatches' as section,
  'Different teams (trades?)' as metric,
  CAST(team_mismatch_count AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 * team_mismatch_count / NULLIF(in_both_sources, 0), 1) AS STRING), '%') as percentage,
  CASE
    WHEN team_mismatch_count <= in_both_sources * 0.10 THEN '✅ Normal'
    ELSE '🟡 Review - recent trades?'
  END as status
FROM validation_summary

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  '=== TEAM MISMATCHES (Top 10) ===' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  player_name as section,
  player_lookup as metric,
  CONCAT('NBA.com: ', COALESCE(nbac_team, 'N/A')) as count,
  CONCAT('BDL: ', COALESCE(bdl_team, 'N/A')) as percentage,
  '🔍 Review' as status
FROM player_comparison
WHERE team_match_status = 'team_mismatch'
ORDER BY player_name
LIMIT 10;
