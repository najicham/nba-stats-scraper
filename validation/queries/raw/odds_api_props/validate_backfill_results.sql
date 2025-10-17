-- ============================================================================
-- File: validation/queries/raw/odds_api_props/validate_backfill_results.sql
-- ============================================================================
-- Validate Props Backfill Results
-- ============================================================================
-- Purpose: Verify that backfilled props data was loaded correctly
-- Usage: Run after completing backfill operations
-- ============================================================================

-- ============================================================================
-- Check 1: Verify Coverage by Season and Priority Level
-- ============================================================================
WITH expected_games AS (
  SELECT 
    CASE
      WHEN game_date >= '2024-10-01' THEN '2024-25'
      WHEN game_date >= '2023-10-01' THEN '2023-24'
      WHEN game_date >= '2022-10-01' THEN '2022-23'
      ELSE '2021-22'
    END as season,
    is_playoffs,
    COUNT(DISTINCT game_id) as total_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE is_playoffs = TRUE
    AND game_date >= '2022-04-01'
  GROUP BY season, is_playoffs
),
actual_games AS (
  SELECT
    CASE
      WHEN game_date >= '2024-10-01' THEN '2024-25'
      WHEN game_date >= '2023-10-01' THEN '2023-24'
      WHEN game_date >= '2022-10-01' THEN '2022-23'
      ELSE '2021-22'
    END as season,
    COUNT(DISTINCT game_id) as games_with_props,
    ROUND(AVG(player_count), 1) as avg_players,
    MIN(player_count) as min_players,
    MAX(player_count) as max_players
  FROM (
    SELECT 
      game_date,
      game_id,
      COUNT(DISTINCT player_name) as player_count
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2022-04-01'
    GROUP BY game_date, game_id
  )
  GROUP BY season
)
SELECT
  e.season,
  'Playoffs' as game_type,
  e.total_games as expected_games,
  COALESCE(a.games_with_props, 0) as actual_games,
  e.total_games - COALESCE(a.games_with_props, 0) as missing_games,
  ROUND(COALESCE(a.games_with_props, 0) * 100.0 / e.total_games, 1) as coverage_pct,
  COALESCE(a.avg_players, 0) as avg_players,
  COALESCE(a.min_players, 0) as min_players,
  COALESCE(a.max_players, 0) as max_players,
  CASE
    WHEN e.total_games = COALESCE(a.games_with_props, 0) THEN '✅ 100% Complete'
    WHEN COALESCE(a.games_with_props, 0) = 0 THEN '❌ No Data'
    WHEN COALESCE(a.games_with_props, 0) < e.total_games * 0.5 THEN '🔴 <50% Coverage'
    WHEN COALESCE(a.games_with_props, 0) < e.total_games * 0.9 THEN '🟡 <90% Coverage'
    ELSE '🟢 >90% Coverage'
  END as status
FROM expected_games e
LEFT JOIN actual_games a ON e.season = a.season
ORDER BY e.season DESC;

-- ============================================================================
-- Check 2: Verify Critical Teams (PHX, LAC, DAL)
-- ============================================================================
WITH critical_teams AS (
  SELECT DISTINCT
    CASE 
      WHEN game_date >= '2024-04-12' THEN '2023-24'
      ELSE '2024-25'
    END as season,
    team as team_code,
    COUNT(*) as playoff_games,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game
  FROM (
    SELECT game_date, home_team_tricode as team
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE is_playoffs = TRUE 
      AND game_date >= '2024-04-12'
      AND home_team_tricode IN ('PHX', 'LAC', 'DAL')
    UNION ALL
    SELECT game_date, away_team_tricode as team
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE is_playoffs = TRUE 
      AND game_date >= '2024-04-12'
      AND away_team_tricode IN ('PHX', 'LAC', 'DAL')
  )
  GROUP BY season, team
),
props_coverage AS (
  SELECT 
    CASE 
      WHEN game_date >= '2024-04-12' THEN '2023-24'
      ELSE '2024-25'
    END as season,
    team as team_code,
    COUNT(*) as games_with_props,
    ROUND(AVG(players), 1) as avg_players,
    MIN(players) as min_players
  FROM (
    SELECT 
      game_date,
      home_team_abbr as team,
      COUNT(DISTINCT player_name) as players
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2024-04-12'
      AND home_team_abbr IN ('PHX', 'LAC', 'DAL')
    GROUP BY game_date, home_team_abbr
    UNION ALL
    SELECT 
      game_date,
      away_team_abbr as team,
      COUNT(DISTINCT player_name) as players
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
    WHERE game_date >= '2024-04-12'
      AND away_team_abbr IN ('PHX', 'LAC', 'DAL')
    GROUP BY game_date, away_team_abbr
  )
  GROUP BY season, team
)
SELECT
  t.season,
  t.team_code as team,
  t.playoff_games as expected_games,
  COALESCE(p.games_with_props, 0) as actual_games,
  t.playoff_games - COALESCE(p.games_with_props, 0) as missing_games,
  ROUND(COALESCE(p.games_with_props, 0) * 100.0 / t.playoff_games, 1) as coverage_pct,
  COALESCE(p.avg_players, 0) as avg_players,
  CASE
    WHEN COALESCE(p.games_with_props, 0) = t.playoff_games AND COALESCE(p.avg_players, 0) >= 12 
      THEN '✅ Complete & High Quality'
    WHEN COALESCE(p.games_with_props, 0) = t.playoff_games 
      THEN '✅ Complete'
    WHEN COALESCE(p.games_with_props, 0) = 0 
      THEN '❌ No Props Data'
    WHEN COALESCE(p.games_with_props, 0) < t.playoff_games * 0.5 
      THEN '🔴 <50% Coverage'
    ELSE '🟡 Partial Coverage'
  END as status,
  t.first_game,
  t.last_game
FROM critical_teams t
LEFT JOIN props_coverage p 
  ON t.season = p.season 
  AND t.team_code = p.team_code
ORDER BY t.season DESC, t.team_code;

-- ============================================================================
-- Check 3: Verify Specific Backfilled Dates
-- ============================================================================
-- Phase 1A: 2024-25 DEN vs LAC
SELECT 
  'Phase 1A: 2024-25 DEN-LAC' as phase,
  game_date,
  home_team_abbr,
  away_team_abbr,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_records,
  MIN(snapshot_timestamp) as earliest_snapshot,
  MAX(snapshot_timestamp) as latest_snapshot,
  CASE
    WHEN COUNT(DISTINCT player_name) >= 15 THEN '✅ Excellent'
    WHEN COUNT(DISTINCT player_name) >= 12 THEN '✅ Good'
    WHEN COUNT(DISTINCT player_name) >= 8 THEN '🟡 Acceptable'
    ELSE '🔴 Low Coverage'
  END as quality
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date IN (
  '2025-04-19', '2025-04-21', '2025-04-24', '2025-04-26',
  '2025-04-29', '2025-05-01', '2025-05-03'
)
GROUP BY game_date, home_team_abbr, away_team_abbr
ORDER BY game_date;

-- Phase 1B: 2023-24 PHX-MIN and LAC-DAL
SELECT 
  'Phase 1B: 2023-24 Playoffs' as phase,
  game_date,
  home_team_abbr,
  away_team_abbr,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_records,
  MIN(snapshot_timestamp) as earliest_snapshot,
  MAX(snapshot_timestamp) as latest_snapshot,
  CASE
    WHEN COUNT(DISTINCT player_name) >= 14 THEN '✅ Excellent'
    WHEN COUNT(DISTINCT player_name) >= 10 THEN '✅ Good'
    WHEN COUNT(DISTINCT player_name) >= 6 THEN '🟡 Acceptable'
    ELSE '🔴 Low Coverage'
  END as quality
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date IN (
  '2024-04-20', '2024-04-21', '2024-04-23', '2024-04-26',
  '2024-04-28', '2024-05-01', '2024-05-03'
)
GROUP BY game_date, home_team_abbr, away_team_abbr
ORDER BY game_date;

-- ============================================================================
-- Check 4: Player Coverage Quality Check
-- ============================================================================
-- Check if any backfilled games have suspiciously low player counts
SELECT 
  game_date,
  game_id,
  home_team_abbr,
  away_team_abbr,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  STRING_AGG(DISTINCT bookmaker, ', ' ORDER BY bookmaker) as bookmaker_list,
  '🔴 LOW PLAYER COUNT - INVESTIGATE' as alert
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2024-04-20'
  AND game_date <= '2025-05-03'
GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
HAVING COUNT(DISTINCT player_name) < 8
ORDER BY unique_players ASC, game_date;

-- ============================================================================
-- Check 5: Verify No Duplicate Records Were Created
-- ============================================================================
SELECT 
  game_date,
  home_team_abbr,
  away_team_abbr,
  player_name,
  bookmaker,
  snapshot_timestamp,
  COUNT(*) as duplicate_count,
  STRING_AGG(source_file_path, ' | ') as source_files
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2024-04-20'
  AND game_date <= '2025-05-03'
GROUP BY game_date, home_team_abbr, away_team_abbr, player_name, bookmaker, snapshot_timestamp
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, game_date;

-- ============================================================================
-- Check 6: Compare Before and After (if you saved baseline)
-- ============================================================================
-- Run this to see improvement (update date based on when you ran backfill)
WITH before_backfill AS (
  -- Manually enter your baseline numbers here
  SELECT '2024-25' as season, 'Playoffs' as type, 7 as missing_before
  UNION ALL SELECT '2023-24', 'Playoffs', 10
  UNION ALL SELECT '2022-23', 'Playoffs', 59
),
after_backfill AS (
  SELECT
    CASE
      WHEN s.game_date >= '2024-10-01' THEN '2024-25'
      WHEN s.game_date >= '2023-10-01' THEN '2023-24'
      ELSE '2022-23'
    END as season,
    'Playoffs' as type,
    COUNT(DISTINCT s.game_id) as total_games,
    COUNT(DISTINCT p.game_id) as games_with_props,
    COUNT(DISTINCT s.game_id) - COUNT(DISTINCT p.game_id) as missing_after
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON s.game_date = p.game_date
    AND s.home_team_tricode = p.home_team_abbr
    AND s.away_team_tricode = p.away_team_abbr
  WHERE s.is_playoffs = TRUE
    AND s.game_date >= '2022-04-01'
  GROUP BY season
)
SELECT
  b.season,
  b.missing_before,
  a.missing_after,
  b.missing_before - a.missing_after as games_backfilled,
  ROUND((b.missing_before - a.missing_after) * 100.0 / b.missing_before, 1) as improvement_pct,
  CASE
    WHEN a.missing_after = 0 THEN '✅ 100% Complete'
    WHEN a.missing_after < b.missing_before * 0.1 THEN '🟢 >90% Improvement'
    WHEN a.missing_after < b.missing_before * 0.5 THEN '🟡 >50% Improvement'
    ELSE '🔴 <50% Improvement'
  END as status
FROM before_backfill b
JOIN after_backfill a ON b.season = a.season
ORDER BY b.season DESC;

-- ============================================================================
-- Summary Report
-- ============================================================================
SELECT 
  '=== BACKFILL VALIDATION SUMMARY ===' as report_section,
  CURRENT_TIMESTAMP() as validation_time;
