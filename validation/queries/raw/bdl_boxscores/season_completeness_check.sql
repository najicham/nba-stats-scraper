-- ============================================================================
-- File: validation/queries/raw/bdl_boxscores/season_completeness_check.sql
-- Purpose: Comprehensive season validation for BDL player box scores
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins, null_teams
--   - Regular season: ~1,230 games per season with balanced player counts
--   - Playoffs: Variable games based on series length
--   - Player counts: ~30-35 total per game (no exact target, varies by rotations)
-- ============================================================================

WITH
boxscores_with_season_info AS (
  SELECT
    b.game_date,
    b.game_id,
    b.team_abbr,
    b.player_lookup,
    b.points,
    s.is_playoffs,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_id as schedule_game_id,
    CASE
      WHEN b.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN b.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN b.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN b.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON b.game_date = s.game_date
    AND (b.team_abbr = s.home_team_tricode OR b.team_abbr = s.away_team_tricode)
  WHERE b.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN game_id END) as null_playoff_flag_games,
    COUNT(DISTINCT CASE WHEN schedule_game_id IS NULL THEN game_id END) as failed_join_games,
    COUNT(DISTINCT CASE WHEN team_abbr IS NULL THEN game_id END) as null_team_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games_found,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN game_id END) as regular_season_games_found,
    COUNT(*) as total_player_records
  FROM boxscores_with_season_info
  WHERE season IS NOT NULL
),

-- Count games per team with player statistics
team_games AS (
  SELECT
    season,
    team_abbr,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    COUNT(DISTINCT game_id) as games,
    COUNT(DISTINCT player_lookup) as unique_players_used,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(players_per_game) as min_players,
    MAX(players_per_game) as max_players
  FROM (
    SELECT
      season,
      team_abbr,
      game_id,
      is_playoffs,
      COUNT(DISTINCT player_lookup) as players_per_game
    FROM boxscores_with_season_info
    WHERE season IS NOT NULL
    GROUP BY season, team_abbr, game_id, is_playoffs
  )
  GROUP BY season, team_abbr, is_playoffs
)

-- Output diagnostics first
SELECT
  row_type,
  CAST(total_games AS STRING) as season,
  'diagnostics' as team,
  CAST(null_playoff_flag_games AS STRING) as reg_games,
  CAST(failed_join_games AS STRING) as playoff_games,
  CAST(null_team_games AS STRING) as unique_players,
  CAST(total_player_records AS STRING) as avg_players,
  '' as min_players,
  '' as max_players,
  'Check: null counts should be 0' as notes
FROM diagnostics

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team_abbr as team,
  CAST(SUM(CASE WHEN is_playoffs = FALSE THEN games END) AS STRING) as reg_games,
  CAST(SUM(CASE WHEN is_playoffs = TRUE THEN games END) AS STRING) as playoff_games,
  CAST(MAX(unique_players_used) AS STRING) as unique_players,
  CAST(MAX(CASE WHEN is_playoffs = FALSE THEN avg_players_per_game END) AS STRING) as avg_players,
  CAST(MIN(CASE WHEN is_playoffs = FALSE THEN min_players END) AS STRING) as min_players,
  CAST(MAX(CASE WHEN is_playoffs = FALSE THEN max_players END) AS STRING) as max_players,
  CASE
    WHEN SUM(CASE WHEN is_playoffs = FALSE THEN games END) < 82 THEN '⚠️ Missing regular season games'
    WHEN MIN(CASE WHEN is_playoffs = FALSE THEN min_players END) < 10 THEN '⚠️ Suspiciously low player count'
    ELSE ''
  END as notes
FROM team_games
GROUP BY season, team_abbr
ORDER BY
  row_type,
  season,
  CAST(SUM(CASE WHEN is_playoffs = TRUE THEN games END) AS INT64) DESC,
  team;
