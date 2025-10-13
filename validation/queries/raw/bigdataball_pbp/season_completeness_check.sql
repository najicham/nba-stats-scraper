-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/season_completeness_check.sql
-- ============================================================================
-- Purpose: Comprehensive season validation for BigDataBall play-by-play data
-- Usage: Run after backfills or to verify historical data integrity
-- ============================================================================
-- Expected Results:
--   - DIAGNOSTICS row should show 0 for null_playoff, failed_joins, null_teams
--   - Regular season: ~1,230 games per season with balanced event counts
--   - Playoffs: Variable games based on series length
--   - Event counts: ~400-600 total per game (reasonable range, varies by OT)
--   - Shot coverage: ~80-100 shot events per game
--   - Lineup coverage: 10 players per possession (5 home + 5 away)
-- ============================================================================

WITH
pbp_with_season_info AS (
  SELECT
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    p.event_sequence,
    p.event_type,
    p.shot_made,
    p.original_x,
    p.original_y,
    p.away_player_1_lookup,
    p.home_player_1_lookup,
    s.is_playoffs,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_id as schedule_game_id,
    '2024-25' as season  -- Only one season in BigDataBall data
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play` p
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON p.game_date = s.game_date
    AND (p.home_team_abbr = s.home_team_tricode OR p.away_team_abbr = s.away_team_tricode)
  WHERE p.game_date BETWEEN '2024-10-22' AND '2025-06-22'
    AND s.game_date BETWEEN '2024-10-22' AND '2025-06-22'
),

-- Diagnostic checks for data quality
diagnostics AS (
  SELECT
    'DIAGNOSTICS' as row_type,
    COUNT(DISTINCT game_id) as total_games,
    COUNT(DISTINCT CASE WHEN is_playoffs IS NULL THEN game_id END) as null_playoff_flag_games,
    COUNT(DISTINCT CASE WHEN schedule_game_id IS NULL THEN game_id END) as failed_join_games,
    COUNT(DISTINCT CASE WHEN home_team_abbr IS NULL THEN game_id END) as null_team_games,
    COUNT(DISTINCT CASE WHEN is_playoffs = TRUE THEN game_id END) as playoff_games_found,
    COUNT(DISTINCT CASE WHEN is_playoffs = FALSE THEN game_id END) as regular_season_games_found,
    COUNT(*) as total_events,
    COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as total_shots,
    COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as shots_with_coordinates
  FROM pbp_with_season_info
  WHERE season IS NOT NULL
),

-- Get event counts per game first, before aggregating
game_level_stats AS (
  SELECT
    season,
    home_team_abbr,
    away_team_abbr,
    game_id,
    is_playoffs,
    COUNT(*) as events_in_game,
    COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shots_in_game,
    COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as shots_with_coords,
    COUNT(DISTINCT away_player_1_lookup) + COUNT(DISTINCT home_player_1_lookup) as unique_players,
    MIN(event_sequence) as first_sequence,
    MAX(event_sequence) as last_sequence
  FROM pbp_with_season_info
  WHERE season IS NOT NULL
  GROUP BY season, home_team_abbr, away_team_abbr, game_id, is_playoffs
),

-- Aggregate to team level (count BOTH home and away games)
team_games AS (
  SELECT
    season,
    team_abbr,
    COALESCE(is_playoffs, FALSE) as is_playoffs,
    COUNT(DISTINCT game_id) as games,
    COUNT(DISTINCT CASE WHEN events_in_game > 0 THEN game_id END) as games_with_events,
    ROUND(AVG(events_in_game), 1) as avg_events_per_game,
    MIN(events_in_game) as min_events,
    MAX(events_in_game) as max_events,
    ROUND(AVG(shots_in_game), 1) as avg_shots_per_game,
    ROUND(AVG(shots_with_coords * 100.0 / NULLIF(shots_in_game, 0)), 1) as pct_shots_with_coords
  FROM (
    -- Home games
    SELECT season, home_team_abbr as team_abbr, game_id, is_playoffs, 
           events_in_game, shots_in_game, shots_with_coords
    FROM game_level_stats
    UNION ALL
    -- Away games
    SELECT season, away_team_abbr as team_abbr, game_id, is_playoffs,
           events_in_game, shots_in_game, shots_with_coords
    FROM game_level_stats
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
  CAST(total_events AS STRING) as total_events,
  CAST(total_shots AS STRING) as avg_events,
  CAST(shots_with_coordinates AS STRING) as min_events,
  '' as max_events,
  'Check: null counts should be 0, shots should have coords' as notes
FROM diagnostics

UNION ALL

-- Then team stats
SELECT
  'TEAM' as row_type,
  season,
  team_abbr as team,
  CAST(SUM(CASE WHEN is_playoffs = FALSE THEN games ELSE 0 END) AS STRING) as reg_games,
  CAST(SUM(CASE WHEN is_playoffs = TRUE THEN games ELSE 0 END) AS STRING) as playoff_games,
  CAST(MAX(games_with_events) AS STRING) as total_events,
  CAST(MAX(CASE WHEN is_playoffs = FALSE THEN avg_events_per_game END) AS STRING) as avg_events,
  CAST(MIN(CASE WHEN is_playoffs = FALSE THEN min_events END) AS STRING) as min_events,
  CAST(MAX(CASE WHEN is_playoffs = FALSE THEN max_events END) AS STRING) as max_events,
  CASE
    WHEN SUM(CASE WHEN is_playoffs = FALSE THEN games ELSE 0 END) < 82 THEN '⚠️ Missing regular season games'
    WHEN MIN(CASE WHEN is_playoffs = FALSE THEN min_events END) < 300 THEN '⚠️ Suspiciously low event count'
    WHEN MAX(CASE WHEN is_playoffs = FALSE THEN pct_shots_with_coords END) < 70 THEN '⚠️ Poor coordinate coverage'
    ELSE ''
  END as notes
FROM team_games
GROUP BY season, team_abbr
ORDER BY
  row_type DESC,  -- DIAGNOSTICS first, then TEAM
  season DESC,    -- Most recent season first
  CAST(playoff_games AS INT64) DESC,  -- Teams with more playoff games first
  team;