-- ============================================================================
-- File: validation/queries/raw/bdl_active_players/validation_status_summary.sql
-- Purpose: Analyze validation_status distribution (UNIQUE TO BDL)
-- Usage: Run daily to monitor cross-validation intelligence
-- ============================================================================
-- Instructions:
--   1. Expected distribution: ~60% validated, ~25% missing_nba_com, ~15% team_mismatch
--   2. High 'data_quality_issue' count requires investigation
--   3. Per-team validation rates help identify problem areas
-- ============================================================================
-- Expected Results:
--   - validated: 55-65% (both sources agree)
--   - missing_nba_com: 20-30% (G-League, two-way contracts expected)
--   - team_mismatch: 10-20% (trades, roster timing differences)
--   - data_quality_issue: <5% (investigate if higher)
-- ============================================================================

WITH
-- Overall validation status distribution
validation_distribution AS (
  SELECT
    validation_status,
    COUNT(*) as player_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as percentage,
    STRING_AGG(player_full_name ORDER BY player_full_name LIMIT 5) as sample_players
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  GROUP BY validation_status
),

-- Per-team validation rates
team_validation AS (
  SELECT
    team_abbr,
    team_full_name,
    COUNT(*) as total_players,
    COUNT(CASE WHEN validation_status = 'validated' THEN 1 END) as validated_count,
    COUNT(CASE WHEN validation_status = 'missing_nba_com' THEN 1 END) as missing_count,
    COUNT(CASE WHEN validation_status = 'team_mismatch' THEN 1 END) as mismatch_count,
    COUNT(CASE WHEN validation_status = 'data_quality_issue' THEN 1 END) as quality_issue_count,
    ROUND(100.0 * COUNT(CASE WHEN validation_status = 'validated' THEN 1 END) / COUNT(*), 1) as pct_validated
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
  GROUP BY team_abbr, team_full_name
),

-- Overall summary stats
summary_stats AS (
  SELECT
    COUNT(*) as total_players,
    COUNT(DISTINCT team_abbr) as total_teams,
    COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) as no_issues,
    COUNT(CASE WHEN has_validation_issues = TRUE THEN 1 END) as has_issues,
    ROUND(100.0 * COUNT(CASE WHEN has_validation_issues = FALSE THEN 1 END) / COUNT(*), 1) as pct_no_issues
  FROM `nba-props-platform.nba_raw.bdl_active_players_current`
)

-- Output: Validation status analysis
SELECT
  '=== VALIDATION STATUS DISTRIBUTION ===' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  validation_status as section,
  CASE validation_status
    WHEN 'validated' THEN 'Both sources agree perfectly'
    WHEN 'missing_nba_com' THEN 'Not in NBA.com (G-League, two-way?)'
    WHEN 'team_mismatch' THEN 'Different teams (trade timing?)'
    WHEN 'data_quality_issue' THEN 'Data problems detected'
    ELSE 'Unknown status'
  END as metric,
  CAST(player_count AS STRING) as count,
  CONCAT(CAST(percentage AS STRING), '%') as percentage,
  CASE validation_status
    WHEN 'validated' THEN
      CASE
        WHEN percentage >= 55 AND percentage <= 65 THEN '✅ Healthy'
        WHEN percentage >= 45 AND percentage <= 75 THEN '🟡 Acceptable'
        ELSE '🔴 Low validation rate'
      END
    WHEN 'missing_nba_com' THEN
      CASE
        WHEN percentage <= 30 THEN '✅ Expected (G-League, two-way)'
        WHEN percentage <= 40 THEN '🟡 High but acceptable'
        ELSE '🔴 Too many missing from NBA.com'
      END
    WHEN 'team_mismatch' THEN
      CASE
        WHEN percentage <= 20 THEN '✅ Normal (trade timing)'
        WHEN percentage <= 30 THEN '🟡 Review recent trades'
        ELSE '🔴 Excessive mismatches'
      END
    WHEN 'data_quality_issue' THEN
      CASE
        WHEN percentage <= 5 THEN '✅ Minimal issues'
        WHEN percentage <= 10 THEN '🟡 Investigate'
        ELSE '🔴 CRITICAL: Data problems'
      END
    ELSE '❓ Unknown'
  END as status
FROM validation_distribution

UNION ALL

SELECT
  '' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  '=== OVERALL SUMMARY ===' as section,
  '' as metric,
  '' as count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Total Players' as section,
  '' as metric,
  CAST(total_players AS STRING) as count,
  CONCAT(CAST(total_teams AS STRING), ' teams') as percentage,
  '' as status
FROM summary_stats

UNION ALL

SELECT
  'No Validation Issues' as section,
  'has_validation_issues = FALSE' as metric,
  CAST(no_issues AS STRING) as count,
  CONCAT(CAST(pct_no_issues AS STRING), '%') as percentage,
  CASE
    WHEN pct_no_issues >= 55 THEN '✅ Healthy'
    WHEN pct_no_issues >= 45 THEN '🟡 Acceptable'
    ELSE '🔴 Investigate'
  END as status
FROM summary_stats

UNION ALL

SELECT
  'Has Validation Issues' as section,
  'has_validation_issues = TRUE' as metric,
  CAST(has_issues AS STRING) as count,
  CONCAT(CAST(ROUND(100.0 - pct_no_issues, 1) AS STRING), '%') as percentage,
  CASE
    WHEN has_issues <= total_players * 0.45 THEN '✅ Expected'
    ELSE '🟡 High'
  END as status
FROM summary_stats;
