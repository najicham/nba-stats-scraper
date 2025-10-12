-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/find_market_discrepancies.sql
-- Purpose: Find games with only spreads or only totals (bookmaker-specific gaps)
-- Usage: Run to identify games where one bookmaker didn't offer a market
-- ============================================================================
-- Instructions:
--   1. Update date range for the season you're checking
--   2. Run the query
--   3. Review results - small numbers (<1% of games) are normal
-- ============================================================================
-- Expected Results:
--   - Games with "Missing Totals" or "Missing Spreads"
--   - This is NORMAL - bookmakers occasionally don't offer markets
--   - Not a data quality issue unless systematic (many games on same date)
-- ============================================================================

WITH game_markets AS (
  SELECT 
    game_date,
    game_id,
    home_team,
    away_team,
    MAX(CASE WHEN market_key = 'spreads' THEN 1 ELSE 0 END) as has_spreads,
    MAX(CASE WHEN market_key = 'totals' THEN 1 ELSE 0 END) as has_totals,
    STRING_AGG(DISTINCT bookmaker_key ORDER BY bookmaker_key) as bookmakers
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-06-20'  -- UPDATE: Full season including playoffs
  GROUP BY game_date, game_id, home_team, away_team
)
SELECT 
  game_date,
  home_team,
  away_team,
  CONCAT(away_team, ' @ ', home_team) as matchup,
  bookmakers,
  has_spreads,
  has_totals,
  CASE 
    WHEN has_spreads = 1 AND has_totals = 0 THEN 'Missing Totals'
    WHEN has_spreads = 0 AND has_totals = 1 THEN 'Missing Spreads'
  END as issue
FROM game_markets
WHERE has_spreads != has_totals
ORDER BY game_date, home_team
LIMIT 100;