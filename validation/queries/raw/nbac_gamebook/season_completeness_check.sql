-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/season_completeness_check.sql
-- Purpose: Comprehensive season validation for NBA.com gamebook data
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins, null_team
--   - All teams should have ~82 games for regular season
--   - Each game should have ~30-35 total players (active + DNP + inactive)
--   - Name resolution rate should be ≥98.5%
-- ============================================================================

WITH
gamebook_with_season AS (
  SELECT
    g.game_date,
    g.game_id,
    g.home_team_abbr,
    g.away_team_abbr,
    g.team_abbr as player_team,
    g.player_status,
    g.name_resolution_status,
    g.player_name,
    s.is_playoffs,
    s.game_id as schedule_game_id,
    CASE
      WHEN g.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN g.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN g.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN g.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` g
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON g.game_date = s.game_date
    AND (g.home_team_abbr = s.home_team_tricode OR g.away_team_abbr = s.away_team_tricode)
  WHERE g.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN game_id END) as null_playoff_flag_games,
    COUNT(DISTINCT CASE WHEN schedule_game_id IS NULL THEN game_id END) as failed_join_games,
    COUNT(DISTINCT CASE WHEN home_team_abbr IS NULL OR away_team_abbr IS NULL THEN game_id END) as null_team_games,
    -- Name resolution diagnostics
    COUNT(*) as total_players,
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_players,
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END) as resolved_inactive,
    ROUND(SAFE_DIVIDE(
      COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END),
      COUNT(CASE WHEN player_status = 'inactive' THEN 1 END)
    ) * 100, 2) as resolution_rate_pct
  FROM gamebook_with_season
  WHERE season IS NOT NULL
),

-- Count games and players per team
team_stats AS (
  SELECT
    season,
    player_team as team,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    COUNT(DISTINCT game_id) as games,
    COUNT(*) as total_player_records,
    COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_players,
    COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as inactive_players,
    COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp_players,
    -- Name resolution for inactive players
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'resolved' THEN 1 END) as inactive_resolved,
    COUNT(CASE WHEN player_status = 'inactive' AND name_resolution_status = 'not_found' THEN 1 END) as inactive_not_found
  FROM gamebook_with_season
  WHERE season IS NOT NULL
  GROUP BY season, player_team, is_playoffs
),

-- Check for games with unusually low player counts
low_player_games AS (
  SELECT
    season,
    player_team as team,
    COUNT(DISTINCT game_id) as games_with_low_players
  FROM (
    SELECT
      CASE
        WHEN game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
        WHEN game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
        WHEN game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
        WHEN game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
      END as season,
      game_id,
      team_abbr as player_team,
      COUNT(*) as players_in_game
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date BETWEEN '2021-10-19' AND '2025-06-20'
    GROUP BY season, game_id, player_team
    HAVING COUNT(*) < 25
  )
  WHERE season IS NOT NULL
  GROUP BY season, team
)

-- Output diagnostics first
SELECT
  row_type,
  CAST(total_games AS STRING) as season,
  'DIAGNOSTICS' as team,
  CAST(null_playoff_flag_games AS STRING) as games,
  CAST(failed_join_games AS STRING) as total_players,
  CAST(null_team_games AS STRING) as active_players,
  CAST(inactive_players AS STRING) as inactive_players,
  CAST(resolved_inactive AS STRING) as resolved_inactive,
  CONCAT(CAST(resolution_rate_pct AS STRING), '%') as resolution_rate,
  'All diagnostic counts should be 0 except resolution_rate (target: ≥98.5%)' as notes
FROM diagnostics

UNION ALL

-- Then team stats by season/team (aggregated across regular + playoffs)
SELECT
  'TEAM' as row_type,
  t.season,
  t.team,
  CAST(SUM(t.games) AS STRING) as games,
  CAST(SUM(t.total_player_records) AS STRING) as total_players,
  CAST(SUM(t.active_players) AS STRING) as active_players,
  CAST(SUM(t.inactive_players) AS STRING) as inactive_players,
  CAST(SUM(t.inactive_resolved) AS STRING) as resolved_inactive,
  CASE 
    WHEN SUM(t.inactive_players) > 0 
    THEN CONCAT(CAST(ROUND(SAFE_DIVIDE(SUM(t.inactive_resolved), SUM(t.inactive_players)) * 100, 1) AS STRING), '%')
    ELSE 'N/A'
  END as resolution_rate,
  CASE
    -- Check regular season game count
    WHEN SUM(CASE WHEN t.is_playoffs = FALSE THEN t.games ELSE 0 END) < 82 THEN '⚠️ Missing games'
    WHEN SUM(CASE WHEN t.is_playoffs = FALSE THEN t.games ELSE 0 END) > 82 THEN '⚠️ Too many games'
    -- Check if team has games with low player counts
    WHEN COALESCE(l.games_with_low_players, 0) > 0 
      THEN CONCAT('⚠️ ', CAST(l.games_with_low_players AS STRING), ' games with <25 players')
    ELSE ''
  END as notes
FROM team_stats t
LEFT JOIN low_player_games l 
  ON t.season = l.season AND t.team = l.team
GROUP BY t.season, t.team, l.games_with_low_players
ORDER BY
  row_type,
  season,
  team;