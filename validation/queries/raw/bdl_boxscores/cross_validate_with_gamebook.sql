-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/cross_validate_with_gamebook.sql
-- Purpose: Compare BDL stats against NBA.com official gamebook (source of truth)
-- Usage: Run weekly to verify data quality and identify discrepancies
-- ============================================================================
-- Expected Results:
--   - Most players should show "✅ Match" for all stats
--   - Points discrepancies are CRITICAL (affect prop settlement)
--   - Assists/rebounds discrepancies are concerning but less critical
--   - Missing players should be investigated
-- ============================================================================

WITH
-- Get BDL stats for active players only (those who played)
bdl_stats AS (
  SELECT
    game_date,
    game_id,
    player_lookup,
    player_full_name,
    team_abbr,
    points,
    assists,
    rebounds as total_rebounds
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND points IS NOT NULL
),

-- Get gamebook stats for players who actually played
gamebook_stats AS (
  SELECT
    game_date,
    game_id,
    player_lookup,
    player_name,
    team_abbr,
    points,
    assists,
    total_rebounds
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND player_status = 'ACTIVE'
    AND points IS NOT NULL
),

-- Full outer join to catch missing players in either source
comparison AS (
  SELECT
    COALESCE(b.game_date, g.game_date) as game_date,
    COALESCE(b.game_id, g.game_id) as game_id,
    COALESCE(b.player_lookup, g.player_lookup) as player_lookup,
    COALESCE(b.player_full_name, g.player_name) as player_name,
    COALESCE(b.team_abbr, g.team_abbr) as team_abbr,
    
    -- BDL stats
    b.points as bdl_points,
    b.assists as bdl_assists,
    b.total_rebounds as bdl_rebounds,
    
    -- Gamebook stats
    g.points as gamebook_points,
    g.assists as gamebook_assists,
    g.total_rebounds as gamebook_rebounds,
    
    -- Presence flags
    CASE
      WHEN b.player_lookup IS NOT NULL AND g.player_lookup IS NOT NULL THEN 'in_both'
      WHEN b.player_lookup IS NOT NULL THEN 'bdl_only'
      WHEN g.player_lookup IS NOT NULL THEN 'gamebook_only'
    END as presence_status
    
  FROM bdl_stats b
  FULL OUTER JOIN gamebook_stats g
    ON b.game_date = g.game_date
    AND b.game_id = g.game_id
    AND b.player_lookup = g.player_lookup
)

SELECT
  game_date,
  player_name,
  team_abbr,
  presence_status,
  bdl_points,
  gamebook_points,
  ABS(COALESCE(bdl_points, 0) - COALESCE(gamebook_points, 0)) as point_diff,
  bdl_assists,
  gamebook_assists,
  ABS(COALESCE(bdl_assists, 0) - COALESCE(gamebook_assists, 0)) as assist_diff,
  bdl_rebounds,
  gamebook_rebounds,
  ABS(COALESCE(bdl_rebounds, 0) - COALESCE(gamebook_rebounds, 0)) as rebound_diff,
  
  -- Issue severity
  CASE
    -- Critical issues (affect prop settlement)
    WHEN presence_status = 'gamebook_only' THEN '🔴 CRITICAL: Missing from BDL'
    WHEN presence_status = 'bdl_only' THEN '🟡 WARNING: Missing from Gamebook'
    WHEN ABS(COALESCE(bdl_points, 0) - COALESCE(gamebook_points, 0)) > 2 
      THEN '🔴 CRITICAL: Point discrepancy'
    
    -- Moderate issues
    WHEN ABS(COALESCE(bdl_assists, 0) - COALESCE(gamebook_assists, 0)) > 2 
      THEN '🟡 WARNING: Assist discrepancy'
    WHEN ABS(COALESCE(bdl_rebounds, 0) - COALESCE(gamebook_rebounds, 0)) > 2 
      THEN '🟡 WARNING: Rebound discrepancy'
    
    -- All stats match
    ELSE '✅ Match'
  END as issue_severity

FROM comparison

-- Show issues first, then perfect matches
ORDER BY
  CASE issue_severity
    WHEN '🔴 CRITICAL: Missing from BDL' THEN 1
    WHEN '🔴 CRITICAL: Point discrepancy' THEN 2
    WHEN '🟡 WARNING: Missing from Gamebook' THEN 3
    WHEN '🟡 WARNING: Assist discrepancy' THEN 4
    WHEN '🟡 WARNING: Rebound discrepancy' THEN 5
    ELSE 6
  END,
  game_date DESC,
  player_name;