-- ============================================================================
-- File: validation/queries/raw/odds_api_props/season_completeness_check.sql
-- Purpose: Team-by-team season validation for player props
-- Usage: Run after backfills to verify team coverage
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins
--   - Each team should have games_with_props > 0
--   - Regular season avg: 6-8 players/game
--   - Playoffs avg: 8-10 players/game
-- ============================================================================

WITH
props_with_season_info AS (
  SELECT
    p.game_date,
    p.game_id as props_game_id,
    p.player_name,
    p.player_lookup,
    p.bookmaker,
    p.home_team_abbr,
    p.away_team_abbr,
    s.is_playoffs,
    s.home_team_tricode,
    s.away_team_tricode,
    CASE
      WHEN p.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN p.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN p.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN p.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON p.game_date = s.game_date
    AND p.home_team_abbr = s.home_team_tricode
    AND p.away_team_abbr = s.away_team_tricode
  WHERE p.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    '---' as season,
    'Quality Checks' as team,
    CAST(COUNT(DISTINCT props_game_id) AS STRING) as metric1,
    CAST(COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN props_game_id END) AS STRING) as metric2,
    CAST(COUNT(DISTINCT CASE WHEN home_team_tricode IS NULL THEN props_game_id END) AS STRING) as metric3,
    CAST(COUNT(DISTINCT player_lookup) AS STRING) as metric4,
    'total_games | null_playoff | null_team | unique_players' as description
  FROM props_with_season_info
  WHERE season IS NOT NULL
),

-- Calculate players per game
game_player_counts AS (
  SELECT
    season,
    props_game_id,
    home_team_abbr,
    away_team_abbr,
    is_playoffs,
    COUNT(DISTINCT player_lookup) as players_in_game
  FROM props_with_season_info
  WHERE season IS NOT NULL
  GROUP BY season, props_game_id, home_team_abbr, away_team_abbr, is_playoffs
),

-- Get stats per team
team_stats AS (
  SELECT
    season,
    team,
    is_playoffs,
    COUNT(DISTINCT game_id) as games,
    ROUND(AVG(players_in_game), 1) as avg_players
  FROM (
    -- Home games
    SELECT season, home_team_abbr as team, props_game_id as game_id, is_playoffs, players_in_game
    FROM game_player_counts
    UNION ALL
    -- Away games
    SELECT season, away_team_abbr as team, props_game_id as game_id, is_playoffs, players_in_game
    FROM game_player_counts
  )
  GROUP BY season, team, is_playoffs
),

-- Final aggregation by team and season
team_summary AS (
  SELECT
    season,
    team,
    SUM(CASE WHEN is_playoffs = FALSE THEN games ELSE 0 END) as reg_games,
    MAX(CASE WHEN is_playoffs = FALSE THEN avg_players ELSE 0 END) as reg_avg_players,
    SUM(CASE WHEN is_playoffs = TRUE THEN games ELSE 0 END) as playoff_games,
    MAX(CASE WHEN is_playoffs = TRUE THEN avg_players ELSE 0 END) as playoff_avg_players,
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

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team,
  CAST(reg_games AS STRING) as info1,
  CAST(reg_avg_players AS STRING) as info2,
  CAST(playoff_games AS STRING) as info3,
  CAST(playoff_avg_players AS STRING) as info4,
  CASE
    WHEN reg_games = 0 AND playoff_games = 0 THEN '❌ No games'
    WHEN reg_avg_players < 6.0 AND reg_games > 0 THEN '🟡 Low coverage'
    ELSE ''
  END as notes
FROM team_summary
ORDER BY
  row_type,
  season,
  CAST(info3 AS INT64) DESC,
  team;
