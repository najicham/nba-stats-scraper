-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/check_recent_espn_data.sql
-- ============================================================================
-- ESPN Boxscore: Detailed Recent Data Check
-- Purpose: Validate recently scraped ESPN data with comparison to BDL
-- ============================================================================

WITH espn_recent AS (
  SELECT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as player_count,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT team_abbr) as team_count,
    SUM(points) as total_points,
    MAX(points) as max_points,
    AVG(points) as avg_points,
    -- Check for data quality issues
    COUNT(CASE WHEN points IS NULL THEN 1 END) as null_points,
    COUNT(CASE WHEN minutes = '0:00' THEN 1 END) as dnp_count
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
),

bdl_recent AS (
  SELECT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as bdl_player_count,
    COUNT(DISTINCT player_lookup) as bdl_unique_players
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
),

comparison AS (
  SELECT
    COALESCE(e.game_date, b.game_date) as game_date,
    COALESCE(e.game_id, b.game_id) as game_id,
    COALESCE(e.home_team_abbr, b.home_team_abbr) as home_team,
    COALESCE(e.away_team_abbr, b.away_team_abbr) as away_team,
    
    -- ESPN data
    e.player_count as espn_players,
    e.unique_players as espn_unique,
    e.team_count as espn_teams,
    e.total_points as espn_total_pts,
    e.max_points as espn_max_pts,
    e.null_points as espn_null_pts,
    e.dnp_count as espn_dnp,
    
    -- BDL data
    b.bdl_player_count as bdl_players,
    b.bdl_unique_players as bdl_unique,
    
    -- Comparison flags
    CASE
      WHEN e.game_id IS NOT NULL AND b.game_id IS NULL THEN 'ESPN_ONLY'
      WHEN e.game_id IS NULL AND b.game_id IS NOT NULL THEN 'BDL_ONLY'
      ELSE 'BOTH'
    END as source_status,
    
    -- Quality assessment
    CASE
      WHEN e.player_count IS NOT NULL AND e.player_count < 20 THEN '⚠️ Low player count'
      WHEN e.player_count IS NOT NULL AND e.player_count > 35 THEN '⚠️ High player count'
      WHEN e.team_count IS NOT NULL AND e.team_count != 2 THEN '🔴 Wrong team count'
      WHEN e.null_points IS NOT NULL AND e.null_points > 0 THEN '🔴 NULL points found'
      WHEN e.player_count IS NOT NULL THEN '✅ Quality OK'
      ELSE NULL
    END as espn_quality,
    
    -- BDL comparison (only if both exist)
    CASE
      WHEN e.game_id IS NOT NULL AND b.game_id IS NOT NULL THEN
        ABS(e.player_count - b.bdl_player_count)
      ELSE NULL
    END as player_count_diff
    
  FROM espn_recent e
  FULL OUTER JOIN bdl_recent b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
)

-- Output results
SELECT
  game_date,
  CONCAT(away_team, ' @ ', home_team) as matchup,
  game_id,
  source_status,
  
  -- ESPN metrics
  espn_players,
  espn_unique,
  espn_teams,
  espn_total_pts,
  espn_max_pts,
  espn_dnp,
  espn_quality,
  
  -- BDL comparison
  bdl_players,
  player_count_diff,
  
  -- Overall assessment
  CASE
    WHEN source_status = 'ESPN_ONLY' AND bdl_players IS NULL THEN 
      '⚠️ ESPN collected but BDL did not - INVESTIGATE'
    WHEN source_status = 'BDL_ONLY' THEN 
      '⚪ Normal - BDL is primary source'
    WHEN source_status = 'BOTH' AND espn_quality LIKE '✅%' AND player_count_diff <= 2 THEN
      '✅ Perfect - Both sources match'
    WHEN source_status = 'BOTH' AND player_count_diff > 2 THEN
      '⚠️ Player count mismatch - review data'
    WHEN espn_quality LIKE '🔴%' THEN
      '🔴 CRITICAL - Data quality issue'
    ELSE
      '⚪ Review manually'
  END as assessment

FROM comparison
ORDER BY game_date DESC, game_id;
