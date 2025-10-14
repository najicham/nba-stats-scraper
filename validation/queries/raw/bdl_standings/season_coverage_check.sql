-- ============================================================================
-- File: validation/queries/raw/bdl_standings/season_coverage_check.sql
-- ============================================================================
-- BDL Standings Season Coverage Check
-- Purpose: Comprehensive season validation by month
-- Expected: Daily coverage October-June, sparse July-September
-- Run: After backfills, monthly during season
-- ============================================================================

WITH daily_stats AS (
  SELECT
    season_year,
    season_display,
    date_recorded,
    COUNT(*) as team_count_per_day,
    COUNT(DISTINCT CASE WHEN conference = 'East' THEN team_abbr END) as east_count,
    COUNT(DISTINCT CASE WHEN conference = 'West' THEN team_abbr END) as west_count,
    MIN(games_played) as min_games,
    MAX(games_played) as max_games,
    AVG(games_played) as avg_games
  FROM `nba-props-platform.nba_raw.bdl_standings`
  GROUP BY season_year, season_display, date_recorded
),

monthly_coverage AS (
  SELECT
    season_year,
    season_display,
    EXTRACT(YEAR FROM date_recorded) as year,
    EXTRACT(MONTH FROM date_recorded) as month,
    FORMAT_DATE('%Y-%m', date_recorded) as year_month,
    FORMAT_DATE('%B %Y', date_recorded) as month_name,
    COUNT(DISTINCT date_recorded) as dates_with_data,
    COUNT(*) as total_records,
    COUNT(DISTINCT date_recorded) as unique_dates,
    ROUND(AVG(team_count_per_day), 1) as avg_teams_per_day,
    MIN(date_recorded) as first_date,
    MAX(date_recorded) as last_date,
    AVG(east_count) as avg_east_teams,
    AVG(west_count) as avg_west_teams,
    MIN(min_games) as season_min_games,
    MAX(max_games) as season_max_games,
    ROUND(AVG(avg_games), 1) as avg_games_in_month
  FROM daily_stats
  GROUP BY season_year, season_display, year, month, year_month, month_name
),

month_expectations AS (
  SELECT
    year_month,
    month,
    CASE
      WHEN month IN (10, 11, 12, 1, 2, 3) THEN 
        EXTRACT(DAY FROM LAST_DAY(PARSE_DATE('%Y-%m', year_month)))
      WHEN month = 4 THEN 25
      WHEN month IN (5, 6) THEN 15
      ELSE 3
    END as expected_days,
    CASE
      WHEN month BETWEEN 10 AND 12 THEN 'Regular Season'
      WHEN month BETWEEN 1 AND 3 THEN 'Regular Season'
      WHEN month = 4 THEN 'Regular Season + Playoffs'
      WHEN month IN (5, 6) THEN 'Playoffs'
      ELSE 'Offseason'
    END as season_phase
  FROM monthly_coverage
)

SELECT
  c.season_display,
  c.month_name,
  e.season_phase,
  c.dates_with_data,
  e.expected_days,
  ROUND(c.dates_with_data / e.expected_days * 100, 1) as coverage_pct,
  c.unique_dates,
  c.avg_teams_per_day,
  c.avg_east_teams,
  c.avg_west_teams,
  c.avg_games_in_month,
  c.first_date,
  c.last_date,
  CASE
    WHEN c.avg_teams_per_day = 30 AND c.unique_dates = c.dates_with_data
         AND c.dates_with_data >= e.expected_days * 0.9
      THEN '✅ Excellent'
    WHEN c.dates_with_data >= e.expected_days * 0.9 
         AND c.avg_teams_per_day >= 29
      THEN '✅ Good'
    WHEN c.dates_with_data >= e.expected_days * 0.7
      THEN '⚠️ Acceptable'
    WHEN e.season_phase IN ('Regular Season', 'Playoffs', 'Regular Season + Playoffs')
         AND c.dates_with_data < e.expected_days * 0.7
      THEN '🔴 Poor Coverage'
    WHEN e.season_phase = 'Offseason'
      THEN '⚪ Offseason'
    ELSE '⚠️ Review Needed'
  END as status,
  CASE
    WHEN c.avg_teams_per_day < 30 OR c.unique_dates < c.dates_with_data
      THEN '⚠️ Incomplete team coverage'
    WHEN c.avg_east_teams != 15 OR c.avg_west_teams != 15
      THEN '⚠️ Conference imbalance'
    WHEN c.dates_with_data < e.expected_days * 0.5 
         AND e.season_phase IN ('Regular Season', 'Playoffs')
      THEN '🚨 Missing >50% of days'
    ELSE '✅ Data quality good'
  END as data_quality

FROM monthly_coverage c
JOIN month_expectations e ON c.year_month = e.year_month

ORDER BY c.season_year DESC, c.year, c.month DESC;

-- Overall Season Summary
WITH season_summary AS (
  SELECT
    season_display,
    MIN(date_recorded) as season_start,
    MAX(date_recorded) as season_end,
    COUNT(DISTINCT date_recorded) as total_dates_with_data,
    COUNT(*) as total_team_records,
    COUNT(DISTINCT team_abbr) as unique_teams_seen,
    ROUND(AVG(games_played), 1) as avg_games_per_team,
    MIN(games_played) as min_games,
    MAX(games_played) as max_games
  FROM `nba-props-platform.nba_raw.bdl_standings`
  GROUP BY season_display
)
SELECT
  '📊 SEASON SUMMARY' as section,
  season_display,
  season_start,
  season_end,
  total_dates_with_data,
  total_team_records,
  unique_teams_seen,
  avg_games_per_team,
  min_games,
  max_games
FROM season_summary
ORDER BY season_display DESC;
