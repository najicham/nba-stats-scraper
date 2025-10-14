-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/cross_validate_with_nbac.sql
-- Purpose: Cross-validate ESPN scores vs NBA.com Scoreboard V2 (official)
-- Usage: Compare backup source vs official NBA.com game results
-- ============================================================================
-- Expected Results:
--   - Perfect matches expected (both should reflect official scores)
--   - Any mismatch indicates data quality issue needing investigation
--   - ESPN may have fewer games (backup collection pattern)
-- ============================================================================

WITH 
-- ESPN scores
espn_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_team_score as espn_home_score,
    away_team_score as espn_away_score,
    is_completed as espn_completed,
    game_status as espn_status
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND is_completed = TRUE
),

-- NBA.com Scoreboard V2 scores
nbac_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_score as nbac_home_score,
    away_score as nbac_away_score,
    game_state as nbac_status
  FROM `nba-props-platform.nba_raw.nbac_scoreboard_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND game_state = 'post'  -- Completed games only
),

-- Full outer join to find coverage differences
comparison AS (
  SELECT 
    COALESCE(e.game_id, n.game_id) as game_id,
    COALESCE(e.game_date, n.game_date) as game_date,
    COALESCE(e.home_team_abbr, n.home_team_abbr) as home_team,
    COALESCE(e.away_team_abbr, n.away_team_abbr) as away_team,
    e.espn_home_score,
    e.espn_away_score,
    n.nbac_home_score,
    n.nbac_away_score,
    ABS(COALESCE(e.espn_home_score, 0) - COALESCE(n.nbac_home_score, 0)) as home_diff,
    ABS(COALESCE(e.espn_away_score, 0) - COALESCE(n.nbac_away_score, 0)) as away_diff,
    CASE
      WHEN e.game_id IS NULL THEN 'NBAC_ONLY'
      WHEN n.game_id IS NULL THEN 'ESPN_ONLY'
      ELSE 'BOTH'
    END as source_status
  FROM espn_scores e
  FULL OUTER JOIN nbac_scores n
    ON e.game_id = n.game_id
),

-- Summary statistics
summary AS (
  SELECT
    COUNT(*) as total_games,
    COUNT(CASE WHEN source_status = 'BOTH' THEN 1 END) as both_sources,
    COUNT(CASE WHEN source_status = 'ESPN_ONLY' THEN 1 END) as espn_only,
    COUNT(CASE WHEN source_status = 'NBAC_ONLY' THEN 1 END) as nbac_only,
    COUNT(CASE WHEN source_status = 'BOTH' AND home_diff = 0 AND away_diff = 0 THEN 1 END) as perfect_matches,
    COUNT(CASE WHEN source_status = 'BOTH' AND (home_diff > 0 OR away_diff > 0) THEN 1 END) as mismatches,
    AVG(CASE WHEN source_status = 'BOTH' THEN GREATEST(home_diff, away_diff) END) as avg_max_diff
  FROM comparison
)

-- Output: Combined results with proper BigQuery syntax
(
  SELECT 
    '📊 SUMMARY (Last 30 Days)' as section,
    CAST(total_games AS STRING) as col1,
    CAST(both_sources AS STRING) as col2,
    CAST(perfect_matches AS STRING) as col3,
    CAST(mismatches AS STRING) as col4,
    CAST(ROUND(avg_max_diff, 2) AS STRING) as col5,
    CAST(espn_only AS STRING) as col6,
    CAST(nbac_only AS STRING) as col7,
    CASE
      WHEN mismatches > 0 THEN '🔴 CRITICAL - Investigate'
      WHEN nbac_only > both_sources * 0.5 THEN '⚠️ Low ESPN coverage'
      ELSE '✅ Good validation'
    END as status,
    1 as sort_order,
    0 as subsort
  FROM summary

  UNION ALL

  -- Output: Score mismatches (critical errors) - Top 10 only
  SELECT 
    '🔴 SCORE MISMATCHES' as section,
    game_id as col1,
    CONCAT(away_team, ' @ ', home_team) as col2,
    CONCAT('ESPN: ', espn_away_score, '-', espn_home_score) as col3,
    CONCAT('NBAC: ', nbac_away_score, '-', nbac_home_score) as col4,
    CONCAT('Δ Home: ', home_diff, ' Away: ', away_diff) as col5,
    '' as col6,
    CAST(game_date AS STRING) as col7,
    '🔴 DATA QUALITY ISSUE' as status,
    2 as sort_order,
    GREATEST(home_diff, away_diff) as subsort
  FROM comparison
  WHERE source_status = 'BOTH'
    AND (home_diff > 0 OR away_diff > 0)

  UNION ALL

  -- Output: Coverage analysis
  SELECT 
    '📋 COVERAGE ANALYSIS' as section,
    CAST(COUNT(*) AS STRING) as col1,
    source_status as col2,
    CONCAT('Games: ', COUNT(*)) as col3,
    '' as col4,
    '' as col5,
    '' as col6,
    '' as col7,
    CASE source_status
      WHEN 'BOTH' THEN '✅ Both sources'
      WHEN 'NBAC_ONLY' THEN '⚪ Missing from ESPN (backup)'
      WHEN 'ESPN_ONLY' THEN '⚠️ Missing from NBA.com'
    END as status,
    3 as sort_order,
    0 as subsort
  FROM comparison
  GROUP BY source_status
)
ORDER BY sort_order, subsort DESC;
