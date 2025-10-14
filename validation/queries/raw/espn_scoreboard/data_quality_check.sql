-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/data_quality_check.sql
-- Purpose: Comprehensive data quality validation for ESPN scoreboard data
-- Usage: Verify score reasonableness, completion status, confidence scores
-- ============================================================================
-- Expected Results:
--   - All games should have reasonable scores (60-170 range typical)
--   - is_completed should match game_status = 'final'
--   - processing_confidence should always be 1.0 (ESPN reliable)
--   - No NULL scores for completed games
-- ============================================================================

WITH 
-- Overall data quality metrics
quality_metrics AS (
  SELECT 
    COUNT(*) as total_games,
    COUNT(CASE WHEN is_completed = TRUE THEN 1 END) as completed_games,
    COUNT(CASE WHEN is_completed = FALSE THEN 1 END) as in_progress_games,
    
    -- Score validation
    COUNT(CASE WHEN home_team_score IS NULL OR away_team_score IS NULL THEN 1 END) as null_scores,
    COUNT(CASE WHEN home_team_score + away_team_score < 100 THEN 1 END) as very_low_scores,
    COUNT(CASE WHEN home_team_score + away_team_score > 280 THEN 1 END) as very_high_scores,
    COUNT(CASE WHEN home_team_score = away_team_score AND is_completed = TRUE THEN 1 END) as tied_final_games,
    
    -- Winner validation
    COUNT(CASE WHEN home_team_winner = TRUE AND away_team_winner = TRUE THEN 1 END) as both_winners,
    COUNT(CASE WHEN home_team_winner = FALSE AND away_team_winner = FALSE THEN 1 END) as no_winner_completed,
    COUNT(CASE WHEN (home_team_score > away_team_score) != home_team_winner AND is_completed = TRUE THEN 1 END) as wrong_winner_flag,
    
    -- Confidence and status
    AVG(processing_confidence) as avg_confidence,
    COUNT(CASE WHEN processing_confidence != 1.0 THEN 1 END) as non_perfect_confidence,
    COUNT(CASE WHEN is_completed = TRUE AND game_status != 'final' THEN 1 END) as status_mismatch,
    
    -- Timestamp validation
    COUNT(CASE WHEN created_at > processed_at THEN 1 END) as time_logic_errors
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
),

-- Score distribution analysis
score_distribution AS (
  SELECT 
    CASE
      WHEN home_team_score + away_team_score < 150 THEN '< 150 (Very Low)'
      WHEN home_team_score + away_team_score < 180 THEN '150-179 (Low)'
      WHEN home_team_score + away_team_score < 210 THEN '180-209 (Normal Low)'
      WHEN home_team_score + away_team_score < 240 THEN '210-239 (Normal)'
      WHEN home_team_score + away_team_score < 270 THEN '240-269 (High)'
      ELSE '270+ (Very High)'
    END as score_range,
    COUNT(*) as games,
    ROUND(AVG(home_team_score + away_team_score), 1) as avg_total_score
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
    AND is_completed = TRUE
  GROUP BY score_range
),

-- Recent data quality (last 30 days)
recent_quality AS (
  SELECT 
    'Last 30 Days' as period,
    COUNT(*) as games,
    COUNT(CASE WHEN is_completed = TRUE THEN 1 END) as completed,
    AVG(processing_confidence) as avg_conf,
    COUNT(CASE WHEN home_team_score + away_team_score BETWEEN 180 AND 240 THEN 1 END) as normal_scores,
    COUNT(CASE WHEN home_team_score + away_team_score < 150 OR home_team_score + away_team_score > 280 THEN 1 END) as outlier_scores
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

-- Output: Combined results with proper BigQuery syntax
(
  SELECT 
    '📊 OVERALL QUALITY' as section,
    'Total/Completed' as metric,
    CAST(total_games AS STRING) as value,
    CONCAT('Null scores: ', null_scores) as detail1,
    CONCAT('Both winners: ', both_winners) as detail2,
    CONCAT('No winner: ', no_winner_completed) as detail3,
    CASE
      WHEN null_scores > 0 OR both_winners > 0 OR wrong_winner_flag > 0 THEN '🔴 Critical issues'
      WHEN very_low_scores > 5 OR very_high_scores > 5 THEN '⚠️ Check outliers'
      ELSE '✅ Quality good'
    END as status,
    1 as sort_order
  FROM quality_metrics

  UNION ALL

  SELECT 
    '📊 OVERALL QUALITY' as section,
    'Score Issues' as metric,
    CAST(very_low_scores AS STRING) as value,
    CONCAT('Very low (< 100): ', very_low_scores) as detail1,
    CONCAT('Very high (> 280): ', very_high_scores) as detail2,
    CONCAT('Tied finals: ', tied_final_games) as detail3,
    CASE
      WHEN very_low_scores > 10 OR very_high_scores > 10 THEN '⚠️ Review games'
      ELSE '✅ Acceptable'
    END as status,
    2 as sort_order
  FROM quality_metrics

  UNION ALL

  SELECT 
    '📊 OVERALL QUALITY' as section,
    'Confidence & Status' as metric,
    CAST(ROUND(avg_confidence, 3) AS STRING) as value,
    CONCAT('Non-1.0 confidence: ', non_perfect_confidence) as detail1,
    CONCAT('Status mismatches: ', status_mismatch) as detail2,
    CONCAT('Time logic errors: ', time_logic_errors) as detail3,
    CASE
      WHEN non_perfect_confidence > 0 THEN '⚠️ Unexpected'
      WHEN status_mismatch > 0 THEN '⚠️ Check status'
      ELSE '✅ Perfect'
    END as status,
    3 as sort_order
  FROM quality_metrics

  UNION ALL

  -- Output: Score distribution
  SELECT 
    '📈 SCORE DISTRIBUTION' as section,
    score_range as metric,
    CAST(games AS STRING) as value,
    CONCAT('Avg: ', avg_total_score) as detail1,
    CONCAT(ROUND(games * 100.0 / SUM(games) OVER(), 1), '%') as detail2,
    '' as detail3,
    CASE
      WHEN score_range LIKE '%Very Low%' OR score_range LIKE '%Very High%' THEN '⚪ Outliers'
      ELSE '✅ Normal'
    END as status,
    CASE score_range
      WHEN '< 150 (Very Low)' THEN 4
      WHEN '150-179 (Low)' THEN 5
      WHEN '180-209 (Normal Low)' THEN 6
      WHEN '210-239 (Normal)' THEN 7
      WHEN '240-269 (High)' THEN 8
      ELSE 9
    END as sort_order
  FROM score_distribution

  UNION ALL

  -- Output: Recent quality
  SELECT 
    '📅 RECENT QUALITY' as section,
    period as metric,
    CAST(games AS STRING) as value,
    CONCAT('Completed: ', completed) as detail1,
    CONCAT('Normal scores: ', normal_scores) as detail2,
    CONCAT('Outliers: ', outlier_scores) as detail3,
    CASE
      WHEN outlier_scores > games * 0.1 THEN '⚠️ High outlier rate'
      ELSE '✅ Good'
    END as status,
    10 as sort_order
  FROM recent_quality
)
ORDER BY sort_order;