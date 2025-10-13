-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/find_missing_games.sql
-- Purpose: Identify specific games missing from BDL box scores
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- FIXED: Now joins on date+teams instead of game_id (format mismatch issue)
-- BDL uses format: YYYYMMDD_AWAY_HOME
-- Schedule uses format: 00SSGGGGGG
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to investigate scraper issues or create backfill plan
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
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-20'  -- UPDATE: Regular season only
    AND s.is_playoffs = FALSE
),
-- Get all games we have box scores for
boxscore_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-20'  -- UPDATE: Match schedule range
)
-- Find games in schedule but not in box scores
-- JOIN ON DATE + TEAMS (not game_id - formats don't match!)
SELECT
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  'MISSING FROM BDL BOX SCORES' as status,
  s.game_id as schedule_game_id
FROM all_scheduled_games s
LEFT JOIN boxscore_games b
  ON s.game_date = b.game_date
  AND s.home_team_tricode = b.home_team_abbr
  AND s.away_team_tricode = b.away_team_abbr
WHERE b.game_date IS NULL
ORDER BY s.game_date;