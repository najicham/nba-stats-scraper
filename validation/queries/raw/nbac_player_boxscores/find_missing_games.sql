-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/find_missing_games.sql
-- Purpose: Identify specific games missing from NBA.com player box scores
-- Usage: Run when season_completeness_check shows teams with <82 games
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- This query is ready to execute once data arrives
-- ============================================================================
-- Key Advantage: NBA.com uses same game_id format as schedule (direct join)
-- Format: YYYYMMDD_AWAY_HOME (e.g., "20241022_BOS_NYK")
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query
--   3. Use results to investigate scraper issues or create backfill plan
-- ============================================================================
-- Expected Results:
--   - List of specific games (date, matchup) that need to be scraped
--   - Empty result = all regular season games present
--   - Should match BDL missing games closely
-- ============================================================================

WITH
-- Check if table has any data
data_check AS (
  SELECT COUNT(*) as total_records
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= '2024-10-22'  -- Current season
),

-- Get all regular season games from schedule
all_scheduled_games AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_name as home_team,
    s.home_team_tricode,
    s.away_team_name as away_team,
    s.away_team_tricode,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup,
    s.season_nba_format
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.game_date BETWEEN '2024-10-22' AND '2025-04-20'  -- UPDATE: Regular season only
    AND s.is_playoffs = FALSE
    AND s.game_date BETWEEN '2024-10-22' AND '2025-04-20'  -- Partition filter
),

-- Get all games we have box scores for
boxscore_games AS (
  SELECT DISTINCT
    game_id,
    game_date,
    COUNT(DISTINCT player_lookup) as player_count
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-20'  -- UPDATE: Match schedule range
  GROUP BY game_id, game_date
)

-- No data message (only show if table is empty)
SELECT
  CURRENT_DATE() as report_date,
  '⚪ No Data Yet' as status,
  'NBA.com player boxscore table is empty - awaiting season start' as message,
  NULL as game_date,
  NULL as matchup,
  NULL as season,
  NULL as schedule_game_id
FROM data_check
WHERE total_records = 0

UNION ALL

-- Find games in schedule but not in box scores
SELECT
  CURRENT_DATE() as report_date,
  '❌ Missing' as status,
  'Game has no player boxscore data' as message,
  s.game_date,
  s.matchup,
  s.season_nba_format as season,
  s.game_id as schedule_game_id
FROM all_scheduled_games s
LEFT JOIN boxscore_games b
  ON s.game_id = b.game_id  -- Direct join on game_id (formats match!)
WHERE b.game_id IS NULL
  AND (SELECT total_records FROM data_check) > 0

UNION ALL

-- Find games with suspiciously low player counts
SELECT
  CURRENT_DATE() as report_date,
  '⚠️ Incomplete' as status,
  CONCAT('Only ', CAST(b.player_count AS STRING), ' players found (expected ~30)') as message,
  s.game_date,
  s.matchup,
  s.season_nba_format as season,
  s.game_id as schedule_game_id
FROM all_scheduled_games s
INNER JOIN boxscore_games b
  ON s.game_id = b.game_id
WHERE b.player_count < 20  -- Suspiciously low
  AND (SELECT total_records FROM data_check) > 0

ORDER BY
  CASE status
    WHEN '⚪ No Data Yet' THEN 1
    WHEN '❌ Missing' THEN 2
    WHEN '⚠️ Incomplete' THEN 3
  END,
  game_date;