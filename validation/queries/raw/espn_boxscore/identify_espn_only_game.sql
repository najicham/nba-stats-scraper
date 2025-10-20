-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/identify_espn_only_game.sql
-- ============================================================================
-- Simple query to identify which game ESPN has that BDL doesn't
-- ============================================================================

-- First, find the ESPN-only game
WITH espn_games AS (
  SELECT DISTINCT
    game_date,
    game_id,
    season_year,
    home_team_abbr,
    away_team_abbr,
    CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup
  FROM `nba-props-platform.nba_raw.espn_boxscores`
),

bdl_games AS (
  SELECT DISTINCT
    game_id
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2020-01-01'  -- Check all BDL data
),

espn_only AS (
  SELECT 
    e.game_date,
    e.game_id,
    e.season_year,
    e.matchup,
    e.home_team_abbr,
    e.away_team_abbr
  FROM espn_games e
  LEFT JOIN bdl_games b ON e.game_id = b.game_id
  WHERE b.game_id IS NULL  -- ESPN has it, BDL doesn't
)

SELECT
  '=== ESPN-ONLY GAME DETAILS ===' as section,
  game_date,
  game_id as espn_game_id,
  matchup,
  CAST(season_year AS STRING) as season
FROM espn_only;

-- Get player details from this game
SELECT
  '=== PLAYERS IN ESPN-ONLY GAME ===' as section,
  player_full_name,
  team_abbr,
  points,
  rebounds,
  assists,
  minutes,
  CASE 
    WHEN minutes = '0:00' THEN 'DNP'
    ELSE 'PLAYED'
  END as status
FROM `nba-props-platform.nba_raw.espn_boxscores`
WHERE game_id IN (
  SELECT game_id 
  FROM espn_games e
  LEFT JOIN bdl_games b ON e.game_id = b.game_id
  WHERE b.game_id IS NULL
)
ORDER BY team_abbr, points DESC;

-- Check if this game exists in schedule (with partition filter)
SELECT
  '=== SCHEDULE CHECK ===' as section,
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ Game IS in schedule'
    ELSE '🔴 Game NOT in schedule'
  END as schedule_status,
  MAX(game_id) as schedule_game_id,
  MAX(game_status_text) as status,
  MAX(CAST(is_playoffs AS STRING)) as is_playoffs
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date = '2025-01-15'  -- Hardcoded date from ESPN game
  AND home_team_tricode = 'PHI'  -- Need to get these from ESPN
  AND away_team_tricode = 'HOU'; -- Will show in first query results
