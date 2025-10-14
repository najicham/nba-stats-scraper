-- ============================================================================
-- File: validation/queries/raw/nbac_player_boxscores/data_quality_checks.sql
-- Purpose: Validate enhanced metrics and data quality for NBA.com box scores
-- Usage: Run weekly to monitor data quality and enhanced metrics availability
-- ============================================================================
-- ⚠️ NOTE: Table is currently empty (awaiting NBA season start)
-- Many enhanced metrics are currently NULL (planned for future)
-- This query tracks when enhanced features become available
-- ============================================================================
-- Checks:
--   1. Enhanced metrics availability (TS%, usage rate, etc.)
--   2. Quarter breakdown availability
--   3. Official NBA player ID consistency
--   4. Starter flag validation
--   5. Plus/minus availability
--   6. Field goal percentage calculations
-- ============================================================================

WITH
-- Check if table has data
data_check AS (
  SELECT COUNT(*) as total_records
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

recent_data AS (
  SELECT
    game_date,
    game_id,
    player_lookup,
    player_full_name,
    nba_player_id,
    team_abbr,
    starter,
    minutes,
    points,
    field_goals_made,
    field_goals_attempted,
    field_goal_percentage,
    three_pointers_made,
    three_pointers_attempted,
    total_rebounds,
    assists,
    steals,
    blocks,
    turnovers,
    personal_fouls,
    flagrant_fouls,
    technical_fouls,
    plus_minus,
    
    -- Enhanced metrics (currently NULL but planned)
    true_shooting_pct,
    effective_fg_pct,
    usage_rate,
    offensive_rating,
    defensive_rating,
    pace,
    pie,
    
    -- Quarter breakdowns (currently NULL but planned)
    points_q1,
    points_q2,
    points_q3,
    points_q4,
    points_ot
    
  FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- Feature availability tracking
feature_availability AS (
  SELECT
    'Enhanced Metrics' as feature_category,
    'True Shooting %' as feature_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN true_shooting_pct IS NOT NULL THEN 1 END) as populated_records,
    ROUND(100.0 * COUNT(CASE WHEN true_shooting_pct IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1) as availability_pct
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Enhanced Metrics',
    'Effective FG %',
    COUNT(*),
    COUNT(CASE WHEN effective_fg_pct IS NOT NULL THEN 1 END),
    ROUND(100.0 * COUNT(CASE WHEN effective_fg_pct IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1)
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Enhanced Metrics',
    'Usage Rate',
    COUNT(*),
    COUNT(CASE WHEN usage_rate IS NOT NULL THEN 1 END),
    ROUND(100.0 * COUNT(CASE WHEN usage_rate IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1)
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Enhanced Metrics',
    'Offensive Rating',
    COUNT(*),
    COUNT(CASE WHEN offensive_rating IS NOT NULL THEN 1 END),
    ROUND(100.0 * COUNT(CASE WHEN offensive_rating IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1)
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Quarter Breakdown',
    'Points Q1-Q4',
    COUNT(*),
    COUNT(CASE WHEN points_q1 IS NOT NULL 
               OR points_q2 IS NOT NULL 
               OR points_q3 IS NOT NULL 
               OR points_q4 IS NOT NULL THEN 1 END),
    ROUND(100.0 * COUNT(CASE WHEN points_q1 IS NOT NULL 
               OR points_q2 IS NOT NULL 
               OR points_q3 IS NOT NULL 
               OR points_q4 IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1)
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Core Stats',
    'Plus/Minus',
    COUNT(*),
    COUNT(CASE WHEN plus_minus IS NOT NULL THEN 1 END),
    ROUND(100.0 * COUNT(CASE WHEN plus_minus IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 1)
  FROM recent_data
),

-- Data quality checks
quality_checks AS (
  SELECT
    'NBA Player ID' as check_category,
    'Missing NBA Player IDs' as check_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN nba_player_id IS NULL THEN 1 END) as issue_count,
    CASE 
      WHEN COUNT(CASE WHEN nba_player_id IS NULL THEN 1 END) = 0 THEN '✅ All present'
      ELSE CONCAT('⚠️ ', CAST(COUNT(CASE WHEN nba_player_id IS NULL THEN 1 END) AS STRING), ' missing')
    END as status
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Starter Flag',
    'Starters per game',
    COUNT(DISTINCT game_id),
    0,
    CASE
      WHEN COUNT(DISTINCT game_id) = 0 THEN '⚪ No data'
      WHEN AVG(starters_per_game) BETWEEN 9.5 AND 10.5 THEN '✅ Normal (~10 per game)'
      WHEN AVG(starters_per_game) < 9 THEN '⚠️ Too few starters'
      WHEN AVG(starters_per_game) > 11 THEN '⚠️ Too many starters'
      ELSE '✅ Acceptable range'
    END
  FROM (
    SELECT 
      game_id,
      COUNT(CASE WHEN starter = TRUE THEN 1 END) as starters_per_game
    FROM recent_data
    GROUP BY game_id
  )
  
  UNION ALL
  
  SELECT
    'Field Goal %',
    'FG% Calculation Match',
    COUNT(*),
    COUNT(CASE 
      WHEN field_goals_attempted > 0 
       AND field_goal_percentage IS NOT NULL
       AND ABS(field_goal_percentage - (CAST(field_goals_made AS FLOAT64) / field_goals_attempted)) > 0.01
      THEN 1 END),
    CASE
      WHEN COUNT(CASE 
        WHEN field_goals_attempted > 0 
         AND field_goal_percentage IS NOT NULL
         AND ABS(field_goal_percentage - (CAST(field_goals_made AS FLOAT64) / field_goals_attempted)) > 0.01
        THEN 1 END) = 0 THEN '✅ All match'
      ELSE CONCAT('⚠️ ', CAST(COUNT(CASE 
        WHEN field_goals_attempted > 0 
         AND field_goal_percentage IS NOT NULL
         AND ABS(field_goal_percentage - (CAST(field_goals_made AS FLOAT64) / field_goals_attempted)) > 0.01
        THEN 1 END) AS STRING), ' mismatches')
    END
  FROM recent_data
  
  UNION ALL
  
  SELECT
    'Fouls',
    'Technical/Flagrant Availability',
    COUNT(*),
    COUNT(*) - COUNT(CASE WHEN technical_fouls IS NOT NULL OR flagrant_fouls IS NOT NULL THEN 1 END),
    CASE
      WHEN COUNT(CASE WHEN technical_fouls IS NOT NULL OR flagrant_fouls IS NOT NULL THEN 1 END) > 0 
        THEN '✅ Data available'
      ELSE '⚪ No data (may be normal)'
    END
  FROM recent_data
)

-- No data message
SELECT
  '⚪ Status' as category,
  'No Data Available' as metric,
  0 as total_records,
  0 as value_or_count,
  'NBA.com player boxscores table is empty - awaiting season start' as status
FROM data_check
WHERE total_records = 0

UNION ALL

-- Feature availability
SELECT
  fa.feature_category as category,
  fa.feature_name as metric,
  fa.total_records,
  fa.populated_records as value_or_count,
  CASE
    WHEN fa.availability_pct = 0 THEN '⚪ Not yet available'
    WHEN fa.availability_pct < 50 THEN CONCAT('⚠️ Partial: ', CAST(fa.availability_pct AS STRING), '%')
    WHEN fa.availability_pct < 100 THEN CONCAT('✅ Mostly: ', CAST(fa.availability_pct AS STRING), '%')
    ELSE '✅ Complete: 100%'
  END as status
FROM feature_availability fa
CROSS JOIN data_check dc
WHERE dc.total_records > 0

UNION ALL

-- Quality checks
SELECT
  qc.check_category as category,
  qc.check_name as metric,
  qc.total_records,
  qc.issue_count as value_or_count,
  qc.status
FROM quality_checks qc
CROSS JOIN data_check dc
WHERE dc.total_records > 0

ORDER BY
  CASE category
    WHEN '⚪ Status' THEN 1
    WHEN 'Core Stats' THEN 2
    WHEN 'NBA Player ID' THEN 3
    WHEN 'Starter Flag' THEN 4
    WHEN 'Field Goal %' THEN 5
    WHEN 'Fouls' THEN 6
    WHEN 'Enhanced Metrics' THEN 7
    WHEN 'Quarter Breakdown' THEN 8
  END,
  metric;