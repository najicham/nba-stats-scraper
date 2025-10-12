-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/cross_validate_with_gamebook.sql
-- Purpose: Compare BDL box scores with NBA.com gamebook for data quality
-- Usage: Run to detect discrepancies between sources
-- ============================================================================
-- Instructions:
--   1. Update date range to check specific period
--   2. Adjust point_diff_threshold if needed (default: 2 points)
--   3. Results show players with stat discrepancies between sources
-- ============================================================================
-- Expected Results:
--   - Empty or minimal results = data sources agree
--   - Large point_diff = investigate scraper/processor issues
--   - Missing players = one source has incomplete data
-- ============================================================================

WITH
-- BDL data (active players only)
bdl_data AS (
  SELECT
    game_id,
    game_date,
    player_lookup,
    player_full_name as bdl_player_name,
    team_abbr,
    points as bdl_points,
    assists as bdl_assists,
    rebounds as bdl_rebounds,
    minutes as bdl_minutes
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()  -- UPDATE: Date range
),

-- NBA.com gamebook data (active players only)
gamebook_data AS (
  SELECT
    game_id,
    game_date,
    player_lookup,
    player_name as gamebook_player_name,
    team_abbr,
    points as gamebook_points,
    assists as gamebook_assists,
    rebounds as gamebook_rebounds,
    minutes as gamebook_minutes
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()  -- UPDATE: Match BDL range
    AND player_status = 'active'  -- Only active players (DNP excluded)
),

-- Join and compare
comparison AS (
  SELECT
    COALESCE(b.game_date, g.game_date) as game_date,
    COALESCE(b.game_id, g.game_id) as game_id,
    COALESCE(b.player_lookup, g.player_lookup) as player_lookup,
    COALESCE(b.bdl_player_name, g.gamebook_player_name) as player_name,
    COALESCE(b.team_abbr, g.team_abbr) as team_abbr,
    
    -- BDL stats
    b.bdl_points,
    b.bdl_assists,
    b.bdl_rebounds,
    b.bdl_minutes,
    
    -- Gamebook stats
    g.gamebook_points,
    g.gamebook_assists,
    g.gamebook_rebounds,
    g.gamebook_minutes,
    
    -- Differences
    ABS(COALESCE(b.bdl_points, 0) - COALESCE(g.gamebook_points, 0)) as point_diff,
    ABS(COALESCE(b.bdl_assists, 0) - COALESCE(g.gamebook_assists, 0)) as assist_diff,
    ABS(COALESCE(b.bdl_rebounds, 0) - COALESCE(g.gamebook_rebounds, 0)) as rebound_diff,
    
    -- Data presence flags
    CASE 
      WHEN b.player_lookup IS NULL THEN 'missing_from_bdl'
      WHEN g.player_lookup IS NULL THEN 'missing_from_gamebook'
      ELSE 'in_both'
    END as presence_status
    
  FROM bdl_data b
  FULL OUTER JOIN gamebook_data g
    ON b.game_id = g.game_id
    AND b.player_lookup = g.player_lookup
)

-- Report discrepancies
SELECT
  game_date,
  game_id,
  player_name,
  team_abbr,
  presence_status,
  
  -- Points comparison
  bdl_points,
  gamebook_points,
  point_diff,
  
  -- Assists comparison
  bdl_assists,
  gamebook_assists,
  assist_diff,
  
  -- Rebounds comparison
  bdl_rebounds,
  gamebook_rebounds,
  rebound_diff,
  
  -- Issue classification
  CASE
    WHEN presence_status = 'missing_from_bdl' THEN '🔴 CRITICAL: Missing from BDL'
    WHEN presence_status = 'missing_from_gamebook' THEN '🟡 WARNING: Missing from Gamebook'
    WHEN point_diff > 2 THEN '🔴 CRITICAL: Point discrepancy'
    WHEN assist_diff > 2 OR rebound_diff > 2 THEN '🟡 WARNING: Stat discrepancy'
    ELSE '✅ Match'
  END as issue_severity

FROM comparison
WHERE 
  -- Filter to only show issues
  presence_status != 'in_both'
  OR point_diff > 2
  OR assist_diff > 2
  OR rebound_diff > 2

ORDER BY 
  game_date DESC,
  point_diff DESC,
  player_name;
