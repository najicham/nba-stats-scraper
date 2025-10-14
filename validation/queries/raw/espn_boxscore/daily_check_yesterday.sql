-- ============================================================================
-- File: validation/queries/raw/espn_boxscore/daily_check_yesterday.sql
-- ESPN Boxscore: Daily Check for Yesterday's Data
-- Purpose: Monitor if ESPN backup collection ran for yesterday's games
-- Note: ESPN is sparse backup - NO data is NORMAL, not a failure
-- ============================================================================

WITH yesterday_schedule AS (
  SELECT 
    COUNT(DISTINCT game_id) as scheduled_games,
    STRING_AGG(
      CONCAT(away_team_tricode, '@', home_team_tricode), 
      ', ' 
      ORDER BY home_team_tricode
      LIMIT 10
    ) as sample_matchups
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_playoffs = FALSE
    AND game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)  -- Partition filter
),

yesterday_espn AS (
  SELECT 
    COUNT(DISTINCT game_id) as espn_games,
    COUNT(*) as espn_player_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    STRING_AGG(
      CONCAT(away_team_abbr, '@', home_team_abbr), 
      ', '
      ORDER BY home_team_abbr
    ) as espn_matchups,
    AVG(points) as avg_points_per_player
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),

yesterday_bdl AS (
  SELECT 
    COUNT(DISTINCT game_id) as bdl_games,
    COUNT(*) as bdl_player_records
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)

-- Output summary
SELECT 
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as check_date,
  
  -- Schedule context
  s.scheduled_games,
  s.sample_matchups as scheduled_matchups,
  
  -- ESPN data
  COALESCE(e.espn_games, 0) as espn_games_collected,
  COALESCE(e.espn_player_records, 0) as espn_player_records,
  e.espn_matchups as espn_matchups_collected,
  
  -- BDL comparison (primary source)
  COALESCE(b.bdl_games, 0) as bdl_games_collected,
  
  -- Status assessment
  CASE 
    WHEN s.scheduled_games = 0 THEN '⚪ NO GAMES SCHEDULED'
    WHEN e.espn_games IS NULL OR e.espn_games = 0 THEN '⚪ NO ESPN DATA (Normal for backup source)'
    WHEN b.bdl_games = 0 THEN '🔴 CRITICAL: No BDL data but ESPN collected'
    WHEN e.espn_games > 0 AND b.bdl_games > 0 THEN '✅ ESPN backup data exists (with BDL)'
    ELSE '⚪ ESPN Only (investigate why no BDL)'
  END as status,
  
  -- Data quality check
  CASE 
    WHEN e.espn_games > 0 AND e.espn_player_records / e.espn_games < 20 THEN '⚠️ Low player count per game'
    WHEN e.espn_games > 0 AND e.espn_player_records / e.espn_games > 35 THEN '⚠️ High player count per game'
    WHEN e.espn_games > 0 THEN '✅ Player counts normal'
    ELSE 'N/A'
  END as quality_check,
  
  -- Interpretation
  CASE 
    WHEN s.scheduled_games = 0 THEN 'Off day - no validation needed'
    WHEN e.espn_games = 0 THEN 'Normal - ESPN is sparse backup, not collected every day'
    WHEN e.espn_games > 0 AND b.bdl_games > 0 THEN 'Good - Both sources available for validation'
    WHEN e.espn_games > 0 AND b.bdl_games = 0 THEN 'INVESTIGATE - Why no BDL when ESPN collected?'
    ELSE 'Normal operation'
  END as interpretation

FROM yesterday_schedule s
CROSS JOIN yesterday_espn e
CROSS JOIN yesterday_bdl b;

-- ============================================================================
-- GAME-LEVEL DETAILS (if ESPN data exists)
-- ============================================================================

-- Uncomment to see per-game breakdown when ESPN data exists
/*
SELECT 
  game_id,
  home_team_abbr || ' vs ' || away_team_abbr as matchup,
  COUNT(*) as player_count,
  COUNT(DISTINCT team_abbr) as team_count,
  SUM(points) as total_points,
  AVG(points) as avg_points_per_player,
  MAX(points) as top_scorer_points,
  CASE 
    WHEN COUNT(*) < 20 THEN '⚠️ Low player count'
    WHEN COUNT(*) > 35 THEN '⚠️ High player count'
    WHEN COUNT(DISTINCT team_abbr) != 2 THEN '🔴 Wrong team count'
    ELSE '✅ Normal'
  END as status
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY game_id, home_team_abbr, away_team_abbr
ORDER BY game_id;
*/

-- ============================================================================
-- EXPECTED RESULTS:
-- 
-- Most days: "⚪ NO ESPN DATA (Normal for backup source)"
-- This is EXPECTED and CORRECT behavior
--
-- ESPN is a sparse backup source that only collects data during:
-- - Early Morning Final Check workflow failures
-- - Manual backup validation scenarios
-- - Ad-hoc data quality checks
--
-- STATUS GUIDE:
-- ⚪ No ESPN Data = Normal (backup source, not daily collection)
-- ✅ ESPN + BDL = Excellent (both sources for validation)
-- 🔴 ESPN Only = Investigate (why no BDL data?)
-- 
-- CRITICAL: Do NOT alert on "no ESPN data" - this is expected behavior
-- ONLY alert if ESPN exists but BDL doesn't (role reversal = problem)
-- ============================================================================
