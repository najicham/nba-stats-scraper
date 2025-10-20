-- File: validation/queries/raw/espn_rosters/todays_freshness_check.sql
-- ============================================================================
-- Purpose: Immediate check to verify TODAY'S roster data was collected
-- Usage: Run immediately after scraping to validate the scrape worked
-- ============================================================================
-- Instructions:
--   1. Run this RIGHT AFTER scraping completes
--   2. Use daily_freshness_check.sql for next-day monitoring
--   3. This checks if data landed in BigQuery after scraping
-- ============================================================================
-- Expected Results:
--   - status = "✅ Complete" when all 30 teams have roster data for today
--   - status = "🔴 CRITICAL" if no data or missing teams
--   - 15-23 players per team is normal (varies by roster composition)
-- ============================================================================

WITH
-- Check today's roster data (just scraped)
today_rosters AS (
  SELECT
    CURRENT_DATE() as check_date,
    COUNT(DISTINCT team_abbr) as teams_with_data,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(*) as total_records,
    MIN(scrape_hour) as min_scrape_hour,
    MAX(scrape_hour) as max_scrape_hour
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date = CURRENT_DATE()
)

SELECT
  t.check_date,
  FORMAT_DATE('%A', t.check_date) as day_of_week,
  COALESCE(t.teams_with_data, 0) as teams_with_data,
  COALESCE(t.unique_players, 0) as unique_players,
  COALESCE(t.total_records, 0) as total_records,
  CASE 
    WHEN t.min_scrape_hour IS NOT NULL 
    THEN CONCAT('✓ Hour ', CAST(t.min_scrape_hour AS STRING))
    ELSE '✗ No scrape time'
  END as scrape_time,
  CASE
    -- Today has no data
    WHEN COALESCE(t.teams_with_data, 0) = 0
      THEN '🔴 CRITICAL: No roster data collected today'

    -- Today incomplete (missing teams)
    WHEN t.teams_with_data < 30
      THEN CONCAT('🟡 WARNING: Only ', CAST(t.teams_with_data AS STRING), '/30 teams collected')

    -- Today suspicious (too few players)
    WHEN t.unique_players < 450  -- 30 teams × 15 min players
      THEN CONCAT('⚠️  WARNING: Only ', CAST(t.unique_players AS STRING), ' players (expected ~500-650)')

    -- Today complete
    WHEN t.teams_with_data = 30 AND t.unique_players >= 450
      THEN '✅ Complete: All 30 teams with roster data collected today'

    ELSE '📊 Review: Unusual pattern'
  END as status
FROM today_rosters t;
