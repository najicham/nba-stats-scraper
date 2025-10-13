-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/verify_playoff_completeness.sql
-- Purpose: Verify playoff game completeness for teams that made playoffs
-- Usage: Run after season ends or to verify playoff data integrity
-- ============================================================================
-- Expected Results:
--   - All teams should show expected playoff games matching actual series played
--   - Player counts should be ~30-35 per game
--   - Status should be "✅ Complete" for all teams
-- ============================================================================

WITH
-- Get playoff games per team with player counts
playoff_games AS (
  SELECT
    b.game_date,
    b.game_id,
    b.team_abbr,
    s.season_nba_format,
    s.playoff_round,
    COUNT(DISTINCT b.player_lookup) as players_in_game
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
  INNER JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON b.game_date = s.game_date
    AND (b.team_abbr = s.home_team_tricode OR b.team_abbr = s.away_team_tricode)
  WHERE s.is_playoffs = TRUE
    AND b.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY b.game_date, b.game_id, b.team_abbr, s.season_nba_format, s.playoff_round
),

-- Expected playoff games from schedule (count home and away separately)
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
    MIN(pg.players_in_game) as min_players_per_game,
    MAX(pg.players_in_game) as max_players_per_game
  FROM playoff_games pg
  GROUP BY pg.team_abbr, pg.season_nba_format
)

-- Final output
SELECT
  CONCAT(tps.team_abbr, ' (', tps.season_nba_format, ')') as team,
  et.expected_games,
  tps.actual_games,
  tps.total_player_records,
  tps.avg_players_per_game,
  (et.expected_games - tps.actual_games) as missing_games,
  CASE
    WHEN tps.actual_games = et.expected_games 
      AND tps.min_players_per_game >= 20 THEN '✅ Complete'
    WHEN tps.actual_games < et.expected_games THEN 
      CONCAT('❌ Missing ', CAST(et.expected_games - tps.actual_games AS STRING), ' games')
    WHEN tps.min_players_per_game < 20 THEN '⚠️ Low player count detected'
    ELSE '⚠️ Data quality issue'
  END as status
FROM team_playoff_stats tps
INNER JOIN expected_totals et
  ON tps.team_abbr = et.team_abbr
  AND tps.season_nba_format = et.season_nba_format
ORDER BY 
  tps.season_nba_format DESC,
  missing_games DESC,
  team;