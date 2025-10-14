-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/cross_validate_with_bdl.sql
-- Purpose: Cross-validate ESPN scores vs Ball Don't Lie box scores
-- Usage: Detect scoring discrepancies between backup and primary sources
-- ============================================================================
-- Expected Results:
--   - Most games should match exactly (score difference = 0)
--   - Flag any games with score mismatches >2 points (data quality issue)
--   - Report games in ESPN but missing from BDL (and vice versa)
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
    is_completed as espn_completed
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND is_completed = TRUE
),

-- BDL scores (aggregate from player box scores)
bdl_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_team_score as bdl_home_score,
    away_team_score as bdl_away_score
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_id, game_date, home_team_abbr, away_team_abbr, 
           home_team_score, away_team_score
),

-- Full outer join to find all games
comparison AS (
  SELECT 
    COALESCE(e.game_id, b.game_id) as game_id,
    COALESCE(e.game_date, b.game_date) as game_date,
    COALESCE(e.home_team_abbr, b.home_team_abbr) as home_team,
    COALESCE(e.away_team_abbr, b.away_team_abbr) as away_team,
    e.espn_home_score,
    e.espn_away_score,
    b.bdl_home_score,
    b.bdl_away_score,
    ABS(COALESCE(e.espn_home_score, 0) - COALESCE(b.bdl_home_score, 0)) as home_diff,
    ABS(COALESCE(e.espn_away_score, 0) - COALESCE(b.bdl_away_score, 0)) as away_diff,
    CASE
      WHEN e.game_id IS NULL THEN 'BDL_ONLY'
      WHEN b.game_id IS NULL THEN 'ESPN_ONLY'
      ELSE 'BOTH'
    END as source_status
  FROM espn_scores e
  FULL OUTER JOIN bdl_scores b
    ON e.game_id = b.game_id
),

-- Summary statistics
summary AS (
  SELECT
    COUNT(*) as total_games,
    COUNT(CASE WHEN source_status = 'BOTH' THEN 1 END) as both_sources,
    COUNT(CASE WHEN source_status = 'ESPN_ONLY' THEN 1 END) as espn_only,
    COUNT(CASE WHEN source_status = 'BDL_ONLY' THEN 1 END) as bdl_only,
    COUNT(CASE WHEN source_status = 'BOTH' AND home_diff = 0 AND away_diff = 0 THEN 1 END) as perfect_matches,
    COUNT(CASE WHEN source_status = 'BOTH' AND (home_diff > 0 OR away_diff > 0) THEN 1 END) as mismatches,
    COUNT(CASE WHEN source_status = 'BOTH' AND (home_diff > 2 OR away_diff > 2) THEN 1 END) as major_mismatches
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
    CAST(major_mismatches AS STRING) as col5,
    CAST(espn_only AS STRING) as col6,
    CAST(bdl_only AS STRING) as col7,
    CASE
      WHEN major_mismatches > 0 THEN '🔴 INVESTIGATE'
      WHEN mismatches > 0 THEN '⚠️ Minor diffs'
      ELSE '✅ All match'
    END as status,
    1 as sort_order,
    0 as subsort
  FROM summary

  UNION ALL

  -- Output: Score mismatches (any difference)
  SELECT 
    '⚠️ SCORE DIFFERENCES' as section,
    game_id as col1,
    CONCAT(away_team, ' @ ', home_team) as col2,
    CONCAT('ESPN: ', espn_away_score, '-', espn_home_score) as col3,
    CONCAT('BDL: ', bdl_away_score, '-', bdl_home_score) as col4,
    CONCAT('Δ: ', home_diff, ' / ', away_diff) as col5,
    '' as col6,
    CAST(game_date AS STRING) as col7,
    CASE
      WHEN home_diff > 2 OR away_diff > 2 THEN '🔴 MAJOR'
      ELSE '⚠️ MINOR'
    END as status,
    2 as sort_order,
    GREATEST(home_diff, away_diff) as subsort
  FROM comparison
  WHERE source_status = 'BOTH'
    AND (home_diff > 0 OR away_diff > 0)
  LIMIT 20
)
ORDER BY sort_order, subsort DESC;