-- ============================================================================
-- File: validation/queries/raw/odds_api_props/find_missing_games.sql
-- Purpose: Identify specific games with ZERO player props (CRITICAL issues)
-- Usage: Run when season_completeness_check shows missing games
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to identify dates needing rescraping
-- ============================================================================
-- Expected Results:
--   - List of games with NO props data (scraper failure)
--   - Empty result = all scheduled games have at least some props
-- ============================================================================

WITH
-- Get all games from schedule (excluding All-Star and preseason)
all_scheduled_games AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_name as home_team,
    s.home_team_tricode,
    s.away_team_name as away_team,
    s.away_team_tricode,
    s.is_playoffs,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2023-05-03' AND '2025-06-30'  -- Full date range (May 2023 - end of 2024-25)
    AND s.is_all_star = FALSE  -- Exclude All-Star games
    AND (s.is_regular_season = TRUE OR s.is_playoffs = TRUE)  -- Only regular season and playoffs
),

-- Get all games we have props for
props_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(DISTINCT player_lookup) as player_count,
    COUNT(DISTINCT bookmaker) as bookmaker_count
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
  WHERE game_date BETWEEN '2023-05-03' AND '2025-06-30'  -- Match schedule range
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
)

-- Find games in schedule but not in props (CRITICAL)
SELECT
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  CASE WHEN s.is_playoffs THEN 'PLAYOFF' ELSE 'REGULAR SEASON' END as game_type,
  '🔴 CRITICAL: NO PROPS DATA' as status,
  'Scraper did not run or failed completely' as likely_cause
FROM all_scheduled_games s
LEFT JOIN props_games p
  ON s.game_date = p.game_date
  AND s.home_team_tricode = p.home_team_abbr
  AND s.away_team_tricode = p.away_team_abbr
WHERE p.game_date IS NULL
ORDER BY s.game_date, s.is_playoffs DESC;