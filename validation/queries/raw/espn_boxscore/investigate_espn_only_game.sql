-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/investigate_espn_only_game.sql
-- ============================================================================
-- Investigate the ESPN-only game (where BDL has no data)
-- This is a role reversal situation that needs investigation
-- ============================================================================

-- Find the ESPN-only game
WITH espn_only_game AS (
  SELECT DISTINCT
    e.game_date,
    e.game_id,
    e.season_year,
    e.home_team_abbr,
    e.away_team_abbr,
    CONCAT(e.away_team_abbr, ' @ ', e.home_team_abbr) as matchup,
    COUNT(*) OVER (PARTITION BY e.game_id) as espn_player_count
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON e.game_date = b.game_date
    AND e.game_id = b.game_id
  WHERE b.game_id IS NULL  -- ESPN has it, BDL doesn't
),

-- Check if this game is in the schedule
schedule_check AS (
  SELECT 
    s.game_date,
    s.game_id as schedule_game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    s.game_status_text,
    s.is_playoffs,
    s.season_year
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  INNER JOIN espn_only_game e
    ON s.game_date = e.game_date
    AND s.home_team_tricode = e.home_team_abbr
    AND s.away_team_tricode = e.away_team_abbr
  WHERE s.game_date = s.game_date  -- Partition filter
),

-- Get ESPN player details for this game
espn_players AS (
  SELECT
    e.game_id,
    e.player_full_name,
    e.team_abbr,
    e.points,
    e.rebounds,
    e.assists,
    e.minutes
  FROM `nba-props-platform.nba_raw.espn_boxscores` e
  INNER JOIN espn_only_game eo
    ON e.game_id = eo.game_id
  ORDER BY e.team_abbr, e.points DESC
)

-- Output investigation report
SELECT
  '=== ESPN-ONLY GAME DETAILS ===' as section,
  '' as blank1,
  CAST(eog.game_date AS STRING) as game_date,
  eog.game_id as espn_game_id,
  eog.matchup,
  CAST(eog.season_year AS STRING) as season_year,
  CAST(eog.espn_player_count AS STRING) as player_count,
  '' as blank2,
  '=== SCHEDULE CHECK ===' as schedule_section,
  CASE 
    WHEN sc.schedule_game_id IS NOT NULL 
    THEN '✅ Game IS in schedule'
    ELSE '🔴 Game NOT in schedule'
  END as in_schedule,
  COALESCE(sc.schedule_game_id, 'NOT FOUND') as schedule_game_id,
  COALESCE(sc.game_status_text, 'N/A') as game_status,
  '' as blank3,
  '=== WHY BDL MIGHT HAVE MISSED IT ===' as investigation_section,
  CASE
    WHEN sc.schedule_game_id IS NULL THEN '🔴 Game not in schedule - BDL would skip it'
    WHEN sc.game_status_text LIKE '%Postponed%' THEN '⚠️ Game was postponed - check if rescheduled'
    WHEN sc.game_status_text LIKE '%Canceled%' THEN '⚠️ Game was canceled'
    WHEN eog.game_date < '2025-01-15' THEN '⚠️ Old game - BDL may have started collection later'
    ELSE '❓ Unknown - BDL should have collected this'
  END as likely_reason,
  '' as blank4,
  '=== NEXT STEPS ===' as next_steps_section,
  CASE
    WHEN sc.schedule_game_id IS NULL THEN 
      '1. Verify game actually happened on NBA.com\n2. Check if schedule import missed this game\n3. Manually add to schedule if needed'
    WHEN sc.game_status_text LIKE '%Postponed%' OR sc.game_status_text LIKE '%Canceled%' THEN
      '1. Check if game was rescheduled\n2. Update schedule status\n3. Re-run BDL scraper for this date'
    ELSE
      '1. Check BDL API response for this date\n2. Review BDL scraper logs for 2025-01-15\n3. Re-run BDL scraper for this specific game'
  END as recommended_actions
FROM espn_only_game eog
LEFT JOIN schedule_check sc
  ON eog.game_date = sc.game_date
  AND eog.home_team_abbr = sc.home_team_tricode
  AND eog.away_team_abbr = sc.away_team_tricode;

-- Show the actual players in this ESPN-only game
SELECT
  '=== PLAYERS IN ESPN-ONLY GAME ===' as info,
  game_id,
  player_full_name,
  team_abbr,
  points,
  rebounds,
  assists,
  minutes
FROM espn_players
ORDER BY team_abbr, points DESC
LIMIT 30;
