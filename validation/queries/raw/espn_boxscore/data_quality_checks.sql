-- ============================================================================
-- File: validation/queries/raw/espn_boxscore/data_quality_checks.sql
-- ESPN Boxscore: Data Quality Checks
-- Purpose: Identify suspicious patterns in ESPN data when it exists
-- Focus: Quality validation, not completeness (sparse data is normal)
-- ============================================================================

WITH game_level_quality AS (
  SELECT 
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    COUNT(*) as player_count,
    COUNT(DISTINCT team_abbr) as team_count,
    COUNT(DISTINCT player_lookup) as unique_players,
    
    -- Stats validation
    COUNT(CASE WHEN points IS NULL THEN 1 END) as null_points,
    COUNT(CASE WHEN rebounds IS NULL THEN 1 END) as null_rebounds,
    COUNT(CASE WHEN assists IS NULL THEN 1 END) as null_assists,
    COUNT(CASE WHEN minutes IS NULL OR minutes = '0:00' THEN 1 END) as no_minutes,
    
    -- Unusual stats
    COUNT(CASE WHEN points > 50 THEN 1 END) as players_50plus_points,
    COUNT(CASE WHEN points = 0 AND minutes != '0:00' THEN 1 END) as zero_points_with_minutes,
    COUNT(CASE WHEN rebounds > 20 THEN 1 END) as players_20plus_rebounds,
    
    -- Team balance
    SUM(CASE WHEN team_abbr = home_team_abbr THEN 1 ELSE 0 END) as home_player_count,
    SUM(CASE WHEN team_abbr = away_team_abbr THEN 1 ELSE 0 END) as away_player_count,
    
    -- Score totals (basic sanity check)
    SUM(CASE WHEN team_abbr = home_team_abbr THEN points ELSE 0 END) as home_points_sum,
    SUM(CASE WHEN team_abbr = away_team_abbr THEN points ELSE 0 END) as away_points_sum
    
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= '2020-01-01'  -- Include all ESPN data
  GROUP BY game_date, game_id, home_team_abbr, away_team_abbr
),

player_level_quality AS (
  SELECT 
    game_date,
    game_id,
    player_lookup,
    player_full_name,
    team_abbr,
    
    -- Flag suspicious combinations
    CASE 
      WHEN points IS NULL THEN 'NULL_POINTS'
      WHEN points > 50 THEN 'VERY_HIGH_POINTS'
      WHEN points = 0 AND minutes != '0:00' THEN 'ZERO_POINTS_WITH_MINUTES'
      ELSE NULL
    END as points_issue,
    
    CASE 
      WHEN rebounds IS NULL THEN 'NULL_REBOUNDS'
      WHEN rebounds > 20 THEN 'VERY_HIGH_REBOUNDS'
      ELSE NULL
    END as rebounds_issue,
    
    CASE 
      WHEN minutes IS NULL OR minutes = '0:00' THEN 'NO_MINUTES'
      ELSE NULL
    END as minutes_issue,
    
    -- Actual values for investigation
    points,
    rebounds,
    assists,
    minutes
    
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= '2020-01-01'  -- Include all ESPN data
),

quality_summary AS (
  SELECT 
    COUNT(DISTINCT game_id) as total_games,
    
    -- Game-level issues
    COUNT(CASE WHEN player_count < 20 THEN 1 END) as games_low_player_count,
    COUNT(CASE WHEN player_count > 35 THEN 1 END) as games_high_player_count,
    COUNT(CASE WHEN team_count != 2 THEN 1 END) as games_wrong_team_count,
    COUNT(CASE WHEN home_player_count < 8 OR away_player_count < 8 THEN 1 END) as games_unbalanced_teams,
    
    -- Stat quality issues
    SUM(null_points) as total_null_points,
    SUM(null_rebounds) as total_null_rebounds,
    SUM(null_assists) as total_null_assists,
    SUM(no_minutes) as total_no_minutes,
    
    -- Unusual but valid stats
    SUM(players_50plus_points) as total_50plus_point_games,
    SUM(players_20plus_rebounds) as total_20plus_rebound_games,
    SUM(zero_points_with_minutes) as total_zero_points_with_minutes
    
  FROM game_level_quality
)

-- Output quality report
(
  SELECT 
    'GAME-LEVEL QUALITY' as check_category,
    'Total Games Analyzed' as metric,
    CAST(total_games AS STRING) as value,
    '✅ Reference' as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'GAME-LEVEL QUALITY' as check_category,
    'Low Player Count (<20)' as metric,
    CAST(games_low_player_count AS STRING) as value,
    CASE 
      WHEN games_low_player_count = 0 THEN '✅ None'
      ELSE '⚠️ Investigate these games'
    END as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'GAME-LEVEL QUALITY' as check_category,
    'High Player Count (>35)' as metric,
    CAST(games_high_player_count AS STRING) as value,
    CASE 
      WHEN games_high_player_count = 0 THEN '✅ None'
      ELSE '⚠️ Investigate these games'
    END as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'GAME-LEVEL QUALITY' as check_category,
    'Wrong Team Count (≠2)' as metric,
    CAST(games_wrong_team_count AS STRING) as value,
    CASE 
      WHEN games_wrong_team_count = 0 THEN '✅ None'
      ELSE '🔴 CRITICAL - Fix team assignments'
    END as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT QUALITY' as check_category,
    'NULL Points Values' as metric,
    CAST(total_null_points AS STRING) as value,
    CASE 
      WHEN total_null_points = 0 THEN '✅ None'
      ELSE '🔴 CRITICAL - Missing core stat'
    END as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT QUALITY' as check_category,
    'NULL Rebounds Values' as metric,
    CAST(total_null_rebounds AS STRING) as value,
    CASE 
      WHEN total_null_rebounds = 0 THEN '✅ None'
      ELSE '⚠️ Missing rebounds data'
    END as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'STAT QUALITY' as check_category,
    'Players with No Minutes' as metric,
    CAST(total_no_minutes AS STRING) as value,
    '⚪ DNP players (normal)' as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'UNUSUAL STATS' as check_category,
    '50+ Point Games' as metric,
    CAST(total_50plus_point_games AS STRING) as value,
    '⚪ Rare but valid' as status
  FROM quality_summary
  
  UNION ALL
  
  SELECT 
    'UNUSUAL STATS' as check_category,
    '20+ Rebound Games' as metric,
    CAST(total_20plus_rebound_games AS STRING) as value,
    '⚪ Rare but valid' as status
  FROM quality_summary
)

ORDER BY 
  CASE check_category
    WHEN 'GAME-LEVEL QUALITY' THEN 1
    WHEN 'STAT QUALITY' THEN 2
    WHEN 'UNUSUAL STATS' THEN 3
  END,
  metric;

-- ============================================================================
-- DETAILED PROBLEM GAMES (if any issues found)
-- ============================================================================
/*
-- Uncomment to investigate specific quality issues

-- Games with structural problems
SELECT 
  game_date,
  game_id,
  home_team_abbr || ' vs ' || away_team_abbr as matchup,
  player_count,
  team_count,
  home_player_count,
  away_player_count,
  CASE 
    WHEN player_count < 20 THEN '⚠️ Low total players'
    WHEN player_count > 35 THEN '⚠️ High total players'
    WHEN team_count != 2 THEN '🔴 Wrong team count'
    WHEN home_player_count < 8 THEN '⚠️ Low home players'
    WHEN away_player_count < 8 THEN '⚠️ Low away players'
    ELSE '✅ OK'
  END as issue
FROM game_level_quality
WHERE player_count < 20 
   OR player_count > 35 
   OR team_count != 2
   OR home_player_count < 8 
   OR away_player_count < 8
ORDER BY game_date DESC;

-- Players with stat issues
SELECT 
  game_date,
  game_id,
  player_full_name,
  team_abbr,
  points,
  rebounds,
  assists,
  minutes,
  COALESCE(points_issue, rebounds_issue, minutes_issue, 'Multiple issues') as issue_type
FROM player_level_quality
WHERE points_issue IS NOT NULL 
   OR rebounds_issue IS NOT NULL 
   OR minutes_issue IS NOT NULL
ORDER BY game_date DESC, player_full_name;
*/

-- ============================================================================
-- EXPECTED RESULTS (as of Oct 2025):
-- 
-- Total Games: 1 (single game in dataset)
-- All Quality Checks: ✅ Pass (ESPN data is high quality)
--
-- QUALITY THRESHOLDS:
-- 🔴 CRITICAL Issues:
--   - NULL points values (core stat missing)
--   - Wrong team count (≠2 teams per game)
--   - Player count <15 per game
--
-- ⚠️ WARNING Issues:
--   - Player count 15-19 or >35 (unusual but possible)
--   - Missing rebounds/assists (nice to have)
--   - Unbalanced teams (<8 players one side)
--
-- ⚪ NORMAL Patterns:
--   - DNP players with no minutes
--   - 50+ point games (rare but valid)
--   - 20+ rebound games (rare but valid)
-- ============================================================================
