-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/date_coverage_analysis.sql
-- Purpose: Analyze ESPN scoreboard sparse backup coverage patterns
-- Usage: Understand which dates have ESPN data (backup source, not complete)
-- ============================================================================
-- Expected Results:
--   - ~895 dates with data across 3.75 seasons (sparse is NORMAL)
--   - ~6 games per date on average (backup collection pattern)
--   - Identifies large gaps (offseason, collection issues)
-- ============================================================================

WITH 
-- Overall coverage summary
coverage_summary AS (
  SELECT 
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(DISTINCT game_date) as total_dates_with_data,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_id) as unique_games,
    ROUND(COUNT(*) / COUNT(DISTINCT game_date), 1) as avg_games_per_date
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
),

-- Season-level coverage
season_coverage AS (
  SELECT 
    season_year,
    COUNT(*) as games,
    COUNT(DISTINCT game_date) as dates_with_data,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    ROUND(COUNT(*) / COUNT(DISTINCT game_date), 1) as avg_games_per_date
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
  GROUP BY season_year
),

-- Monthly coverage pattern
monthly_coverage AS (
  SELECT 
    FORMAT_DATE('%Y-%m', game_date) as year_month,
    COUNT(*) as games,
    COUNT(DISTINCT game_date) as dates_with_data,
    ROUND(COUNT(*) / COUNT(DISTINCT game_date), 1) as avg_games_per_date
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
  GROUP BY year_month
  ORDER BY year_month DESC
  LIMIT 12
),

-- Find large gaps (>10 days without data)
date_gaps AS (
  SELECT 
    game_date,
    LEAD(game_date) OVER (ORDER BY game_date) as next_date,
    DATE_DIFF(LEAD(game_date) OVER (ORDER BY game_date), game_date, DAY) as days_gap
  FROM (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_raw.espn_scoreboard`
    WHERE game_date >= '2021-10-19'
  )
)

-- Output: Combined results with proper BigQuery syntax
(
  SELECT 
    '📊 SUMMARY' as section,
    CAST(earliest_date AS STRING) as metric,
    CAST(latest_date AS STRING) as value,
    CONCAT(total_dates_with_data, ' dates') as detail,
    CONCAT(unique_games, ' unique games') as note,
    1 as sort_order
  FROM coverage_summary

  UNION ALL

  SELECT 
    '📊 SUMMARY' as section,
    'Average games/date' as metric,
    CAST(avg_games_per_date AS STRING) as value,
    'Sparse backup collection' as detail,
    'Normal for backup source' as note,
    2 as sort_order
  FROM coverage_summary

  UNION ALL

  -- Output: Season breakdown
  SELECT 
    '📅 BY SEASON' as section,
    CONCAT('Season ', season_year) as metric,
    CAST(games AS STRING) as value,
    CONCAT(dates_with_data, ' dates, ', avg_games_per_date, ' games/date') as detail,
    CONCAT(first_game, ' → ', last_game) as note,
    3 as sort_order
  FROM season_coverage

  UNION ALL

  -- Output: Recent months
  SELECT 
    '📈 RECENT MONTHS' as section,
    year_month as metric,
    CAST(games AS STRING) as value,
    CONCAT(dates_with_data, ' dates, ', avg_games_per_date, ' games/date') as detail,
    '' as note,
    4 as sort_order
  FROM monthly_coverage

  UNION ALL

  -- Output: Large gaps
  SELECT 
    '⚠️ LARGE GAPS' as section,
    CAST(game_date AS STRING) as metric,
    CAST(days_gap AS STRING) as value,
    CONCAT('Gap to ', next_date) as detail,
    CASE 
      WHEN days_gap > 100 THEN 'Offseason (expected)'
      WHEN days_gap > 30 THEN 'Long gap - investigate'
      ELSE 'Medium gap - check'
    END as note,
    5 as sort_order
  FROM date_gaps
  WHERE days_gap > 10

  ORDER BY sort_order, section, metric
);