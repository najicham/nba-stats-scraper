-- ============================================================================
-- File: validation/queries/raw/bdl_standings/daily_check_yesterday.sql
-- ============================================================================
-- BDL Standings Daily Check (Yesterday)
-- Purpose: Verify yesterday's standings snapshot was captured successfully
-- Expected: 30 teams (15 East, 15 West) per day during NBA season
-- Run: Daily at 9 AM PT
-- ============================================================================

WITH yesterday_data AS (
  SELECT
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
    COUNT(*) as team_count,
    COUNT(DISTINCT conference) as conferences,
    COUNT(DISTINCT CASE WHEN conference = 'East' THEN team_abbr END) as east_teams,
    COUNT(DISTINCT CASE WHEN conference = 'West' THEN team_abbr END) as west_teams,
    COUNT(DISTINCT season_year) as seasons,
    AVG(games_played) as avg_games_played,
    MIN(date_recorded) as data_date
  FROM `nba-props-platform.nba_raw.bdl_standings`
  WHERE date_recorded = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

season_check AS (
  SELECT
    -- NBA season runs October through June
    CASE 
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) BETWEEN 10 AND 12 THEN TRUE  -- Oct-Dec
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) BETWEEN 1 AND 6 THEN TRUE    -- Jan-Jun
      ELSE FALSE  -- Jul-Sep (offseason)
    END as is_nba_season
),

-- Always ensure we have a row by using IFNULL/COALESCE
result AS (
  SELECT
    COALESCE(d.check_date, DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) as check_date,
    COALESCE(d.team_count, 0) as team_count,
    COALESCE(d.conferences, 0) as conferences,
    COALESCE(d.east_teams, 0) as east_teams,
    COALESCE(d.west_teams, 0) as west_teams,
    COALESCE(ROUND(d.avg_games_played, 1), 0.0) as avg_games_played,
    COALESCE(d.seasons, 0) as distinct_seasons,
    s.is_nba_season
  FROM season_check s
  LEFT JOIN yesterday_data d ON TRUE  -- Cross join, always returns a row
)

SELECT
  check_date,
  team_count,
  conferences,
  east_teams,
  west_teams,
  avg_games_played,
  distinct_seasons,
  is_nba_season,
  CASE
    -- Perfect snapshot
    WHEN team_count = 30 AND east_teams = 15 AND west_teams = 15 
      THEN '✅ Complete'
    
    -- Offseason with no data (normal)
    WHEN team_count = 0 AND NOT is_nba_season 
      THEN '⚪ No data (offseason - normal)'
    
    -- During season with no data (CRITICAL)
    WHEN team_count = 0 AND is_nba_season 
      THEN '🔴 CRITICAL: No data during NBA season'
    
    -- Wrong team count
    WHEN team_count != 30 
      THEN CONCAT('⚠️ WARNING: Expected 30 teams, got ', CAST(team_count AS STRING))
    
    -- Conference imbalance
    WHEN east_teams != 15 OR west_teams != 15
      THEN CONCAT('⚠️ WARNING: Conference imbalance (East: ', 
                  CAST(east_teams AS STRING), ', West: ', 
                  CAST(west_teams AS STRING), ')')
    
    -- Multiple seasons mixed (shouldn't happen)
    WHEN distinct_seasons > 1
      THEN '⚠️ WARNING: Multiple seasons in same date'
    
    ELSE '✅ Complete'
  END as status,
  
  -- Actionable recommendations
  CASE
    WHEN team_count = 0 AND is_nba_season 
      THEN '🚨 ACTION: Run scraper immediately! Check scraper logs and GCS bucket.'
    
    WHEN team_count != 30 AND team_count > 0
      THEN 'ACTION: Check scraper logs for partial data. Re-run scraper and processor.'
    
    WHEN east_teams != 15 OR west_teams != 15
      THEN 'ACTION: Check team abbreviation mapping and conference assignments.'
    
    WHEN team_count = 0 AND NOT is_nba_season
      THEN 'No action needed - offseason.'
    
    ELSE 'No action needed - data looks good!'
  END as recommendation

FROM result;