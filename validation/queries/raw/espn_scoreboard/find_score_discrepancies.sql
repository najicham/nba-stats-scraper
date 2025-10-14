-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/find_score_discrepancies.sql
-- Purpose: Identify specific games with score discrepancies across sources
-- Usage: Three-way comparison (ESPN vs BDL vs NBA.com) to find data issues
-- ============================================================================
-- Expected Results:
--   - Most games should agree across all 3 sources
--   - Any discrepancy requires investigation (possible data corruption)
--   - Priority: ESPN vs NBA.com (both should be official)
-- ============================================================================

WITH 
-- ESPN scores
espn_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_team_score as espn_home,
    away_team_score as espn_away,
    espn_game_id,
    scrape_timestamp as espn_scraped
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND is_completed = TRUE
),

-- BDL scores
bdl_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_team_score as bdl_home,
    away_team_score as bdl_away
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY game_id, game_date, home_team_abbr, away_team_abbr,
           home_team_score, away_team_score
),

-- NBA.com Scoreboard V2
nbac_scores AS (
  SELECT 
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    home_score as nbac_home,
    away_score as nbac_away
  FROM `nba-props-platform.nba_raw.nbac_scoreboard_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND game_state = 'post'
),

-- Three-way join
comparison AS (
  SELECT 
    COALESCE(e.game_id, b.game_id, n.game_id) as game_id,
    COALESCE(e.game_date, b.game_date, n.game_date) as game_date,
    COALESCE(e.home_team_abbr, b.home_team_abbr, n.home_team_abbr) as home_team,
    COALESCE(e.away_team_abbr, b.away_team_abbr, n.away_team_abbr) as away_team,
    e.espn_home,
    e.espn_away,
    b.bdl_home,
    b.bdl_away,
    n.nbac_home,
    n.nbac_away,
    e.espn_game_id,
    
    -- Source presence flags
    CASE WHEN e.game_id IS NOT NULL THEN 1 ELSE 0 END as has_espn,
    CASE WHEN b.game_id IS NOT NULL THEN 1 ELSE 0 END as has_bdl,
    CASE WHEN n.game_id IS NOT NULL THEN 1 ELSE 0 END as has_nbac,
    
    -- Discrepancy detection
    CASE
      WHEN e.espn_home IS NULL OR b.bdl_home IS NULL OR n.nbac_home IS NULL THEN NULL
      WHEN e.espn_home = b.bdl_home AND b.bdl_home = n.nbac_home THEN 'PERFECT'
      WHEN e.espn_home = n.nbac_home AND e.espn_home != b.bdl_home THEN 'BDL_DIFFERS'
      WHEN e.espn_home != n.nbac_home THEN 'ESPN_NBAC_DIFFER'
      ELSE 'COMPLEX'
    END as discrepancy_type,
    
    -- Calculate max difference
    GREATEST(
      ABS(COALESCE(e.espn_home, 0) - COALESCE(b.bdl_home, 0)),
      ABS(COALESCE(e.espn_home, 0) - COALESCE(n.nbac_home, 0)),
      ABS(COALESCE(b.bdl_home, 0) - COALESCE(n.nbac_home, 0)),
      ABS(COALESCE(e.espn_away, 0) - COALESCE(b.bdl_away, 0)),
      ABS(COALESCE(e.espn_away, 0) - COALESCE(n.nbac_away, 0)),
      ABS(COALESCE(b.bdl_away, 0) - COALESCE(n.nbac_away, 0))
    ) as max_diff
  FROM espn_scores e
  FULL OUTER JOIN bdl_scores b ON e.game_id = b.game_id
  FULL OUTER JOIN nbac_scores n ON e.game_id = n.game_id
),

-- Summary statistics
summary AS (
  SELECT
    COUNT(*) as total_games,
    SUM(has_espn) as games_in_espn,
    SUM(has_bdl) as games_in_bdl,
    SUM(has_nbac) as games_in_nbac,
    SUM(CASE WHEN has_espn = 1 AND has_bdl = 1 AND has_nbac = 1 THEN 1 ELSE 0 END) as in_all_three,
    COUNT(CASE WHEN discrepancy_type = 'PERFECT' THEN 1 END) as perfect_matches,
    COUNT(CASE WHEN discrepancy_type IS NOT NULL AND discrepancy_type != 'PERFECT' THEN 1 END) as has_discrepancies,
    COUNT(CASE WHEN discrepancy_type = 'ESPN_NBAC_DIFFER' THEN 1 END) as espn_vs_nbac_issues
  FROM comparison
)

-- Output: Combined results with proper BigQuery syntax
(
  SELECT 
    '📊 3-WAY SUMMARY (Last 90 Days)' as section,
    CAST(total_games AS STRING) as col1,
    CAST(in_all_three AS STRING) as col2,
    CAST(perfect_matches AS STRING) as col3,
    CAST(has_discrepancies AS STRING) as col4,
    CAST(espn_vs_nbac_issues AS STRING) as col5,
    CASE
      WHEN espn_vs_nbac_issues > 0 THEN '🔴 CRITICAL - ESPN vs NBA.com differ'
      WHEN has_discrepancies > 0 THEN '⚠️ Minor issues'
      ELSE '✅ All sources agree'
    END as status,
    1 as sort_order,
    0 as subsort
  FROM summary

  UNION ALL

  -- Output: Critical discrepancies (ESPN vs NBA.com official sources)
  SELECT 
    '🔴 CRITICAL DISCREPANCIES' as section,
    game_id as col1,
    CONCAT(away_team, ' @ ', home_team) as col2,
    CONCAT('ESPN: ', espn_away, '-', espn_home) as col3,
    CONCAT('NBAC: ', nbac_away, '-', nbac_home) as col4,
    CONCAT('Max Δ: ', max_diff) as col5,
    CONCAT('Date: ', game_date) as status,
    2 as sort_order,
    max_diff as subsort
  FROM comparison
  WHERE discrepancy_type = 'ESPN_NBAC_DIFFER'

  UNION ALL

  -- Output: BDL differs (less critical)
  SELECT 
    '⚠️ BDL DIFFERS' as section,
    game_id as col1,
    CONCAT(away_team, ' @ ', home_team) as col2,
    CONCAT('ESPN/NBAC: ', espn_away, '-', espn_home) as col3,
    CONCAT('BDL: ', bdl_away, '-', bdl_home) as col4,
    CONCAT('Max Δ: ', max_diff) as col5,
    CONCAT('Date: ', game_date) as status,
    3 as sort_order,
    max_diff as subsort
  FROM comparison
  WHERE discrepancy_type = 'BDL_DIFFERS'
    AND max_diff > 0

  UNION ALL

  -- Output: Coverage analysis
  SELECT 
    '📋 COVERAGE' as section,
    CONCAT('ESPN: ', games_in_espn) as col1,
    CONCAT('BDL: ', games_in_bdl) as col2,
    CONCAT('NBAC: ', games_in_nbac) as col3,
    CONCAT('All 3: ', in_all_three) as col4,
    CONCAT('Perfect: ', perfect_matches) as col5,
    CASE
      WHEN CAST(games_in_espn AS FLOAT64) / NULLIF(games_in_nbac, 0) < 0.3 THEN '⚪ Sparse ESPN (backup)'
      ELSE '✅ Good'
    END as status,
    4 as sort_order,
    0 as subsort
  FROM summary
)
ORDER BY sort_order, subsort DESC;
