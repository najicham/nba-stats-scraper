-- ============================================================================
-- File: validation/queries/raw/bettingpros_player_props/season_completeness_check.sql
-- Purpose: Team-by-team season validation for BettingPros player props
-- Usage: Run after backfills to verify team coverage across all seasons
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show confidence distribution
--   - Each team should have games_with_props > 0
--   - Regular season avg: 40-60 props/game (varies by bookmaker coverage)
--   - Playoffs avg: 40-50 props/game (more focused coverage)
-- ============================================================================
-- Key Differences from Odds API:
--   - Tracks validation_confidence scores (0.1, 0.3, 0.95)
--   - No game_id field - uses date + team matching
--   - Variable bookmaker coverage (20 active sportsbooks)
-- ============================================================================

WITH
props_with_season_info AS (
  SELECT
    p.game_date,
    p.player_name,
    p.player_lookup,
    p.bookmaker,
    p.player_team,
    p.validation_confidence,
    s.is_playoffs,
    s.home_team_tricode,
    s.away_team_tricode,
    CASE
      WHEN p.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN p.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN p.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN p.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props` p
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON p.game_date = s.game_date
    AND (p.player_team = s.home_team_tricode OR p.player_team = s.away_team_tricode)
  WHERE p.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    '---' as season,
    'Quality Checks' as team,
    CAST(COUNT(DISTINCT game_date) AS STRING) as metric1,
    CAST(COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN game_date END) AS STRING) as metric2,
    CAST(ROUND(AVG(validation_confidence), 2) AS STRING) as metric3,
    CAST(COUNT(DISTINCT bookmaker) AS STRING) as metric4,
    'total_dates | null_playoff | avg_confidence | unique_books' as description
  FROM props_with_season_info
  WHERE season IS NOT NULL
),

-- Confidence distribution diagnostics
confidence_stats AS (
  SELECT
    'CONFIDENCE' as row_type,
    '---' as season,
    CONCAT('Conf=', CAST(validation_confidence AS STRING)) as team,
    CAST(COUNT(*) AS STRING) as metric1,
    CAST(COUNT(DISTINCT game_date) AS STRING) as metric2,
    CAST(ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS STRING) as metric3,
    '' as metric4,
    'records | dates | percentage | ---' as description
  FROM props_with_season_info
  WHERE season IS NOT NULL
  GROUP BY validation_confidence
),

-- Calculate props per game by team
game_team_props AS (
  SELECT
    season,
    game_date,
    COALESCE(player_team, 'UNKNOWN') as team,
    is_playoffs,
    COUNT(*) as props_in_game,
    COUNT(DISTINCT player_lookup) as players_in_game,
    COUNT(DISTINCT bookmaker) as bookmakers_in_game,
    AVG(validation_confidence) as avg_confidence
  FROM props_with_season_info
  WHERE season IS NOT NULL
  GROUP BY season, game_date, player_team, is_playoffs
),

-- Get stats per team
team_stats AS (
  SELECT
    season,
    team,
    is_playoffs,
    COUNT(DISTINCT game_date) as games,
    ROUND(AVG(props_in_game), 1) as avg_props,
    ROUND(AVG(players_in_game), 1) as avg_players,
    ROUND(AVG(bookmakers_in_game), 1) as avg_bookmakers,
    ROUND(AVG(avg_confidence), 2) as avg_confidence
  FROM game_team_props
  WHERE team != 'UNKNOWN'
  GROUP BY season, team, is_playoffs
),

-- Final aggregation by team and season
team_summary AS (
  SELECT
    season,
    team,
    SUM(CASE WHEN is_playoffs = FALSE THEN games ELSE 0 END) as reg_games,
    MAX(CASE WHEN is_playoffs = FALSE THEN avg_props ELSE 0 END) as reg_avg_props,
    MAX(CASE WHEN is_playoffs = FALSE THEN avg_players ELSE 0 END) as reg_avg_players,
    SUM(CASE WHEN is_playoffs = TRUE THEN games ELSE 0 END) as playoff_games,
    MAX(CASE WHEN is_playoffs = TRUE THEN avg_props ELSE 0 END) as playoff_avg_props,
    MAX(CASE WHEN is_playoffs = TRUE THEN avg_confidence ELSE 0 END) as playoff_confidence,
    SUM(games) as total_games
  FROM team_stats
  GROUP BY season, team
)

-- Output diagnostics first
SELECT
  row_type,
  season,
  team,
  metric1 as info1,
  metric2 as info2,
  metric3 as info3,
  metric4 as info4,
  description as notes
FROM diagnostics

UNION ALL

-- Confidence distribution
SELECT
  row_type,
  season,
  team,
  metric1,
  metric2,
  metric3,
  metric4,
  description
FROM confidence_stats

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team,
  CAST(reg_games AS STRING) as info1,
  CAST(reg_avg_props AS STRING) as info2,
  CAST(playoff_games AS STRING) as info3,
  CAST(playoff_avg_props AS STRING) as info4,
  CASE
    WHEN reg_games = 0 AND playoff_games = 0 THEN '❌ No games'
    WHEN reg_avg_props < 30.0 AND reg_games > 0 THEN '🟡 Low coverage (<30 props/game)'
    WHEN playoff_games > 0 AND playoff_confidence < 0.5 THEN '🟡 Low playoff confidence'
    ELSE ''
  END as notes
FROM team_summary
ORDER BY
  row_type,
  season DESC,
  CAST(info1 AS INT64) DESC,
  team;
