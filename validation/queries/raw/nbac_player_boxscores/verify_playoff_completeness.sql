-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/verify_playoff_completeness.sql
-- Purpose: Verify playoff game completeness for teams that made playoffs
-- Usage: Run after season ends or to verify playoff data integrity
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- This query is ready to execute once playoff data arrives
-- ============================================================================
-- Expected Results:
--   - All teams should show expected playoff games matching actual series played
--   - Player counts should be ~30-35 per game
--   - Starters should be ~10 per game (5 per team)
--   - Status should be "✅ Complete" for all teams
--   - Should match BDL playoff completeness closely
-- ============================================================================

WITH
-- Check if table has data
data_check AS (
  SELECT COUNT(*) as total_records
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= '2021-10-19'
    AND is_playoff_game = TRUE
),

-- Get playoff games per team with player counts
playoff_games AS (
  SELECT
    b.game_date,
    b.game_id,
    b.team_abbr,
    s.season_nba_format,
    s.playoff_round,
    COUNT(DISTINCT b.player_lookup) as players_in_game,
    COUNT(DISTINCT CASE WHEN b.starter = TRUE THEN b.player_lookup END) as starters_in_game,
    COUNT(DISTINCT b.nba_player_id) as unique_nba_ids
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores` b
  INNER JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON b.game_date = s.game_date
    AND b.game_id = s.game_id  -- Direct join (formats match)
  WHERE s.is_playoffs = TRUE
    AND b.is_playoff_game = TRUE
    AND b.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY b.game_date, b.game_id, b.team_abbr, s.season_nba_format, s.playoff_round
),

-- Expected playoff games from schedule
expected_playoff_games AS (
  SELECT
    home_team_tricode as team_abbr,
    season_nba_format,
    COUNT(*) as expected_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE is_playoffs = TRUE
    AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY home_team_tricode, season_nba_format

  UNION ALL

  SELECT
    away_team_tricode as team_abbr,
    season_nba_format,
    COUNT(*) as expected_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE is_playoffs = TRUE
    AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY away_team_tricode, season_nba_format
),

-- Aggregate expected games per team
expected_totals AS (
  SELECT
    team_abbr,
    season_nba_format,
    SUM(expected_games) as expected_games
  FROM expected_playoff_games
  GROUP BY team_abbr, season_nba_format
),

-- Team-level playoff stats
team_playoff_stats AS (
  SELECT
    pg.team_abbr,
    pg.season_nba_format,
    COUNT(DISTINCT pg.game_id) as actual_games,
    COUNT(*) as total_player_records,
    ROUND(AVG(pg.players_in_game), 1) as avg_players_per_game,
    ROUND(AVG(pg.starters_in_game), 1) as avg_starters_per_game,
    MIN(pg.players_in_game) as min_players_per_game,
    MAX(pg.players_in_game) as max_players_per_game,
    COUNT(DISTINCT pg.unique_nba_ids) as total_unique_players
  FROM playoff_games pg
  GROUP BY pg.team_abbr, pg.season_nba_format
),

-- BDL comparison for validation
bdl_playoff_stats AS (
  SELECT
    b.team_abbr,
    s.season_nba_format,
    COUNT(DISTINCT b.game_id) as bdl_playoff_games
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
  INNER JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON b.game_date = s.game_date
    AND (b.team_abbr = s.home_team_tricode OR b.team_abbr = s.away_team_tricode)
  WHERE s.is_playoffs = TRUE
    AND b.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY b.team_abbr, s.season_nba_format
)

-- No data message
SELECT
  '⚪ No Data' as team,
  'No playoff data available yet' as season,
  0 as expected_games,
  0 as actual_games,
  0 as total_player_records,
  0.0 as avg_players_per_game,
  0.0 as avg_starters_per_game,
  0 as missing_games,
  NULL as bdl_games,
  'NBA.com player boxscores table has no playoff data - awaiting playoffs' as status
FROM data_check
WHERE total_records = 0

UNION ALL

-- Final output with BDL comparison
SELECT
  CONCAT(tps.team_abbr, ' (', tps.season_nba_format, ')') as team,
  tps.season_nba_format as season,
  et.expected_games,
  tps.actual_games,
  tps.total_player_records,
  tps.avg_players_per_game,
  tps.avg_starters_per_game,
  (et.expected_games - tps.actual_games) as missing_games,
  bdl.bdl_playoff_games as bdl_games,
  CASE
    -- Check game completeness
    WHEN tps.actual_games < et.expected_games THEN
      CONCAT('❌ Missing ', CAST(et.expected_games - tps.actual_games AS STRING), ' games')
    
    -- Check player counts
    WHEN tps.min_players_per_game < 20 THEN 
      '⚠️ Low player count detected'
    
    -- Check starter counts
    WHEN tps.avg_starters_per_game < 9.5 OR tps.avg_starters_per_game > 10.5 THEN
      CONCAT('⚠️ Unusual starter count: ', CAST(tps.avg_starters_per_game AS STRING))
    
    -- Check BDL consistency
    WHEN bdl.bdl_playoff_games IS NOT NULL 
     AND ABS(tps.actual_games - bdl.bdl_playoff_games) > 0 THEN
      CONCAT('⚠️ Discrepancy vs BDL: ', CAST(bdl.bdl_playoff_games AS STRING), ' games')
    
    -- All checks passed
    WHEN tps.actual_games = et.expected_games
      AND tps.min_players_per_game >= 20
      AND tps.avg_starters_per_game BETWEEN 9.5 AND 10.5
    THEN '✅ Complete'
    
    ELSE '⚠️ Data quality issue'
  END as status
  
FROM team_playoff_stats tps
INNER JOIN expected_totals et
  ON tps.team_abbr = et.team_abbr
  AND tps.season_nba_format = et.season_nba_format
LEFT JOIN bdl_playoff_stats bdl
  ON tps.team_abbr = bdl.team_abbr
  AND tps.season_nba_format = bdl.season_nba_format
CROSS JOIN data_check
WHERE data_check.total_records > 0

ORDER BY
  CASE 
    WHEN team = '⚪ No Data' THEN 0
    ELSE 1
  END,
  season DESC,
  missing_games DESC,
  team;