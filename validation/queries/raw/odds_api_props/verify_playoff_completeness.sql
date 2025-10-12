-- ============================================================================
-- File: validation/queries/raw/odds_api_props/verify_playoff_completeness.sql
-- Purpose: Verify playoff game props coverage matches schedule
-- Usage: Run after playoffs end or during playoffs to validate data
-- ============================================================================
-- Instructions:
--   1. Update date range for the playoff period you're checking
--   2. Run the query - it automatically gets expected counts from schedule
--   3. All teams should show "✅ Complete" or "⚠️ Low Coverage" status
-- ============================================================================
-- Note: Playoffs typically have MORE props (8-10 players) than regular season
--       This query validates both game count and player coverage
-- ============================================================================

WITH
-- Get expected playoff games from schedule (source of truth)
expected_playoff_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-04-12' AND '2024-06-20'  -- UPDATE: Playoff period
    AND is_playoffs = TRUE
),

-- Count expected games per team
expected_by_team AS (
  SELECT
    tricode,
    COUNT(*) as expected_games
  FROM (
    SELECT home_team_tricode as tricode
    FROM expected_playoff_games

    UNION ALL

    SELECT away_team_tricode as tricode
    FROM expected_playoff_games
  )
  GROUP BY tricode
),

-- Get actual playoff props from our table
actual_playoff_props AS (
  SELECT DISTINCT
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    COUNT(DISTINCT p.player_lookup) as unique_players,
    COUNT(DISTINCT p.bookmaker) as bookmaker_count
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
  WHERE p.game_date BETWEEN '2024-04-12' AND '2024-06-20'  -- UPDATE: Match schedule dates
  GROUP BY p.game_date, p.game_id, p.home_team_abbr, p.away_team_abbr
),

-- Count actual games per team and calculate player averages
actual_by_team AS (
  SELECT
    tricode,
    COUNT(DISTINCT game_id) as actual_games,
    ROUND(AVG(unique_players), 1) as avg_players_per_game,
    ROUND(AVG(bookmaker_count), 1) as avg_bookmakers_per_game,
    MIN(unique_players) as min_players,
    MAX(unique_players) as max_players
  FROM (
    SELECT
      home_team_abbr as tricode,
      game_id,
      unique_players,
      bookmaker_count
    FROM actual_playoff_props

    UNION ALL

    SELECT
      away_team_abbr as tricode,
      game_id,
      unique_players,
      bookmaker_count
    FROM actual_playoff_props
  )
  GROUP BY tricode
)

SELECT
  e.tricode as team,
  e.expected_games,
  COALESCE(a.actual_games, 0) as actual_games,
  e.expected_games - COALESCE(a.actual_games, 0) as missing_games,
  COALESCE(a.avg_players_per_game, 0) as avg_players,
  COALESCE(a.min_players, 0) as min_players,
  COALESCE(a.max_players, 0) as max_players,
  COALESCE(a.avg_bookmakers_per_game, 0) as avg_bookmakers,
  CASE
    WHEN COALESCE(a.actual_games, 0) = 0
    THEN '❌ All Missing'
    WHEN COALESCE(a.actual_games, 0) < e.expected_games
    THEN CONCAT('⚠️ Incomplete (', CAST(e.expected_games - COALESCE(a.actual_games, 0) AS STRING), ' missing)')
    WHEN COALESCE(a.avg_players_per_game, 0) < 6.0
    THEN '🟡 Low Player Coverage'
    WHEN COALESCE(a.avg_players_per_game, 0) < 8.0
    THEN '⚠️ Below Playoff Average'
    ELSE '✅ Complete'
  END as status
FROM expected_by_team e
LEFT JOIN actual_by_team a ON e.tricode = a.tricode
ORDER BY e.expected_games DESC, team;
