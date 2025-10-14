-- ============================================================================
-- File: validation/queries/raw/bdl_standings/weekly_check_last_7_days.sql
-- ============================================================================
-- BDL Standings Weekly Check (Last 7 Days)
-- Purpose: Review past week's standings snapshots for trends and gaps
-- Expected: Daily snapshots with 30 teams each (during NBA season)
-- Run: Weekly on Monday mornings
-- ============================================================================

WITH last_7_days AS (
  SELECT
    date_recorded,
    FORMAT_DATE('%A', date_recorded) as day_of_week,
    COUNT(*) as team_count,
    COUNT(DISTINCT conference) as conferences,
    COUNT(DISTINCT CASE WHEN conference = 'East' THEN team_abbr END) as east_teams,
    COUNT(DISTINCT CASE WHEN conference = 'West' THEN team_abbr END) as west_teams,
    AVG(games_played) as avg_games_played,
    MIN(games_played) as min_games_played,
    MAX(games_played) as max_games_played,
    COUNT(DISTINCT season_year) as distinct_seasons,
    -- Get top team from each conference for context
    STRING_AGG(
      CASE WHEN conference_rank = 1 AND conference = 'East' 
           THEN CONCAT(team_abbr, ' (', CAST(wins AS STRING), '-', CAST(losses AS STRING), ')') 
      END, ', ' LIMIT 1
    ) as east_leader,
    STRING_AGG(
      CASE WHEN conference_rank = 1 AND conference = 'West' 
           THEN CONCAT(team_abbr, ' (', CAST(wins AS STRING), '-', CAST(losses AS STRING), ')') 
      END, ', ' LIMIT 1
    ) as west_leader
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) 
                          AND CURRENT_DATE()
  GROUP BY date_recorded
),

all_dates AS (
  -- Generate all dates in the last 7 days
  SELECT date_val as expected_date
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY), 
    CURRENT_DATE()
  )) as date_val
),

season_context AS (
  SELECT 
    expected_date,
    CASE 
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 10 AND 12 THEN TRUE
      WHEN EXTRACT(MONTH FROM expected_date) BETWEEN 1 AND 6 THEN TRUE
      ELSE FALSE
    END as is_nba_season
  FROM all_dates
)

SELECT
  COALESCE(d.date_recorded, a.expected_date) as date_recorded,
  FORMAT_DATE('%A', COALESCE(d.date_recorded, a.expected_date)) as day_of_week,
  COALESCE(d.team_count, 0) as team_count,
  COALESCE(d.conferences, 0) as conferences,
  COALESCE(d.east_teams, 0) as east_teams,
  COALESCE(d.west_teams, 0) as west_teams,
  ROUND(COALESCE(d.avg_games_played, 0), 1) as avg_games_played,
  d.min_games_played,
  d.max_games_played,
  d.east_leader,
  d.west_leader,
  s.is_nba_season,
  CASE
    -- Perfect snapshot
    WHEN d.team_count = 30 AND d.east_teams = 15 AND d.west_teams = 15
      THEN '✅ Complete'
    
    -- Missing data during offseason (normal)
    WHEN d.team_count IS NULL AND NOT s.is_nba_season
      THEN '⚪ No data (offseason - normal)'
    
    -- Missing data during season (CRITICAL)
    WHEN d.team_count IS NULL AND s.is_nba_season
      THEN '🔴 MISSING: No data during season'
    
    -- Wrong team count
    WHEN d.team_count != 30
      THEN CONCAT('⚠️ Incomplete: ', CAST(d.team_count AS STRING), ' teams')
    
    -- Conference imbalance
    WHEN d.east_teams != 15 OR d.west_teams != 15
      THEN CONCAT('⚠️ Imbalance: E', CAST(d.east_teams AS STRING), 
                  '/W', CAST(d.west_teams AS STRING))
    
    ELSE '✅ Complete'
  END as status

FROM all_dates a
LEFT JOIN last_7_days d ON a.expected_date = d.date_recorded
LEFT JOIN season_context s ON a.expected_date = s.expected_date

ORDER BY date_recorded DESC;

-- Summary Statistics (separate query using same CTE)
WITH last_7_days AS (
  SELECT
    date_recorded,
    FORMAT_DATE('%A', date_recorded) as day_of_week,
    COUNT(*) as team_count,
    COUNT(DISTINCT conference) as conferences,
    COUNT(DISTINCT CASE WHEN conference = 'East' THEN team_abbr END) as east_teams,
    COUNT(DISTINCT CASE WHEN conference = 'West' THEN team_abbr END) as west_teams,
    AVG(games_played) as avg_games_played,
    MIN(games_played) as min_games_played,
    MAX(games_played) as max_games_played,
    COUNT(DISTINCT season_year) as distinct_seasons,
    STRING_AGG(
      CASE WHEN conference_rank = 1 AND conference = 'East' 
           THEN CONCAT(team_abbr, ' (', CAST(wins AS STRING), '-', CAST(losses AS STRING), ')') 
      END, ', ' LIMIT 1
    ) as east_leader,
    STRING_AGG(
      CASE WHEN conference_rank = 1 AND conference = 'West' 
           THEN CONCAT(team_abbr, ' (', CAST(wins AS STRING), '-', CAST(losses AS STRING), ')') 
      END, ', ' LIMIT 1
    ) as west_leader
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) 
                          AND CURRENT_DATE()
  GROUP BY date_recorded
)
SELECT 
  '📊 WEEKLY SUMMARY' as section,
  COUNT(DISTINCT date_recorded) as dates_with_data,
  7 as dates_expected,
  ROUND(COUNT(DISTINCT date_recorded) / 7.0 * 100, 1) as coverage_pct,
  SUM(CASE WHEN team_count = 30 THEN 1 ELSE 0 END) as days_complete,
  SUM(CASE WHEN team_count < 30 AND team_count > 0 THEN 1 ELSE 0 END) as days_incomplete,
  7 - COUNT(DISTINCT date_recorded) as days_missing,
  ROUND(AVG(avg_games_played), 1) as overall_avg_games
FROM last_7_days;
