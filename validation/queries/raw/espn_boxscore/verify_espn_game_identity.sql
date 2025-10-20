-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/verify_espn_game_identity.sql
-- ============================================================================
-- Verify if ESPN game is actually NYK @ PHI (not HOU @ PHI)
-- Hypothesis: ESPN has wrong game_id or team abbreviations
-- ============================================================================

-- Check which players ESPN has
WITH espn_players AS (
  SELECT 
    player_full_name,
    team_abbr,
    points
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = '2025-01-15'
  ORDER BY team_abbr, points DESC
  LIMIT 10
),

-- Check if these players match NYK @ PHI in BDL
nyk_phi_players AS (
  SELECT
    player_full_name,
    team_abbr,
    points
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2025-01-15'
    AND game_id LIKE '%NYK%PHI%'
  ORDER BY team_abbr, points DESC
  LIMIT 10
),

-- Check if these players match HOU @ DEN in BDL
hou_den_players AS (
  SELECT
    player_full_name,
    team_abbr,
    points
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2025-01-15'
    AND game_id LIKE '%HOU%DEN%'
  ORDER BY team_abbr, points DESC
  LIMIT 10
)

SELECT '=== ESPN TOP PLAYERS ===' as section, player_full_name, team_abbr, points
FROM espn_players

UNION ALL

SELECT '=== BDL: NYK @ PHI TOP PLAYERS ===' as section, player_full_name, team_abbr, points
FROM nyk_phi_players

UNION ALL

SELECT '=== BDL: HOU @ DEN TOP PLAYERS ===' as section, player_full_name, team_abbr, points
FROM hou_den_players;

-- Player overlap analysis
WITH espn_player_names AS (
  SELECT DISTINCT player_full_name
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date = '2025-01-15'
),

nyk_phi_names AS (
  SELECT DISTINCT player_full_name
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2025-01-15'
    AND (team_abbr = 'NYK' OR team_abbr = 'PHI')
),

hou_den_names AS (
  SELECT DISTINCT player_full_name
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2025-01-15'
    AND (team_abbr = 'HOU' OR team_abbr = 'DEN')
)

SELECT
  '=== PLAYER OVERLAP ANALYSIS ===' as analysis,
  COUNT(DISTINCT e.player_full_name) as espn_players,
  COUNT(DISTINCT n.player_full_name) as matching_nyk_phi,
  COUNT(DISTINCT h.player_full_name) as matching_hou_den,
  CASE
    WHEN COUNT(DISTINCT n.player_full_name) > COUNT(DISTINCT h.player_full_name)
    THEN '🎯 ESPN game is likely NYK @ PHI (wrong game_id/teams)'
    WHEN COUNT(DISTINCT h.player_full_name) > COUNT(DISTINCT n.player_full_name)
    THEN '🎯 ESPN game is likely HOU @ DEN (wrong game_id)'
    ELSE '❓ Unclear - need manual review'
  END as conclusion
FROM espn_player_names e
LEFT JOIN nyk_phi_names n ON e.player_full_name = n.player_full_name
LEFT JOIN hou_den_names h ON e.player_full_name = h.player_full_name;
