-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/simple_espn_game_investigation.sql
-- ============================================================================
-- Simple investigation of ESPN-only game (with proper partition filters)
-- ============================================================================

-- Step 1: Get ESPN game details (with partition filter)
SELECT
  '=== ESPN GAME DETAILS ===' as section,
  game_date,
  game_id,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  home_team_abbr,
  away_team_abbr,
  season_year
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date >= '2025-01-01'  -- Partition filter
LIMIT 1;

-- Step 2: Check if BDL has this exact game_id
SELECT
  '=== BDL CHECK (Exact Match) ===' as section,
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ BDL HAS this exact game_id'
    ELSE '🔴 BDL DOES NOT have this game_id'
  END as bdl_status,
  COUNT(*) as bdl_player_count
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2025-01-15'  -- Partition filter
  AND game_id = '20250115_HOU_PHI';

-- Step 3: Check what games BDL DOES have on 2025-01-15
SELECT
  '=== BDL GAMES on 2025-01-15 ===' as section,
  game_id,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  COUNT(*) as players
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2025-01-15'
GROUP BY game_id, away_team_abbr, home_team_abbr
ORDER BY matchup;

-- Step 4: Check schedule for HOU @ PHI
SELECT
  '=== SCHEDULE CHECK (HOU @ PHI) ===' as section,
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ HOU @ PHI IS in schedule'
    ELSE '🔴 HOU @ PHI NOT in schedule'
  END as schedule_status,
  MAX(game_id) as schedule_game_id,
  MAX(game_status_text) as game_status
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date = '2025-01-15'
  AND home_team_tricode = 'PHI'
  AND away_team_tricode = 'HOU';

-- Step 5: Check schedule for games involving PHI
SELECT
  '=== ALL PHI GAMES on 2025-01-15 ===' as section,
  game_id,
  CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
  game_status_text
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date = '2025-01-15'
  AND (home_team_tricode = 'PHI' OR away_team_tricode = 'PHI');

-- Step 6: Show ESPN players
SELECT
  '=== ESPN PLAYERS ===' as section,
  player_full_name,
  team_abbr,
  points,
  rebounds,
  assists,
  minutes
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_date = '2025-01-15'
ORDER BY team_abbr, points DESC;
