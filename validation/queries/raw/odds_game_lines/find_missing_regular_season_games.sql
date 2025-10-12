-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/find_missing_regular_season_games.sql
-- Purpose: Identify specific regular season games missing from odds data
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to create backfill dates file
-- ============================================================================
-- Expected Results:
--   - List of specific games (date, matchup) that need to be scraped
--   - Empty result = all regular season games present
-- ============================================================================

WITH 
-- Get all regular season games from schedule
all_scheduled_games AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_name as home_team,
    s.home_team_tricode,
    s.away_team_name as away_team,
    s.away_team_tricode,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2021-10-19' AND '2022-04-10'  -- UPDATE: Regular season only
    AND s.is_playoffs = FALSE
),

-- Get all games we have odds for
odds_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'  -- UPDATE: Match schedule range
)

-- Find games in schedule but not in odds
SELECT 
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  'MISSING FROM ODDS DATA' as status
FROM all_scheduled_games s
LEFT JOIN odds_games o
  ON s.game_date = o.game_date
  AND s.home_team_tricode = o.home_team_abbr
  AND s.away_team_tricode = o.away_team_abbr
WHERE o.game_date IS NULL
ORDER BY s.game_date;