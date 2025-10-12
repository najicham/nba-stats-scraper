-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/season_completeness_check.sql
-- Purpose: Comprehensive season validation with diagnostics
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins, null_abbr
--   - All teams should have 82/82 for regular season spreads and totals
--   - Playoff games should match actual playoff results
-- ============================================================================

WITH 
odds_with_season_info AS (
  SELECT 
    o.game_date,
    o.game_id as odds_game_id,
    o.home_team,
    o.away_team,
    o.home_team_abbr,
    o.away_team_abbr,
    o.market_key,
    o.bookmaker_key,
    s.is_playoffs,
    s.game_id as schedule_game_id,
    CASE 
      WHEN o.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN o.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN o.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN o.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.odds_api_game_lines` o
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s 
    ON o.game_date = s.game_date 
    AND o.home_team_abbr = s.home_team_tricode
    AND o.away_team_abbr = s.away_team_tricode
  WHERE o.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    -- NOTE: No bookmaker filter - count either DraftKings or FanDuel
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT 
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT odds_game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN odds_game_id END) as null_playoff_flag_games,
    COUNT(DISTINCT CASE WHEN schedule_game_id IS NULL THEN odds_game_id END) as failed_join_games,
    COUNT(DISTINCT CASE WHEN home_team_abbr IS NULL OR away_team_abbr IS NULL THEN odds_game_id END) as null_abbr_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN odds_game_id END) as playoff_games_found,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN odds_game_id END) as regular_season_games_found
  FROM odds_with_season_info
  WHERE season IS NOT NULL
),

-- Count unique games per team (using DISTINCT to handle either bookmaker)
team_games AS (
  SELECT DISTINCT
    season,
    home_team as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    market_key,
    odds_game_id
  FROM odds_with_season_info
  WHERE season IS NOT NULL
  
  UNION DISTINCT
  
  SELECT DISTINCT
    season,
    away_team as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    market_key,
    odds_game_id
  FROM odds_with_season_info
  WHERE season IS NOT NULL
),

team_stats AS (
  SELECT 
    season,
    team,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE AND market_key = 'spreads' THEN odds_game_id END) as reg_spreads,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE AND market_key = 'totals' THEN odds_game_id END) as reg_totals,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE AND market_key = 'spreads' THEN odds_game_id END) as playoff_spreads,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE AND market_key = 'totals' THEN odds_game_id END) as playoff_totals,
    COUNT(DISTINCT odds_game_id) as total_games
  FROM team_games
  GROUP BY season, team
)

-- Output diagnostics first
SELECT 
  row_type,
  CAST(total_games AS STRING) as season,
  'null_playoff_flag' as team,
  CAST(null_playoff_flag_games AS STRING) as reg_spreads,
  CAST(failed_join_games AS STRING) as reg_totals,
  CAST(null_abbr_games AS STRING) as playoff_spreads,
  CAST(playoff_games_found AS STRING) as playoff_totals,
  CAST(regular_season_games_found AS STRING) as total,
  'Check: all should be 0' as notes
FROM diagnostics

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team,
  CAST(reg_spreads AS STRING) as reg_spreads,
  CAST(reg_totals AS STRING) as reg_totals,
  CAST(playoff_spreads AS STRING) as playoff_spreads,
  CAST(playoff_totals AS STRING) as playoff_totals,
  CAST(total_games AS STRING) as total,
  CASE 
    WHEN reg_spreads < 82 OR reg_totals < 82 THEN '⚠️ Missing games'
    ELSE ''
  END as notes
FROM team_stats
ORDER BY 
  row_type,
  season,
  CAST(playoff_spreads AS INT64) DESC,
  team;