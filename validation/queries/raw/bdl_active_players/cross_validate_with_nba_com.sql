-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/cross_validate_with_nba_com.sql
-- Purpose: Compare BDL active players against NBA.com player list
-- Usage: Run weekly to detect discrepancies between data sources
-- ============================================================================
-- Instructions:
--   1. Both sources should have similar player counts (~60-70% overlap expected)
--   2. Large discrepancies indicate data quality issues
--   3. Team mismatches highlight recent trades or roster moves
--   4. NOTE: BDL table NOT partitioned, NBA.com table IS partitioned
-- ============================================================================
-- Expected Results:
--   - ~60-70% validated players (both sources agree)
--   - ~20-30% BDL only (expected - G-League, two-way contracts, timing)
--   - ~10-20% NBA.com only (expected - BDL may be delayed)
--   - Team mismatches: ~10-20% (trades, roster timing differences)
-- ============================================================================

WITH
-- Get BDL active players (NOT partitioned - no filter needed)
bdl_players AS (
  SELECT
    player_lookup,
    player_full_name,
    team_abbr as bdl_team,
    validation_status as bdl_validation_status,
    has_validation_issues as bdl_has_issues,
    last_seen_date as bdl_last_seen
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
),

-- Get NBA.com current players (IS partitioned - filter required)
nbac_players AS (
  SELECT
    player_lookup,
    player_full_name,
    team_abbr as nbac_team,
    is_active as nbac_is_active,
    last_seen_date as nbac_last_seen
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024  -- Partition filter REQUIRED
),

-- Full outer join to find matches and mismatches
player_comparison AS (
  SELECT
    COALESCE(b.player_lookup, n.player_lookup) as player_lookup,
    COALESCE(b.player_full_name, n.player_full_name) as player_name,
    b.bdl_team,
    n.nbac_team,
    b.bdl_validation_status,
    b.bdl_has_issues,
    b.bdl_last_seen,
    n.nbac_is_active,
    n.nbac_last_seen,
    CASE
      WHEN b.player_lookup IS NOT NULL AND n.player_lookup IS NOT NULL THEN 'both_sources'
      WHEN b.player_lookup IS NOT NULL AND n.player_lookup IS NULL THEN 'bdl_only'
      WHEN b.player_lookup IS NULL AND n.player_lookup IS NOT NULL THEN 'nbac_only'
    END as source_presence,
    CASE
      WHEN b.player_lookup IS NOT NULL AND n.player_lookup IS NOT NULL AND b.bdl_team = n.nbac_team THEN 'teams_match'
      WHEN b.player_lookup IS NOT NULL AND n.player_lookup IS NOT NULL AND b.bdl_team != n.nbac_team THEN 'team_mismatch'
      ELSE 'single_source'
    END as team_match_status
  FROM bdl_players b
  FULL OUTER JOIN nbac_players n
    ON b.player_lookup = n.player_lookup
),

-- Calculate summary statistics
validation_summary AS (
  SELECT
    COUNT(*) as total_players,
    COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END) as in_both_sources,
    COUNT(CASE WHEN source_presence = 'bdl_only' THEN 1 END) as bdl_only_count,
    COUNT(CASE WHEN source_presence = 'nbac_only' THEN 1 END) as nbac_only_count,
    COUNT(CASE WHEN team_match_status = 'teams_match' THEN 1 END) as teams_match,
    COUNT(CASE WHEN team_match_status = 'team_mismatch' THEN 1 END) as team_mismatch_count,
    ROUND(100.0 * COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END) / COUNT(*), 1) as pct_in_both,
    ROUND(100.0 * COUNT(CASE WHEN team_match_status = 'teams_match' THEN 1 END) / NULLIF(COUNT(CASE WHEN source_presence = 'both_sources' THEN 1 END), 0), 1) as pct_teams_match
  FROM player_comparison
)

-- Output: Summary then details
SELECT
  '=== CROSS-VALIDATION SUMMARY ===' as section,
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
  'BDL + NBA.com' as metric,
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
  'BDL Only' as section,
  'Missing from NBA.com' as metric,
  CAST(bdl_only_count AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 * bdl_only_count / total_players, 1) AS STRING), '%') as percentage,
  CASE
    WHEN bdl_only_count < total_players * 0.30 THEN '✅ Expected (G-League, two-way)'
    WHEN bdl_only_count < total_players * 0.40 THEN '🟡 High but acceptable'
    ELSE '🔴 Too many missing from NBA.com'
  END as status
FROM validation_summary

UNION ALL

SELECT
  'NBA.com Only' as section,
  'Missing from BDL' as metric,
  CAST(nbac_only_count AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 * nbac_only_count / total_players, 1) AS STRING), '%') as percentage,
  CASE
    WHEN nbac_only_count < total_players * 0.20 THEN '✅ Expected (timing differences)'
    WHEN nbac_only_count < total_players * 0.30 THEN '🟡 BDL may be delayed'
    ELSE '🔴 Investigate BDL scraper'
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
    WHEN pct_teams_match >= 80 THEN '✅ Excellent'
    WHEN pct_teams_match >= 70 THEN '🟡 Good - review mismatches'
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
    WHEN team_mismatch_count <= in_both_sources * 0.20 THEN '✅ Normal (trade timing)'
    WHEN team_mismatch_count <= in_both_sources * 0.30 THEN '🟡 Review - recent trades?'
    ELSE '🔴 Excessive mismatches'
  END as status
FROM validation_summary;
