-- ============================================================================
-- File: validation/queries/raw/nbac_referee/realtime_scraper_check.sql
-- Purpose: Real-time monitoring of referee assignment scraper health
-- Usage: Run during the day to check if scraper is actively collecting data
-- ============================================================================
-- Expected Results:
--   - Shows when data was last collected
--   - Identifies if scraper is running behind schedule
--   - Alerts if no recent data for today's or tomorrow's games
-- ============================================================================

WITH todays_schedule AS (
  SELECT
    COUNT(*) as games_today,
    STRING_AGG(CONCAT(away_team_tricode, '@', home_team_tricode), ', ' ORDER BY game_time) as matchups
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = CURRENT_DATE()
),

tomorrows_schedule AS (
  SELECT
    COUNT(*) as games_tomorrow,
    STRING_AGG(CONCAT(away_team_tricode, '@', home_team_tricode), ', ' ORDER BY game_time) as matchups
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
),

todays_refs AS (
  SELECT
    COUNT(DISTINCT game_id) as games_with_refs,
    COUNT(DISTINCT official_code) as unique_officials,
    MAX(created_at) as last_processed
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date = CURRENT_DATE()
),

tomorrows_refs AS (
  SELECT
    COUNT(DISTINCT game_id) as games_with_refs,
    COUNT(DISTINCT official_code) as unique_officials,
    MAX(created_at) as last_processed
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
),

recent_activity AS (
  SELECT
    MAX(created_at) as last_data_processed,
    COUNT(DISTINCT game_date) as dates_processed_today
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE DATE(created_at) = CURRENT_DATE()
)

SELECT
  CURRENT_TIMESTAMP() as check_time,
  
  -- Today's game status
  ts.games_today,
  tr.games_with_refs as today_games_with_refs,
  CASE
    WHEN ts.games_today = 0 THEN '⚪ No games today'
    WHEN tr.games_with_refs = ts.games_today THEN '✅ All games have refs'
    WHEN tr.games_with_refs = 0 THEN '❌ No ref data yet'
    ELSE CONCAT('⚠️ ', CAST(tr.games_with_refs AS STRING), '/', CAST(ts.games_today AS STRING), ' games')
  END as today_status,
  
  -- Tomorrow's game status (refs usually published day before)
  toms.games_tomorrow,
  tomr.games_with_refs as tomorrow_games_with_refs,
  CASE
    WHEN toms.games_tomorrow = 0 THEN '⚪ No games tomorrow'
    WHEN tomr.games_with_refs = toms.games_tomorrow THEN '✅ All games have refs'
    WHEN tomr.games_with_refs = 0 THEN '⚠️ No ref data yet (check this afternoon)'
    ELSE CONCAT('⚠️ ', CAST(tomr.games_with_refs AS STRING), '/', CAST(toms.games_tomorrow AS STRING), ' games')
  END as tomorrow_status,
  
  -- Recent processing activity
  ra.last_data_processed,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), ra.last_data_processed, MINUTE) as minutes_since_last_update,
  ra.dates_processed_today,
  
  -- Overall scraper health
  CASE
    WHEN ra.last_data_processed IS NULL THEN '❌ CRITICAL: No data processed today'
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), ra.last_data_processed, MINUTE) > 180 THEN '⚠️ WARNING: No updates in 3+ hours'
    WHEN ts.games_today > 0 AND tr.games_with_refs = 0 THEN '⚠️ WARNING: Today''s games missing refs'
    WHEN toms.games_tomorrow > 0 AND tomr.games_with_refs = 0 
     AND EXTRACT(HOUR FROM CURRENT_TIMESTAMP()) > 12 THEN '⚠️ WARNING: Tomorrow''s refs not published yet'
    ELSE '✅ Scraper healthy'
  END as scraper_health

FROM todays_schedule ts
CROSS JOIN tomorrows_schedule toms
CROSS JOIN todays_refs tr
CROSS JOIN tomorrows_refs tomr
CROSS JOIN recent_activity ra;
