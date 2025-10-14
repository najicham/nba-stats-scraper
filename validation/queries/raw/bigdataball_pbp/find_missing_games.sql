-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/find_missing_games.sql
-- ============================================================================
-- Purpose: Identify specific games missing from BigDataBall play-by-play
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- NOTE: BigDataBall game_id format should match schedule format
-- If not, we join on date + teams like we did for BDL
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to investigate scraper issues or create backfill plan
-- ============================================================================
-- Expected Results:
--   - List of specific games (date, matchup) that need play-by-play data
--   - Empty result = all regular season games present
-- ============================================================================

WITH
-- Get all regular season games from schedule
all_scheduled_games AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_name as home_team,
    s.home_team_tricode,
    s.away_team_name as away_team,
    s.away_team_tricode,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- Regular season only (no future games)
    AND s.is_playoffs = FALSE
    AND s.game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- Partition filter
),

-- Get all games we have play-by-play for
pbp_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as event_count
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- Match schedule range
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
)

-- Find games in schedule but not in play-by-play
-- JOIN ON DATE + TEAMS (safe approach in case game_id formats differ)
SELECT
  s.game_date,
  s.home_team,
  s.away_team,
  s.matchup,
  COALESCE(p.event_count, 0) as event_count,
  CASE
    WHEN p.game_date IS NULL THEN '❌ MISSING COMPLETELY'
    WHEN p.event_count < 350 THEN '🔴 CRITICALLY LOW EVENTS'
    ELSE '✅ Present'
  END as status,
  s.game_id as schedule_game_id,
  p.game_id as pbp_game_id
FROM all_scheduled_games s
LEFT JOIN pbp_games p
  ON s.game_date = p.game_date
  AND s.home_team_tricode = p.home_team_abbr
  AND s.away_team_tricode = p.away_team_abbr
WHERE p.game_date IS NULL OR p.event_count < 350
ORDER BY s.game_date;

-- Interpretation:
-- ❌ MISSING COMPLETELY: No play-by-play data at all
-- 🔴 CRITICALLY LOW: <350 events (incomplete game data)