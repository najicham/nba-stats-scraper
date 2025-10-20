-- File: validation/queries/raw/espn_rosters/roster_date_distribution.sql
-- ============================================================================
-- Purpose: Find what dates are actually stored in espn_team_rosters
-- Usage: Diagnose why todays_freshness_check shows 0 records
-- ============================================================================
-- Expected Results:
--   - Shows all roster_date values with record counts
--   - Helps identify if scraper is using a different date than expected
--   - Common issue: Scraper uses ESPN's "as of" date vs current date
-- ============================================================================

WITH
date_summary AS (
  SELECT
    roster_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT team_abbr) as teams,
    COUNT(DISTINCT player_lookup) as players,
    MIN(scrape_timestamp) as first_scrape,
    MAX(scrape_timestamp) as last_scrape,
    FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MIN(scrape_timestamp)) as first_scrape_formatted,
    FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(scrape_timestamp)) as last_scrape_formatted
  FROM `nba-props-platform.nba_raw.espn_team_rosters`
  WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAYS)
  GROUP BY roster_date
)

SELECT
  roster_date,
  FORMAT_DATE('%A', roster_date) as day_of_week,
  total_records,
  teams,
  players,
  first_scrape_formatted as first_scrape,
  last_scrape_formatted as last_scrape,
  DATE_DIFF(CURRENT_DATE(), roster_date, DAY) as days_ago,
  CASE
    WHEN roster_date = CURRENT_DATE() THEN '✅ Today'
    WHEN roster_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) THEN '📅 Yesterday'
    WHEN DATE_DIFF(CURRENT_DATE(), roster_date) <= 7 THEN '📊 This week'
    ELSE '🗓️  Older'
  END as recency
FROM date_summary
ORDER BY roster_date DESC
LIMIT 30;
