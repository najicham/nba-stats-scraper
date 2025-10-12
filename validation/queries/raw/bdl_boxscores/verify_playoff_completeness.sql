-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/verify_playoff_completeness.sql
-- Purpose: Verify playoff game counts match schedule (dynamic from source of truth)
-- Usage: Run after season ends or during playoffs to validate data
-- ============================================================================
-- Instructions:
--   1. Update date range for the playoff period you're checking
--   2. Run the query - it automatically gets expected counts from schedule
--   3. All teams should show "✅ Complete" status
-- ============================================================================
-- Note: This query uses team abbreviations (tricodes) to match between tables
--       Schedule uses tricodes, BDL uses team_abbr - these should match directly
-- ============================================================================

WITH
-- Get expected playoff games from schedule (source of truth)
expected_playoff_games_raw AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-04-20' AND '2024-06-20'  -- UPDATE: Playoff period (play-in through Finals)
    AND is_playoffs = TRUE
),

-- Count expected games per team (by tricode)
expected_by_tricode AS (
  SELECT
    tricode,
    COUNT(*) as expected_games
  FROM (
    SELECT home_team_tricode as tricode
    FROM expected_playoff_games_raw

    UNION ALL

    SELECT away_team_tricode as tricode
    FROM expected_playoff_games_raw
  )
  GROUP BY tricode
),

-- Get actual playoff games from BDL (by team_abbr)
actual_playoff_games_raw AS (
  SELECT DISTINCT
    game_date,
    game_id,
    team_abbr,
    home_team_abbr,
    away_team_abbr
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date BETWEEN '2024-04-20' AND '2024-06-20'  -- UPDATE: Match schedule dates
),

-- Count actual games per team
actual_by_tricode AS (
  SELECT
    team_abbr as tricode,
    COUNT(DISTINCT game_id) as actual_games,
    COUNT(DISTINCT player_lookup) as total_player_records,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game
  FROM (
    SELECT
      team_abbr,
      game_id,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM actual_playoff_games_raw
    CROSS JOIN UNNEST([team_abbr, home_team_abbr, away_team_abbr]) as team_abbr
    GROUP BY team_abbr, game_id
  )
  GROUP BY team_abbr
)

-- Compare expected vs actual
SELECT
  e.tricode as team,
  e.expected_games,
  COALESCE(a.actual_games, 0) as actual_games,
  COALESCE(a.total_player_records, 0) as total_player_records,
  COALESCE(a.avg_players_per_game, 0) as avg_players_per_game,
  e.expected_games - COALESCE(a.actual_games, 0) as missing_games,
  CASE
    WHEN COALESCE(a.actual_games, 0) = e.expected_games THEN '✅ Complete'
    WHEN COALESCE(a.actual_games, 0) = 0 THEN '❌ All Missing'
    WHEN COALESCE(a.actual_games, 0) < e.expected_games THEN '⚠️ Incomplete'
    ELSE '⚠️ Data Quality Issue'
  END as status
FROM expected_by_tricode e
LEFT JOIN actual_by_tricode a ON e.tricode = a.tricode
ORDER BY e.expected_games DESC, team;
