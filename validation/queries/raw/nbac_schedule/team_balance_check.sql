-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/team_balance_check.sql
-- Purpose: Detect teams with unusual game counts (anomaly detection)
-- Usage: Run regularly to ensure all teams have similar game counts
-- ============================================================================
-- Instructions:
--   1. Update date range for the period you're checking
--   2. All teams should be within ~2-3 games of league average
--   3. Large deviations indicate missing data or unusual scheduling
-- ============================================================================
-- Expected Results:
--   - All teams should have similar total games at any point in season
--   - Each team should have ~41 home + ~41 away games
--   - Large deviations (>3 games from average) = data quality issue
-- ============================================================================

WITH
-- Get regular season games only (playoff imbalance is expected!)
regular_season_games AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_team_name,
    away_team_name
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()  -- UPDATE: Date range
    AND is_regular_season = TRUE
    AND is_playoffs = FALSE
    AND game_date >= '2024-10-22'  -- Partition filter
),

-- Expand to team-game combinations with location
team_games AS (
  SELECT 
    home_team_tricode as team,
    home_team_name as team_name,
    'home' as location,
    game_id
  FROM regular_season_games
  
  UNION ALL
  
  SELECT 
    away_team_tricode as team,
    away_team_name as team_name,
    'away' as location,
    game_id
  FROM regular_season_games
),

-- Count games by team and location
team_game_counts AS (
  SELECT
    team,
    MAX(team_name) as team_name,
    COUNT(DISTINCT CASE WHEN location = 'home' THEN game_id END) as home_games,
    COUNT(DISTINCT CASE WHEN location = 'away' THEN game_id END) as away_games,
    COUNT(DISTINCT game_id) as total_games
  FROM team_games
  GROUP BY team
),

-- Calculate league statistics
league_stats AS (
  SELECT
    AVG(total_games) as avg_total,
    STDDEV(total_games) as stddev_total,
    MAX(total_games) as max_total,
    MIN(total_games) as min_total,
    AVG(home_games) as avg_home,
    AVG(away_games) as avg_away
  FROM team_game_counts
),

-- Find teams with unusual counts
team_analysis AS (
  SELECT
    t.team,
    t.team_name,
    t.home_games,
    t.away_games,
    t.total_games,
    l.avg_total,
    t.total_games - l.avg_total as games_diff,
    t.home_games - t.away_games as home_away_diff,
    CASE
      WHEN ABS(t.total_games - l.avg_total) > 5 THEN '🔴 CRITICAL: >5 games from average'
      WHEN ABS(t.total_games - l.avg_total) > 3 THEN '🟡 WARNING: >3 games from average'
      WHEN ABS(t.home_games - t.away_games) > 3 THEN '🟡 WARNING: Home/away imbalance'
      ELSE '✅ Normal'
    END as status,
    RANK() OVER (ORDER BY t.total_games DESC) as rank_most_games,
    RANK() OVER (ORDER BY t.total_games ASC) as rank_fewest_games
  FROM team_game_counts t
  CROSS JOIN league_stats l
)

-- Output: Team balance analysis
SELECT
  '=== LEAGUE SUMMARY ===' as section,
  '' as team,
  '' as home_games,
  '' as away_games,
  '' as total_games,
  '' as games_diff,
  '' as status

UNION ALL

SELECT
  'League Average' as section,
  '' as team,
  CAST(ROUND(avg_home, 1) AS STRING) as home_games,
  CAST(ROUND(avg_away, 1) AS STRING) as away_games,
  CAST(ROUND(avg_total, 1) AS STRING) as total_games,
  CONCAT(CAST(ROUND(min_total, 0) AS STRING), ' to ', CAST(ROUND(max_total, 0) AS STRING)) as games_diff,
  '' as status
FROM league_stats

UNION ALL

SELECT
  '' as section,
  '' as team,
  '' as home_games,
  '' as away_games,
  '' as total_games,
  '' as games_diff,
  '' as status

UNION ALL

SELECT
  '=== TEAM ANALYSIS ===' as section,
  '' as team,
  '' as home_games,
  '' as away_games,
  '' as total_games,
  '' as games_diff,
  '' as status

UNION ALL

SELECT
  team as section,
  team_name as team,
  CAST(home_games AS STRING) as home_games,
  CAST(away_games AS STRING) as away_games,
  CAST(total_games AS STRING) as total_games,
  CONCAT(
    CASE 
      WHEN games_diff > 0 THEN '+'
      ELSE ''
    END,
    CAST(ROUND(games_diff, 1) AS STRING)
  ) as games_diff,
  status
FROM team_analysis
ORDER BY 
  CASE section
    WHEN '=== LEAGUE SUMMARY ===' THEN 0
    WHEN 'League Average' THEN 1
    WHEN '' THEN 2
    WHEN '=== TEAM ANALYSIS ===' THEN 3
    ELSE 4
  END,
  section;  -- Order by section for team rows