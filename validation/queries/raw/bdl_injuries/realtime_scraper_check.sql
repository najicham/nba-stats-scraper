-- ============================================================================
-- File: validation/queries/raw/bdl_injuries/realtime_scraper_check.sql
-- Purpose: Real-time check if BDL injury scraper is running today
-- Usage: Run anytime during the day to check data freshness
-- ============================================================================
-- Expected Results:
--   - During season: Should see TODAY's data if scraper has run
--   - Shows minutes since last scrape_timestamp
--   - Helps diagnose if scraper is delayed or failed
-- ============================================================================

WITH
-- Check today's data
today_data AS (
  SELECT
    MAX(scrape_timestamp) as last_scrape,
    COUNT(*) as injury_count,
    COUNT(DISTINCT bdl_player_id) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    AVG(parsing_confidence) as avg_confidence
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date = CURRENT_DATE()
),

-- Check yesterday's data for comparison
yesterday_data AS (
  SELECT
    MAX(scrape_timestamp) as last_scrape,
    COUNT(*) as injury_count,
    COUNT(DISTINCT bdl_player_id) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams
  FROM `nba-props-platform.nba_raw.bdl_injuries`
  WHERE scrape_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Season context
season_info AS (
  SELECT
    CASE 
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) IN (7, 8, 9) THEN FALSE
      ELSE TRUE
    END as is_season_active,
    EXTRACT(MONTH FROM CURRENT_DATE()) as current_month
)

SELECT
  CURRENT_DATE() as check_date,
  CURRENT_TIMESTAMP() as check_time,
  s.is_season_active,
  
  -- Today's data
  t.last_scrape as today_last_scrape,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t.last_scrape, MINUTE) as minutes_since_scrape,
  COALESCE(t.injury_count, 0) as today_injury_count,
  COALESCE(t.unique_players, 0) as today_unique_players,
  COALESCE(t.unique_teams, 0) as today_unique_teams,
  ROUND(t.avg_confidence, 3) as today_avg_confidence,
  
  -- Yesterday's data for comparison
  COALESCE(y.injury_count, 0) as yesterday_injury_count,
  COALESCE(y.unique_teams, 0) as yesterday_unique_teams,
  
  -- Status determination
  CASE
    -- Off-season
    WHEN NOT s.is_season_active AND t.last_scrape IS NULL 
      THEN '⚪ Expected: Off-season - no scraper run'
    WHEN NOT s.is_season_active AND t.last_scrape IS NOT NULL
      THEN '✅ Off-season data present'
    
    -- Season active - data present
    WHEN s.is_season_active AND t.last_scrape IS NOT NULL AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t.last_scrape, MINUTE) < 120
      THEN '✅ Fresh: Data < 2 hours old'
    WHEN s.is_season_active AND t.last_scrape IS NOT NULL AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t.last_scrape, MINUTE) < 360
      THEN '⚠️  WARNING: Data 2-6 hours old'
    WHEN s.is_season_active AND t.last_scrape IS NOT NULL
      THEN '🟡 STALE: Data > 6 hours old'
    
    -- Season active - no data
    WHEN s.is_season_active AND t.last_scrape IS NULL AND EXTRACT(HOUR FROM CURRENT_TIMESTAMP()) < 10
      THEN '⚪ Early morning: Scraper may not have run yet'
    WHEN s.is_season_active AND t.last_scrape IS NULL
      THEN '🔴 CRITICAL: Season active - no data today'
    
    ELSE '📊 Review: Unusual pattern'
  END as status,
  
  -- Recommendations
  CASE
    WHEN s.is_season_active AND t.last_scrape IS NULL AND EXTRACT(HOUR FROM CURRENT_TIMESTAMP()) >= 10
      THEN 'Check scraper logs - should have run by now'
    WHEN s.is_season_active AND t.last_scrape IS NOT NULL AND t.injury_count < 10
      THEN 'Very low injury count - verify data quality'
    WHEN s.is_season_active AND t.last_scrape IS NOT NULL AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t.last_scrape, MINUTE) > 360
      THEN 'Data is stale - check if scraper is scheduled correctly'
    ELSE 'No action needed'
  END as recommendation

FROM season_info s
CROSS JOIN today_data t
CROSS JOIN yesterday_data y;
