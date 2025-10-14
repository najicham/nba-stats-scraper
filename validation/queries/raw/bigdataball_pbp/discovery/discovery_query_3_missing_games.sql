-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/discovery/discovery_query_3_missing_games.sql
-- ============================================================================
-- BigDataBall Play-by-Play Discovery Query 3: Missing Game Days
-- Purpose: Cross-check against schedule to find missing dates
-- ============================================================================
-- IMPORTANT: Update date range based on Discovery Query 1 results!
-- ============================================================================

WITH all_scheduled_games AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'  -- Actual season dates from Discovery Q1
    AND is_playoffs = FALSE
    AND game_date BETWEEN '2024-10-22' AND '2025-06-22'  -- Partition filter
),
actual_data_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-06-22'  -- Match schedule range
)
SELECT 
  g.game_date,
  FORMAT_DATE('%A', g.game_date) as day_of_week,
  '❌ MISSING FROM PLAY-BY-PLAY' as status
FROM all_scheduled_games g
LEFT JOIN actual_data_dates a ON g.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY g.game_date;

-- Expected Results:
-- Empty = Perfect coverage
-- Any results = Missing game dates that need investigation