-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/verify_playoff_completeness.sql
-- Purpose: Verify playoff game counts match schedule (uses tricodes for accuracy)
-- Usage: Run after season ends or during playoffs to validate data
-- ============================================================================
-- Instructions:
--   1. Update date range for the playoff period you're checking
--   2. Run the query - it automatically gets expected counts from schedule
--   3. All teams should show "✅ Complete" status
-- ============================================================================
-- Note: This query uses team abbreviations (tricodes) to match between tables
--       Schedule uses tricodes, odds uses full names - we join on abbreviations
-- ============================================================================

WITH 
-- Get expected playoff games from schedule using tricodes (source of truth)
expected_playoff_games_raw AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2022-04-12' AND '2022-06-20'  -- UPDATE: Playoff period (play-in through Finals)
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

-- Get actual playoff games from odds (by tricode)
actual_playoff_games_raw AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    home_team,
    away_team,
    market_key
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date BETWEEN '2022-04-12' AND '2022-06-20'  -- UPDATE: Match schedule dates
),

-- Count actual games per team (by tricode) and get full team name
actual_by_tricode AS (
  SELECT 
    tricode,
    MAX(team_full_name) as team,  -- Get full team name from odds table for display
    COUNT(DISTINCT game_id) as actual_games,
    COUNT(DISTINCT CASE WHEN market_key = 'spreads' THEN game_id END) as actual_spreads,
    COUNT(DISTINCT CASE WHEN market_key = 'totals' THEN game_id END) as actual_totals
  FROM (
    SELECT 
      home_team_abbr as tricode, 
      home_team as team_full_name, 
      game_id, 
      market_key
    FROM actual_playoff_games_raw
    
    UNION ALL
    
    SELECT 
      away_team_abbr as tricode, 
      away_team as team_full_name, 
      game_id, 
      market_key
    FROM actual_playoff_games_raw
  )
  GROUP BY tricode
)

SELECT 
  COALESCE(a.team, e.tricode) as team,
  e.tricode,
  e.expected_games,
  COALESCE(a.actual_games, 0) as actual_games,
  COALESCE(a.actual_spreads, 0) as actual_spreads,
  COALESCE(a.actual_totals, 0) as actual_totals,
  e.expected_games - COALESCE(a.actual_games, 0) as missing_games,
  CASE 
    WHEN COALESCE(a.actual_games, 0) = e.expected_games 
     AND COALESCE(a.actual_spreads, 0) = e.expected_games
     AND COALESCE(a.actual_totals, 0) = e.expected_games
    THEN '✅ Complete'
    WHEN COALESCE(a.actual_games, 0) = 0 
    THEN '❌ All Missing'
    WHEN COALESCE(a.actual_games, 0) < e.expected_games
    THEN '⚠️ Incomplete'
    ELSE '⚠️ Data Quality Issue'
  END as status
FROM expected_by_tricode e
LEFT JOIN actual_by_tricode a ON e.tricode = a.tricode
ORDER BY e.expected_games DESC, team;