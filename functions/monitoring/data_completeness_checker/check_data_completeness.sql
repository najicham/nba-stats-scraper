-- Daily Data Completeness Check
-- Compares NBA schedule vs actual data sources (Gamebook, BDL)
-- Returns missing games from the last 7 days

WITH schedule AS (
  SELECT
    game_date,
    game_id,
    game_code,
    home_team_tricode,
    away_team_tricode,
    game_status_text
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status_text = 'Final'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND game_date < CURRENT_DATE()  -- Don't check today (incomplete)
),
gamebook_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr,
    COUNT(DISTINCT player_name) as player_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND game_date < CURRENT_DATE()
  GROUP BY game_date, home_team_abbr, away_team_abbr
),
bdl_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr,
    COUNT(DISTINCT player_full_name) as player_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND game_date < CURRENT_DATE()
  GROUP BY game_date, home_team_abbr, away_team_abbr
)
SELECT
  s.game_date,
  s.game_code,
  CONCAT(s.away_team_tricode, '@', s.home_team_tricode) as matchup,
  CASE
    WHEN g.game_date IS NULL THEN 'MISSING'
    WHEN g.player_count < 10 THEN 'INCOMPLETE'
    ELSE 'OK'
  END as gamebook_status,
  COALESCE(g.player_count, 0) as gamebook_players,
  CASE
    WHEN b.game_date IS NULL THEN 'MISSING'
    WHEN b.player_count < 10 THEN 'INCOMPLETE'
    ELSE 'OK'
  END as bdl_status,
  COALESCE(b.player_count, 0) as bdl_players
FROM schedule s
LEFT JOIN gamebook_games g
  ON s.game_date = g.game_date
  AND s.home_team_tricode = g.home_team_abbr
  AND s.away_team_tricode = g.away_team_abbr
LEFT JOIN bdl_games b
  ON s.game_date = b.game_date
  AND s.home_team_tricode = b.home_team_abbr
  AND s.away_team_tricode = b.away_team_abbr
WHERE g.game_date IS NULL
   OR b.game_date IS NULL
   OR g.player_count < 10
   OR b.player_count < 10
ORDER BY s.game_date DESC, s.game_code
