-- ============================================================================
-- FILE: validation/queries/raw/bigdataball_pbp/realtime_scraper_check.sql
-- ============================================================================
-- Purpose: Check if BigDataBall scraper/processor is running and current
-- Usage: Run to verify real-time data collection during active season
-- ============================================================================
-- Instructions:
--   1. Run anytime to check data freshness
--   2. Set up alerts if minutes_since_last > expected threshold
--   3. NOTE: BigDataBall releases data ~2 hours after game completion
-- ============================================================================
-- Expected Behavior:
--   - During active games: Data appears ~2 hours after game ends
--   - Off days: May show stale data (normal)
--   - Season off: Will show months-old data (normal)
-- ============================================================================

WITH latest_data AS (
  SELECT
    MAX(game_date) as last_game_date,
    COUNT(DISTINCT CASE WHEN game_date = CURRENT_DATE() THEN game_id END) as games_today,
    COUNT(DISTINCT CASE WHEN game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) THEN game_id END) as games_yesterday,
    MAX(processed_at) as last_processed_timestamp,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), MINUTE) as minutes_since_last_processing
  FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),

today_schedule AS (
  SELECT
    COUNT(*) as scheduled_today,
    COUNT(CASE WHEN TIMESTAMP(CONCAT(game_date, ' ', game_time_et)) < CURRENT_TIMESTAMP() THEN 1 END) as completed_today
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

yesterday_schedule AS (
  SELECT
    COUNT(*) as scheduled_yesterday
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)

SELECT
  CURRENT_TIMESTAMP() as check_time,
  l.last_game_date,
  DATE_DIFF(CURRENT_DATE(), l.last_game_date, DAY) as days_since_last_game,
  l.last_processed_timestamp,
  l.minutes_since_last_processing,
  
  -- Today's status
  t.scheduled_today,
  t.completed_today,
  l.games_today as games_in_db_today,
  
  -- Yesterday's status  
  y.scheduled_yesterday,
  l.games_yesterday as games_in_db_yesterday,
  
  -- Health status
  CASE
    -- Season active checks
    WHEN t.scheduled_today > 0 AND t.completed_today > 0 
         AND l.games_today < t.completed_today 
         AND l.minutes_since_last_processing > 240  -- 4 hours after game
    THEN '🔴 CRITICAL: Games completed but not in DB'
    
    -- Yesterday's games check
    WHEN y.scheduled_yesterday > 0 AND l.games_yesterday < y.scheduled_yesterday
    THEN '⚠️ WARNING: Missing yesterday''s games'
    
    -- Normal processing lag
    WHEN t.completed_today > 0 AND l.minutes_since_last_processing < 240
    THEN '⏳ PROCESSING: Within normal 2-4 hour delay'
    
    -- Off season or off day
    WHEN t.scheduled_today = 0 AND y.scheduled_yesterday = 0
    THEN '⚪ OFF DAY: No games scheduled'
    
    -- Current with data
    WHEN l.games_yesterday = y.scheduled_yesterday OR l.games_today > 0
    THEN '✅ CURRENT: Data up to date'
    
    -- Stale data during season
    WHEN DATE_DIFF(CURRENT_DATE(), l.last_game_date, DAY) > 2
    THEN '⚠️ WARNING: Data is stale'
    
    ELSE '⚪ Unknown status'
  END as status,
  
  -- Context notes
  CASE
    WHEN t.scheduled_today > 0 THEN CONCAT('Waiting for ', CAST(t.scheduled_today AS STRING), ' games today')
    WHEN y.scheduled_yesterday > 0 THEN 'Check yesterday''s games'
    ELSE 'No recent games scheduled'
  END as notes
  
FROM latest_data l
CROSS JOIN today_schedule t
CROSS JOIN yesterday_schedule y;

-- Status Guide:
-- ✅ CURRENT: Data is up to date with recent games
-- ⏳ PROCESSING: Games completed <4 hours ago (normal delay)
-- ⚠️ WARNING: Missing expected data
-- 🔴 CRITICAL: Games completed >4 hours ago but not in DB
-- ⚪ OFF DAY: No games scheduled (normal during off days/season)
