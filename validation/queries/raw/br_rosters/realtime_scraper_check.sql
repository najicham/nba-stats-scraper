-- ============================================================================
-- File: validation/queries/raw/br_rosters/realtime_scraper_check.sql
-- Purpose: Real-time scraper health monitoring for roster updates
-- Usage: Run during season to verify scraper is running and data is fresh
-- ============================================================================
-- Instructions:
--   1. Run when investigating scraper issues
--   2. During season, expect daily updates (last_scraped within 24h)
--   3. During offseason, scraper may not run for weeks (NORMAL)
-- ============================================================================
-- Expected Results:
--   - During season: "✅ Scraper healthy" with recent last_scraped dates
--   - During offseason: May show "⚪" status (expected)
--   - Alert on "❌ CRITICAL" during season
-- ============================================================================

WITH
-- Current season (adjust when new season starts)
current_season AS (
  SELECT 2024 as season_year, '2024-25' as season_display
),

-- Most recent roster update
latest_scrape AS (
  SELECT
    MAX(last_scraped_date) as most_recent_scrape,
    COUNT(DISTINCT team_abbrev) as teams_in_latest,
    COUNT(DISTINCT player_full_name) as players_in_latest
  FROM `nba-props-platform.nba_raw.br_rosters_current` r
  CROSS JOIN current_season c
  WHERE r.season_year = c.season_year
    AND r.last_scraped_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),

-- Teams updated today
today_updates AS (
  SELECT
    COUNT(DISTINCT team_abbrev) as teams_today,
    COUNT(DISTINCT player_full_name) as players_today,
    COUNT(DISTINCT CASE WHEN first_seen_date = CURRENT_DATE() THEN player_full_name END) as new_today
  FROM `nba-props-platform.nba_raw.br_rosters_current` r
  CROSS JOIN current_season c
  WHERE r.season_year = c.season_year
    AND r.last_scraped_date = CURRENT_DATE()
)

SELECT
  CURRENT_DATE() as check_date,
  CURRENT_TIMESTAMP() as check_timestamp,
  (SELECT season_display FROM current_season) as season,
  l.most_recent_scrape,
  DATE_DIFF(CURRENT_DATE(), l.most_recent_scrape, DAY) as days_since_scrape,
  l.teams_in_latest,
  l.players_in_latest,
  t.teams_today,
  t.players_today,
  t.new_today,
  CASE
    WHEN l.most_recent_scrape = CURRENT_DATE() THEN '✅ Scraper ran today'
    WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_scrape, DAY) = 1 THEN '✅ Scraper healthy (yesterday)'
    WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_scrape, DAY) BETWEEN 2 AND 7 THEN '⚠️ Scraper stale (check logs)'
    WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_scrape, DAY) > 7 
      AND EXTRACT(MONTH FROM CURRENT_DATE()) BETWEEN 10 AND 6 THEN '❌ CRITICAL: Scraper down during season'
    WHEN DATE_DIFF(CURRENT_DATE(), l.most_recent_scrape, DAY) > 7 
      AND EXTRACT(MONTH FROM CURRENT_DATE()) BETWEEN 7 AND 9 THEN '⚪ Offseason - scraper idle (expected)'
    ELSE '⚪ No recent scrapes'
  END as status
FROM latest_scrape l
CROSS JOIN today_updates t;
