-- ============================================================================
-- FILE: validation/queries/raw/espn_boxscore/check_bdl_coverage_jan2025.sql
-- ============================================================================
-- Check BDL coverage around 2025-01-15 to see if it's a gap or specific miss
-- ============================================================================

-- Check BDL games around ESPN game date
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as player_records,
  STRING_AGG(
    CONCAT(away_team_abbr, '@', home_team_abbr),
    ', '
  ) as matchups
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date BETWEEN '2025-01-14' AND '2025-01-16'  -- 3 days around ESPN game
GROUP BY game_date
ORDER BY game_date;

-- Check if BDL has ANY data for 2025-01-15 specifically
SELECT
  '=== BDL on 2025-01-15 ===' as check,
  CASE 
    WHEN COUNT(*) = 0 THEN '🔴 BDL has NO games on 2025-01-15'
    ELSE CONCAT('✅ BDL has ', CAST(COUNT(DISTINCT game_id) AS STRING), ' games on 2025-01-15')
  END as status
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2025-01-15';
