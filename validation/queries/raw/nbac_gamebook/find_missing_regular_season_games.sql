-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/find_missing_regular_season_games.sql
-- Purpose: Identify specific regular season games missing from gamebook data
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to identify which games need reprocessing
-- ============================================================================
-- Expected Results:
--   - List of specific games (date, matchup) that need gamebook data
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
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Regular season only
    AND s.is_playoffs = FALSE
),

-- Get all games we have gamebook data for
gamebook_games AS (
  SELECT DISTINCT
    game_date,
    game_id
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Match schedule range
),

-- Games with insufficient player data (likely scraper/processor failure)
incomplete_games AS (
  SELECT
    game_date,
    game_id,
    COUNT(*) as player_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'
  GROUP BY game_date, game_id
  HAVING COUNT(*) < 25  -- Expect at least 25 players per game
)

-- Find completely missing games
SELECT
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  'COMPLETELY MISSING' as status,
  0 as player_count
FROM all_scheduled_games s
LEFT JOIN gamebook_games g
  ON s.game_date = g.game_date
  AND s.game_id = g.game_id
WHERE g.game_date IS NULL

UNION ALL

-- Find incomplete games (too few players)
SELECT
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  'INCOMPLETE DATA' as status,
  i.player_count
FROM all_scheduled_games s
JOIN incomplete_games i
  ON s.game_date = i.game_date
  AND s.game_id = i.game_id

ORDER BY game_date, status DESC;
