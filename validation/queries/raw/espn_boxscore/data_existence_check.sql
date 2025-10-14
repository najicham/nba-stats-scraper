-- ============================================================================
-- File: validation/queries/raw/espn_boxscore/data_existence_check.sql
-- ESPN Boxscore: Data Existence Check
-- Purpose: Verify ESPN backup data exists and understand its scope
-- Pattern: Sparse Backup Source - Existence validation, not completeness
-- ============================================================================

WITH espn_coverage AS (
  SELECT 
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(DISTINCT game_date) as dates_with_data,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(*) as total_player_records,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT team_abbr) as unique_teams,
    
    -- Season breakdown
    COUNT(DISTINCT CASE WHEN season_year = 2024 THEN game_id END) as games_2024_25,
    COUNT(DISTINCT CASE WHEN season_year = 2023 THEN game_id END) as games_2023_24,
    COUNT(DISTINCT CASE WHEN season_year = 2025 THEN game_id END) as games_2025_26,
    
    -- Recent activity
    COUNT(DISTINCT CASE WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN game_id END) as games_last_7_days,
    COUNT(DISTINCT CASE WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) THEN game_id END) as games_last_30_days
    
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= '2023-10-01'
),

per_game_stats AS (
  SELECT 
    game_date,
    game_id,
    COUNT(*) as player_count,
    COUNT(DISTINCT team_abbr) as team_count,
    AVG(points) as avg_points_per_player,
    MAX(points) as max_points
  FROM `nba-props-platform.nba_raw.espn_boxscores`
  WHERE game_date >= '2023-10-01'
  GROUP BY game_date, game_id
),

game_quality_summary AS (
  SELECT 
    AVG(player_count) as avg_players_per_game,
    MIN(player_count) as min_players_per_game,
    MAX(player_count) as max_players_per_game,
    COUNT(CASE WHEN player_count < 20 THEN 1 END) as games_with_low_player_count,
    COUNT(CASE WHEN team_count != 2 THEN 1 END) as games_with_wrong_team_count
  FROM per_game_stats
)

-- Output summary
SELECT 
  'ESPN BOXSCORE DATA EXISTENCE CHECK' as check_type,
  '' as separator1,
  
  '=== OVERALL COVERAGE ===' as section1,
  CAST(c.earliest_date AS STRING) as earliest_game,
  CAST(c.latest_date AS STRING) as latest_game,
  CAST(c.dates_with_data AS STRING) as total_dates,
  CAST(c.unique_games AS STRING) as total_games,
  CAST(c.total_player_records AS STRING) as total_player_records,
  '' as separator2,
  
  '=== SEASON BREAKDOWN ===' as section2,
  CAST(c.games_2023_24 AS STRING) as games_2023_24_season,
  CAST(c.games_2024_25 AS STRING) as games_2024_25_season,
  CAST(c.games_2025_26 AS STRING) as games_2025_26_season,
  '' as separator3,
  
  '=== RECENT ACTIVITY ===' as section3,
  CAST(c.games_last_7_days AS STRING) as games_last_7_days,
  CAST(c.games_last_30_days AS STRING) as games_last_30_days,
  CASE 
    WHEN c.games_last_7_days > 0 THEN '✅ Recent data exists'
    WHEN c.games_last_30_days > 0 THEN '⚪ Data exists but not recent'
    ELSE '⚠️ No recent data (expected for backup source)'
  END as recent_status,
  '' as separator4,
  
  '=== DATA QUALITY ===' as section4,
  CAST(ROUND(q.avg_players_per_game, 1) AS STRING) as avg_players_per_game,
  CAST(q.min_players_per_game AS STRING) as min_players,
  CAST(q.max_players_per_game AS STRING) as max_players,
  CAST(q.games_with_low_player_count AS STRING) as games_with_low_player_count,
  CAST(q.games_with_wrong_team_count AS STRING) as games_wrong_team_count,
  '' as separator5,
  
  '=== STATUS ===' as section5,
  CASE 
    WHEN c.unique_games = 0 THEN '🔴 CRITICAL: No ESPN data exists'
    WHEN c.unique_games < 5 THEN '⚪ MINIMAL: Very sparse coverage (expected for backup)'
    WHEN c.unique_games < 50 THEN '✅ GOOD: Sparse backup data exists'
    ELSE '✅ EXCELLENT: Substantial backup data'
  END as overall_status

FROM espn_coverage c
CROSS JOIN game_quality_summary q;

-- ============================================================================
-- EXPECTED RESULTS (as of Oct 2025):
-- 
-- Total Games: 1 (extremely sparse - backup source only)
-- Date Range: 2025-01-15 to 2025-01-15
-- Recent Activity: Minimal (backup collection is ad-hoc)
-- Player Count: ~25 per game (20-30 expected)
-- Quality: High when data exists
--
-- STATUS INTERPRETATION:
-- ⚪ MINIMAL coverage = NORMAL for backup source
-- ✅ GOOD quality = Expected when data exists
-- 
-- CRITICAL UNDERSTANDING:
-- ESPN is a sparse backup source. Low game counts are EXPECTED and NORMAL.
-- This is NOT a completeness check - it's an existence verification.
-- ============================================================================
