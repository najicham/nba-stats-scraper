-- ============================================================================
-- File: validation/queries/raw/odds_api_props/find_low_coverage_games.sql
-- Purpose: Identify games with unusually low player prop coverage (WARNING level)
-- Usage: Run to find games that have some props but fewer players than expected
-- ============================================================================
-- Instructions:
--   1. Update the date range for the period you're checking
--   2. Adjust LOW_COVERAGE_THRESHOLD if needed (default: 6 players)
--   3. Run the query
-- ============================================================================
-- Expected Results:
--   - Games with < 6 unique players with props (might be acceptable)
--   - Regular season expected: ~6-8 players per game
--   - Playoffs expected: ~8-10 players per game
-- ============================================================================

WITH
props_by_game AS (
  SELECT
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    s.is_playoffs,
    COUNT(DISTINCT p.player_lookup) as unique_players,
    COUNT(DISTINCT p.bookmaker) as bookmaker_count,
    STRING_AGG(DISTINCT p.player_name ORDER BY p.player_name LIMIT 10) as sample_players
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON p.game_date = s.game_date
    AND p.home_team_abbr = s.home_team_tricode
    AND p.away_team_abbr = s.away_team_tricode
  WHERE p.game_date BETWEEN '2023-10-24' AND '2024-06-20'  -- UPDATE: Season range
    AND s.game_date BETWEEN '2023-10-24' AND '2024-06-20'  -- UPDATE: Match props range
  GROUP BY p.game_date, p.game_id, p.home_team_abbr, p.away_team_abbr, s.is_playoffs
)

SELECT
  game_date,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  CASE WHEN is_playoffs THEN 'PLAYOFF' ELSE 'REGULAR SEASON' END as game_type,
  unique_players,
  bookmaker_count,
  CASE
    WHEN unique_players < 4 THEN '🟡 VERY LOW'
    WHEN unique_players < 6 THEN '🟡 LOW'
    ELSE '⚠️ BELOW AVERAGE'
  END as coverage_level,
  sample_players,
  CASE
    WHEN bookmaker_count = 0 THEN 'No bookmakers (data issue)'
    WHEN bookmaker_count = 1 THEN 'Single bookmaker only'
    ELSE CONCAT(CAST(bookmaker_count AS STRING), ' bookmakers')
  END as bookmaker_note
FROM props_by_game
WHERE unique_players < 6  -- LOW_COVERAGE_THRESHOLD
ORDER BY unique_players ASC, game_date DESC;
