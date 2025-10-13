-- ============================================================================
-- File: validation/queries/raw/br_rosters/weekly_check_last_7_days.sql
-- Purpose: Weekly trend analysis of roster updates and changes
-- Usage: Run Monday mornings to review past week's roster activity
-- ============================================================================
-- Instructions:
--   1. Schedule weekly (Monday 9 AM) during NBA season
--   2. Review trends in roster changes and scraper runs
--   3. No configuration needed - automatically checks last 7 days
-- ============================================================================
-- Expected Results:
--   - Daily scraper runs during season (1 per day typical)
--   - Roster changes vary by day (trade deadline = spike)
--   - Most days show 0 new players unless trades/signings occurred
-- ============================================================================

WITH
-- Current season (adjust when new season starts)
current_season AS (
  SELECT 2024 as season_year, '2024-25' as season_display
),

-- Last 7 days of roster data
last_7_days AS (
  SELECT
    r.last_scraped_date as scrape_date,
    r.team_abbrev,
    r.player_full_name,
    r.player_lookup,
    r.first_seen_date
  FROM `nba-props-platform.nba_raw.br_rosters_current` r
  CROSS JOIN current_season c
  WHERE r.season_year = c.season_year
    AND r.last_scraped_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
),

-- Daily summary
daily_summary AS (
  SELECT
    scrape_date,
    COUNT(DISTINCT team_abbrev) as teams_updated,
    COUNT(DISTINCT player_full_name) as players_updated,
    COUNT(DISTINCT CASE WHEN first_seen_date = scrape_date THEN player_full_name END) as new_players,
    STRING_AGG(
      DISTINCT CASE WHEN first_seen_date = scrape_date 
      THEN CONCAT(team_abbrev, ':', player_full_name) 
      END, ', '
      ORDER BY CASE WHEN first_seen_date = scrape_date 
      THEN CONCAT(team_abbrev, ':', player_full_name) 
      END
    ) as new_player_details
  FROM last_7_days
  GROUP BY scrape_date
),

-- Fill in missing dates (days without scraper runs)
date_series AS (
  SELECT date FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY),
    CURRENT_DATE(),
    INTERVAL 1 DAY
  )) as date
)

SELECT
  ds.date as check_date,
  FORMAT_DATE('%A', ds.date) as day_of_week,
  COALESCE(d.teams_updated, 0) as teams_updated,
  COALESCE(d.players_updated, 0) as players_updated,
  COALESCE(d.new_players, 0) as new_players,
  COALESCE(d.new_player_details, '') as changes,
  CASE
    WHEN d.scrape_date IS NULL THEN '⚪ No scraper run'
    WHEN d.new_players = 0 THEN '✅ No changes'
    WHEN d.new_players BETWEEN 1 AND 3 THEN '✅ Normal changes'
    WHEN d.new_players > 3 THEN '⚠️ Multiple changes'
    ELSE ''
  END as status
FROM date_series ds
LEFT JOIN daily_summary d ON ds.date = d.scrape_date
ORDER BY ds.date DESC;
