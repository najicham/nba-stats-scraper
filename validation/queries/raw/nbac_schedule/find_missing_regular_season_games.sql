-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/find_missing_regular_season_games.sql
-- Purpose: Detect patterns of missing regular season games by analyzing team game counts
-- Usage: Run when season_completeness_check shows teams with unusual counts
-- ============================================================================
-- Instructions:
--   1. Update the date range for the season you're checking
--   2. Run the query to see teams with unusual game counts
--   3. Review daily gaps to identify specific missing date ranges
-- ============================================================================
-- Expected Results:
--   - Empty team_gaps = all teams have similar game counts
--   - Empty daily_gaps = consistent game scheduling throughout season
--   - Non-empty results indicate missing data or unusual scheduling
-- ============================================================================

WITH
-- Get all regular season games in date range
regular_season_games AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_team_name,
    away_team_name,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Regular season only
    AND is_regular_season = TRUE
    AND is_playoffs = FALSE
    AND game_date >= '2024-10-22'  -- Partition filter
),

-- Expand to team-game combinations
team_games AS (
  SELECT game_date, home_team_tricode as team, home_team_name as team_name, game_id
  FROM regular_season_games
  
  UNION ALL
  
  SELECT game_date, away_team_tricode as team, away_team_name as team_name, game_id
  FROM regular_season_games
),

-- Count games per team
team_game_counts AS (
  SELECT
    team,
    MAX(team_name) as team_name,
    COUNT(DISTINCT game_id) as games,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as days_span
  FROM team_games
  GROUP BY team
),

-- Calculate league average for comparison
league_average AS (
  SELECT
    AVG(games) as avg_games,
    STDDEV(games) as stddev_games,
    MAX(games) as max_games,
    MIN(games) as min_games
  FROM team_game_counts
),

-- Find teams significantly below/above average
team_gaps AS (
  SELECT
    t.team,
    t.team_name,
    t.games,
    t.first_game,
    t.last_game,
    t.days_span,
    l.avg_games,
    t.games - l.avg_games as games_diff,
    CASE
      WHEN t.games < l.avg_games - 3 THEN '🔴 Significantly below average'
      WHEN t.games > l.avg_games + 3 THEN '🔴 Significantly above average'
      WHEN t.games < l.avg_games - 1 THEN '🟡 Slightly below average'
      WHEN t.games > l.avg_games + 1 THEN '🟡 Slightly above average'
      ELSE '✅ Normal'
    END as status
  FROM team_game_counts t
  CROSS JOIN league_average l
  WHERE ABS(t.games - l.avg_games) > 0.5  -- Only show teams with differences
),

-- Analyze daily game distribution
daily_game_counts AS (
  SELECT
    game_date,
    FORMAT_DATE('%A', game_date) as day_of_week,
    COUNT(DISTINCT game_id) as games
  FROM regular_season_games
  GROUP BY game_date
),

-- Find unusual gaps in schedule (separate CTE for window function)
daily_gaps_with_lag AS (
  SELECT
    game_date,
    day_of_week,
    games,
    LAG(game_date) OVER (ORDER BY game_date) as prev_date,
    DATE_DIFF(game_date, LAG(game_date) OVER (ORDER BY game_date), DAY) as days_since_last
  FROM daily_game_counts
),

daily_gaps AS (
  SELECT
    game_date,
    day_of_week,
    games,
    prev_date,
    days_since_last,
    CASE
      WHEN games = 0 THEN '🔴 No games scheduled'
      WHEN games < 3 THEN '🟡 Unusually few games'
      WHEN days_since_last > 3 THEN '🟡 Large gap in schedule'
      ELSE '✅ Normal'
    END as status
  FROM daily_gaps_with_lag
  WHERE games < 3 OR days_since_last > 3
)

-- Output 1: Team-level analysis
SELECT
  '=== TEAM ANALYSIS ===' as section,
  CAST(NULL AS STRING) as detail1,
  CAST(NULL AS STRING) as detail2,
  CAST(NULL AS STRING) as detail3,
  CAST(NULL AS STRING) as detail4,
  0 as sort_order

UNION ALL

SELECT
  team as section,
  team_name as detail1,
  CONCAT('Games: ', CAST(games AS STRING), ' (avg: ', CAST(ROUND(avg_games, 1) AS STRING), ')') as detail2,
  CONCAT('Diff: ', 
    CASE WHEN games_diff > 0 THEN '+' ELSE '' END,
    CAST(ROUND(games_diff, 1) AS STRING)
  ) as detail3,
  status as detail4,
  1 as sort_order
FROM team_gaps
WHERE status != '✅ Normal'

UNION ALL

-- Output 2: Daily gaps analysis
SELECT
  '' as section,
  CAST(NULL AS STRING) as detail1,
  CAST(NULL AS STRING) as detail2,
  CAST(NULL AS STRING) as detail3,
  CAST(NULL AS STRING) as detail4,
  2 as sort_order

UNION ALL

SELECT
  '=== DAILY GAPS ===' as section,
  CAST(NULL AS STRING) as detail1,
  CAST(NULL AS STRING) as detail2,
  CAST(NULL AS STRING) as detail3,
  CAST(NULL AS STRING) as detail4,
  3 as sort_order

UNION ALL

SELECT
  CAST(game_date AS STRING) as section,
  day_of_week as detail1,
  CONCAT(CAST(games AS STRING), ' games') as detail2,
  CONCAT(CAST(days_since_last AS STRING), ' days since last') as detail3,
  status as detail4,
  4 as sort_order
FROM daily_gaps

ORDER BY sort_order, section;