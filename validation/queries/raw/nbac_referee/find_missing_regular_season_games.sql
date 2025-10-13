-- ============================================================================
-- File: validation/queries/raw/nbac_referee/find_missing_regular_season_games.sql
-- Purpose: Identify specific regular season games missing referee assignments
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to create backfill dates file
-- ============================================================================
-- Expected Results:
--   - List of specific games (date, matchup) that need referee data
--   - Empty result = all regular season games have referee assignments
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
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Regular season only
    AND s.is_playoffs = FALSE
),

-- Get all games we have referee assignments for
ref_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr,
    COUNT(DISTINCT official_code) as official_count
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Match schedule range
  GROUP BY game_date, home_team_abbr, away_team_abbr
)

-- Find games in schedule but not in referee assignments
SELECT
  s.game_date,
  FORMAT_DATE('%A', s.game_date) as day_of_week,
  s.home_team,
  s.away_team,
  s.matchup,
  CASE
    WHEN r.game_date IS NULL THEN '❌ MISSING ALL REFEREE DATA'
    WHEN r.official_count < 3 THEN CONCAT('⚠️ INCOMPLETE: Only ', CAST(r.official_count AS STRING), ' officials')
    ELSE '✅ Has data'
  END as status
FROM all_scheduled_games s
LEFT JOIN ref_games r
  ON s.game_date = r.game_date
  AND s.home_team_tricode = r.home_team_abbr
  AND s.away_team_tricode = r.away_team_abbr
WHERE r.game_date IS NULL  -- Only show missing games
   OR r.official_count < 3  -- Or incomplete assignments
ORDER BY s.game_date;
