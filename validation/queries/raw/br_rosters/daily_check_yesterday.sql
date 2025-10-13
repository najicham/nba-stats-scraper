-- ============================================================================
-- File: validation/queries/raw/br_rosters/daily_check_yesterday.sql
-- Purpose: Daily check for new roster additions or updates from yesterday
-- Usage: Run every morning during NBA season to detect roster changes
-- ============================================================================
-- Instructions:
--   1. Schedule this to run daily at ~9 AM during season (Oct-Jun)
--   2. Set up alerts when new_players > 0 (trades/signings)
--   3. During offseason, expect 0 changes most days
-- ============================================================================
-- Expected Results:
--   - During season: Occasional new players (trades, signings, call-ups)
--   - During offseason: Usually 0 changes unless scraper ran
--   - Alert on status = "⚠️" for investigation
-- ============================================================================

WITH
-- Current season (adjust when new season starts)
current_season AS (
  SELECT 2024 as season_year, '2024-25' as season_display
),

-- Rosters as of yesterday's scrape
yesterday_updates AS (
  SELECT
    r.season_year,
    r.season_display,
    r.team_abbrev,
    r.player_full_name,
    r.player_lookup,
    r.position,
    r.first_seen_date,
    r.last_scraped_date
  FROM `nba-props-platform.nba_raw.br_rosters_current` r
  CROSS JOIN current_season c
  WHERE r.season_year = c.season_year
    AND r.last_scraped_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Players who FIRST appeared yesterday (new additions)
new_players AS (
  SELECT
    team_abbrev,
    player_full_name,
    player_lookup,
    position,
    first_seen_date
  FROM yesterday_updates
  WHERE first_seen_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

-- Summary statistics
summary AS (
  SELECT
    COUNT(DISTINCT team_abbrev) as teams_updated,
    COUNT(DISTINCT player_full_name) as players_updated,
    (SELECT COUNT(*) FROM new_players) as new_players
  FROM yesterday_updates
)

SELECT
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  (SELECT season_display FROM current_season) as season,
  s.teams_updated,
  s.players_updated,
  s.new_players,
  CASE
    WHEN s.teams_updated = 0 AND s.players_updated = 0 THEN '⚪ No scraper run'
    WHEN s.new_players = 0 THEN '✅ No roster changes'
    WHEN s.new_players BETWEEN 1 AND 5 THEN '✅ Normal changes'
    WHEN s.new_players > 5 THEN '⚠️ Multiple changes - review below'
    ELSE '✅ Complete'
  END as status
FROM summary s

UNION ALL

-- List new players if any
SELECT
  n.first_seen_date as check_date,
  'NEW_PLAYER' as season,
  0 as teams_updated,
  0 as players_updated,
  0 as new_players,
  CONCAT(n.team_abbrev, ': ', n.player_full_name, ' (', n.position, ')') as status
FROM new_players n
ORDER BY
  season,
  check_date;
