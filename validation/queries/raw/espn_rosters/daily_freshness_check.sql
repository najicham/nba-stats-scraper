-- File: validation/queries/raw/espn_rosters/daily_freshness_check.sql
-- ============================================================================
-- Purpose: Daily check to verify ESPN roster data was collected
-- Usage: Run every morning at ~10 AM (after 8 AM scraper completes)
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~10 AM (ESPN scraper runs at 8 AM)
--   2. Set up alerts for status != "✅ Complete"
--   3. No date parameters needed - automatically checks yesterday
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all 30 teams have roster data
--   - status = "🔴 CRITICAL" if no data or missing teams
--   - 15-23 players per team is normal (varies by roster composition)
-- ============================================================================

WITH
-- Check yesterday's roster data (ESPN scraper runs at 8 AM daily)
yesterday_rosters AS (
  SELECT
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
    COUNT(DISTINCT team_abbr) as teams_with_data,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records,
    MIN(scrape_hour) as min_scrape_hour,
    MAX(scrape_hour) as max_scrape_hour,
    ROUND(AVG(CASE WHEN team_abbr IS NOT NULL THEN 1.0 END), 0) as avg_players_per_team
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Get today's data for comparison
today_rosters AS (
  SELECT
    COUNT(DISTINCT team_abbr) as teams_today,
    COUNT(DISTINCT player_lookup) as players_today
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = CURRENT_DATE()
)

SELECT
  y.check_date,
  FORMAT_DATE('%A', y.check_date) as day_of_week,
  COALESCE(y.teams_with_data, 0) as teams_with_data,
  COALESCE(y.unique_players, 0) as unique_players,
  COALESCE(y.total_records, 0) as total_records,
  CASE WHEN y.min_scrape_hour = 8 THEN '✓ 8 AM' ELSE '✗' END as scrape_time,
  t.teams_today as teams_today_preview,
  CASE
    -- Yesterday had no data
    WHEN COALESCE(y.teams_with_data, 0) = 0
      THEN '🔴 CRITICAL: No roster data collected'
    
    -- Yesterday incomplete (missing teams)
    WHEN y.teams_with_data < 30
      THEN CONCAT('🟡 WARNING: Only ', CAST(y.teams_with_data AS STRING), '/30 teams')
    
    -- Yesterday suspicious (too few players)
    WHEN y.unique_players < 450  -- 30 teams × 15 min players
      THEN CONCAT('⚠️  WARNING: Only ', CAST(y.unique_players AS STRING), ' players (expected ~500-650)')
    
    -- Yesterday complete
    WHEN y.teams_with_data = 30 AND y.unique_players >= 450
      THEN '✅ Complete: All 30 teams with roster data'
    
    ELSE '📊 Review: Unusual pattern'
  END as status
FROM yesterday_rosters y
CROSS JOIN today_rosters t;
