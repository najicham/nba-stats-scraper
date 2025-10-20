-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/check_schedule_for_espn_game.sql
-- ============================================================================
-- Check if the ESPN-only game exists in schedule
-- Run this AFTER identify_espn_only_game.sql to get game details
-- 
-- INSTRUCTIONS:
-- 1. Run identify_espn_only_game.sql first to get: game_date, home_team, away_team
-- 2. Update the three values below with those results
-- 3. Then run this query
-- ============================================================================

-- TODO: UPDATE THESE VALUES with results from identify_espn_only_game.sql
-- Game found: 2025-01-15, HOU @ PHI
-- So the values should be:

WITH schedule_check AS (
  SELECT
    game_date,
    game_id as schedule_game_id,
    home_team_tricode,
    away_team_tricode,
    game_status_text,
    is_playoffs,
    season_year
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = '2025-01-15'  -- ← UPDATE: game_date from ESPN query
    AND home_team_tricode = 'PHI'  -- ← UPDATE: home_team from ESPN query
    AND away_team_tricode = 'HOU'  -- ← UPDATE: away_team from ESPN query
)

SELECT
  '=== SCHEDULE CHECK RESULTS ===' as section,
  '' as blank1,
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ Game IS in schedule'
    ELSE '🔴 Game NOT in schedule'
  END as in_schedule,
  MAX(schedule_game_id) as schedule_game_id,
  MAX(game_status_text) as game_status,
  MAX(CAST(is_playoffs AS STRING)) as is_playoffs,
  '' as blank2,
  CASE
    WHEN COUNT(*) = 0 THEN 
      '🔴 Game not in schedule - BDL would skip it'
    WHEN MAX(game_status_text) LIKE '%Postponed%' THEN 
      '⚠️ Game was postponed - check if rescheduled'
    WHEN MAX(game_status_text) LIKE '%Canceled%' THEN 
      '⚠️ Game was canceled'
    ELSE 
      '❓ Game in schedule but BDL missed it - check logs'
  END as likely_issue,
  '' as blank3,
  '=== RECOMMENDED ACTION ===' as action_section,
  CASE
    WHEN COUNT(*) = 0 THEN 
      '1. Verify game on NBA.com | 2. Check schedule import | 3. Re-run BDL scraper'
    WHEN MAX(game_status_text) LIKE '%Postponed%' OR MAX(game_status_text) LIKE '%Canceled%' THEN
      '1. Confirm status NBA.com | 2. Update schedule | 3. Re-scrape correct date'
    ELSE
      '1. Check BDL API logs | 2. Review scraper logs | 3. Re-run BDL for this game'
  END as action_steps
FROM schedule_check;
