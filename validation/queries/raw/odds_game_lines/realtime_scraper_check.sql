-- ============================================================================
-- File: validation/queries/raw/odds_game_lines/realtime_scraper_check.sql
-- Purpose: Real-time monitoring of scraper health for today's games
-- Usage: Run during game days to verify scraper is actively capturing data
-- ============================================================================
-- Instructions:
--   1. Run multiple times throughout the day (hourly during game days)
--   2. Alert if minutes_since_last_snapshot > 120 (2 hours)
--   3. Alert if games_with_odds < scheduled_games
-- ============================================================================
-- Expected Results:
--   - status = "✅ Scraper healthy" when running normally
--   - minutes_since_last_snapshot should be < 120 minutes
--   - snapshot_count should increase throughout the day
-- ============================================================================

WITH todays_games AS (
  SELECT 
    COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

todays_odds AS (
  SELECT 
    COUNT(DISTINCT game_id) as games_with_odds,
    MAX(snapshot_timestamp) as latest_snapshot,
    COUNT(DISTINCT snapshot_timestamp) as snapshot_count,
    MIN(snapshot_timestamp) as earliest_snapshot
  FROM `nba-props-platform.nba_raw.odds_api_game_lines`
  WHERE game_date = CURRENT_DATE()
)

SELECT 
  CURRENT_DATE() as check_date,
  CURRENT_TIMESTAMP() as check_time,
  s.scheduled_games,
  o.games_with_odds,
  o.earliest_snapshot,
  o.latest_snapshot,
  o.snapshot_count,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), o.latest_snapshot, MINUTE) as minutes_since_last_snapshot,
  CASE 
    WHEN s.scheduled_games = 0 THEN '⚪ No games today'
    WHEN o.games_with_odds = 0 THEN '❌ CRITICAL: No odds captured yet'
    WHEN o.games_with_odds < s.scheduled_games THEN '⚠️ WARNING: Some games missing odds'
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), o.latest_snapshot, MINUTE) > 120 
    THEN '⚠️ WARNING: Scraper may be stale (>2hrs since last snapshot)'
    ELSE '✅ Scraper healthy'
  END as status
FROM todays_games s
CROSS JOIN todays_odds o;