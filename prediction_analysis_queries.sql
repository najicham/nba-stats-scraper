-- Prediction System Performance Analysis Queries
-- Date: January 18, 2026
-- Dataset: nba-props-platform.nba_predictions.prediction_accuracy_real_lines
-- Purpose: Analyze all 6 prediction systems for ensemble retraining

-- ============================================================================
-- QUERY 1: Overall System Performance (Last 30 Days or All 2026 Data)
-- ============================================================================
SELECT
  system_id,
  COUNT(*) as total_predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SQRT(AVG(POWER(signed_error, 2))), 2) as rmse,
  ROUND(STDDEV(signed_error), 2) as std_dev,
  ROUND(AVG(signed_error), 2) as mean_bias,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct,
  ROUND(AVG(CASE WHEN recommendation = 'OVER' THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_pct,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'  -- Adjust date range as needed
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1', 'moving_average', 'zone_matchup_v1', 'similarity_balanced_v1')
GROUP BY system_id
ORDER BY mae ASC;

-- ============================================================================
-- QUERY 2: Performance by Confidence Tier
-- ============================================================================
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.8 THEN 'HIGH (0.8+)'
    WHEN confidence_score >= 0.5 THEN 'MEDIUM (0.5-0.8)'
    ELSE 'LOW (<0.5)'
  END as confidence_tier,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct,
  ROUND(AVG(confidence_score) * 100, 1) as avg_conf_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1', 'moving_average', 'zone_matchup_v1', 'similarity_balanced_v1')
GROUP BY system_id, confidence_tier
ORDER BY system_id, confidence_tier DESC;

-- ============================================================================
-- QUERY 3: Detailed Confidence Calibration
-- ============================================================================
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 0.9 THEN '0.9+ (Very High)'
    WHEN confidence_score >= 0.8 THEN '0.8-0.9 (High)'
    WHEN confidence_score >= 0.7 THEN '0.7-0.8 (Med-High)'
    WHEN confidence_score >= 0.5 THEN '0.5-0.7 (Medium)'
    ELSE '<0.5 (Low)'
  END as confidence_bucket,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct,
  ROUND(AVG(confidence_score) * 100, 1) as avg_conf
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1')
GROUP BY system_id, confidence_bucket
ORDER BY system_id, confidence_bucket DESC;

-- ============================================================================
-- QUERY 4: OVER vs UNDER Bias Analysis
-- ============================================================================
SELECT
  system_id,
  recommendation,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as mean_bias,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND recommendation IN ('OVER', 'UNDER')
  AND system_id IN ('catboost_v8', 'ensemble_v1', 'moving_average', 'zone_matchup_v1', 'similarity_balanced_v1')
GROUP BY system_id, recommendation
ORDER BY system_id, recommendation;

-- ============================================================================
-- QUERY 5: Daily Performance Trend
-- ============================================================================
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1')
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id
LIMIT 50;

-- ============================================================================
-- QUERY 6: Weekly Performance Trends
-- ============================================================================
SELECT
  system_id,
  EXTRACT(WEEK FROM game_date) as week_num,
  MIN(game_date) as week_start,
  MAX(game_date) as week_end,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1')
GROUP BY system_id, week_num
ORDER BY week_num, system_id;

-- ============================================================================
-- QUERY 7: System Agreement and Head-to-Head Comparison
-- ============================================================================
WITH predictions_combined AS (
  SELECT
    player_lookup,
    game_id,
    game_date,
    actual_points,
    MAX(CASE WHEN system_id = 'catboost_v8' THEN predicted_points END) as catboost_pred,
    MAX(CASE WHEN system_id = 'catboost_v8' THEN absolute_error END) as catboost_error,
    MAX(CASE WHEN system_id = 'ensemble_v1' THEN predicted_points END) as ensemble_pred,
    MAX(CASE WHEN system_id = 'ensemble_v1' THEN absolute_error END) as ensemble_error,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as similarity_pred,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN absolute_error END) as similarity_error,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone_pred,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN absolute_error END) as zone_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
  WHERE game_date >= '2026-01-01'
    AND has_real_line = true
    AND is_voided = false
    AND actual_points IS NOT NULL
  GROUP BY player_lookup, game_id, game_date, actual_points
  HAVING COUNT(DISTINCT system_id) >= 2
)
SELECT
  COUNT(*) as games_with_multiple_systems,
  ROUND(AVG(ABS(catboost_pred - ensemble_pred)), 2) as avg_catboost_ensemble_diff,
  ROUND(AVG(ABS(catboost_pred - similarity_pred)), 2) as avg_catboost_similarity_diff,
  ROUND(AVG(ABS(ensemble_pred - similarity_pred)), 2) as avg_ensemble_similarity_diff,
  ROUND(100.0 * SUM(CASE WHEN catboost_error < ensemble_error THEN 1 ELSE 0 END) / COUNT(*), 1) as catboost_beats_ensemble_pct,
  ROUND(100.0 * SUM(CASE WHEN catboost_error < similarity_error THEN 1 ELSE 0 END) / COUNT(*), 1) as catboost_beats_similarity_pct,
  ROUND(100.0 * SUM(CASE WHEN ensemble_error < similarity_error THEN 1 ELSE 0 END) / COUNT(*), 1) as ensemble_beats_similarity_pct
FROM predictions_combined
WHERE catboost_pred IS NOT NULL
  AND ensemble_pred IS NOT NULL;

-- ============================================================================
-- QUERY 8: Head-to-Head CatBoost vs Ensemble (Detailed)
-- ============================================================================
WITH head_to_head AS (
  SELECT
    c.game_date,
    c.player_lookup,
    c.actual_points,
    c.predicted_points as catboost_pred,
    c.absolute_error as catboost_error,
    c.confidence_score as catboost_conf,
    e.predicted_points as ensemble_pred,
    e.absolute_error as ensemble_error,
    e.confidence_score as ensemble_conf,
    CASE
      WHEN c.absolute_error < e.absolute_error THEN 'catboost'
      WHEN e.absolute_error < c.absolute_error THEN 'ensemble'
      ELSE 'tie'
    END as winner
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines` c
  JOIN `nba-props-platform.nba_predictions.prediction_accuracy_real_lines` e
    ON c.player_lookup = e.player_lookup
    AND c.game_id = e.game_id
  WHERE c.system_id = 'catboost_v8'
    AND e.system_id = 'ensemble_v1'
    AND c.game_date >= '2026-01-01'
    AND c.has_real_line = true
    AND c.is_voided = false
    AND c.actual_points IS NOT NULL
)
SELECT
  winner,
  COUNT(*) as games,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct,
  ROUND(AVG(catboost_error), 2) as avg_catboost_mae,
  ROUND(AVG(ensemble_error), 2) as avg_ensemble_mae,
  ROUND(AVG(catboost_error - ensemble_error), 2) as avg_diff
FROM head_to_head
GROUP BY winner
ORDER BY games DESC;

-- ============================================================================
-- QUERY 9: Recommendation Agreement Analysis
-- ============================================================================
WITH paired_predictions AS (
  SELECT
    c.player_lookup,
    c.game_id,
    c.game_date,
    c.actual_points,
    c.recommendation as catboost_rec,
    c.predicted_points as catboost_pred,
    c.absolute_error as catboost_error,
    e.recommendation as ensemble_rec,
    e.predicted_points as ensemble_pred,
    e.absolute_error as ensemble_error,
    CASE
      WHEN c.recommendation = e.recommendation THEN 'AGREE'
      ELSE 'DISAGREE'
    END as agreement
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines` c
  JOIN `nba-props-platform.nba_predictions.prediction_accuracy_real_lines` e
    ON c.player_lookup = e.player_lookup AND c.game_id = e.game_id
  WHERE c.system_id = 'catboost_v8'
    AND e.system_id = 'ensemble_v1'
    AND c.game_date >= '2026-01-01'
    AND c.has_real_line = true
    AND c.is_voided = false
    AND c.actual_points IS NOT NULL
    AND c.recommendation IN ('OVER', 'UNDER')
    AND e.recommendation IN ('OVER', 'UNDER')
)
SELECT
  agreement,
  COUNT(*) as games,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_total,
  ROUND(AVG(catboost_error), 2) as avg_catboost_mae,
  ROUND(AVG(ensemble_error), 2) as avg_ensemble_mae,
  ROUND(AVG(ABS(catboost_pred - ensemble_pred)), 2) as avg_pred_diff
FROM paired_predictions
GROUP BY agreement
ORDER BY games DESC;

-- ============================================================================
-- QUERY 10: When Does Ensemble Beat All Individual Systems?
-- ============================================================================
WITH all_systems AS (
  SELECT
    player_lookup,
    game_id,
    actual_points,
    MAX(CASE WHEN system_id = 'ensemble_v1' THEN absolute_error END) as ensemble_error,
    MAX(CASE WHEN system_id = 'catboost_v8' THEN absolute_error END) as catboost_error,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN absolute_error END) as similarity_error,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN absolute_error END) as zone_error,
    MAX(CASE WHEN system_id = 'moving_average' THEN absolute_error END) as moving_avg_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
  WHERE game_date >= '2026-01-01'
    AND has_real_line = true
    AND is_voided = false
    AND actual_points IS NOT NULL
  GROUP BY player_lookup, game_id, actual_points
  HAVING ensemble_error IS NOT NULL
    AND catboost_error IS NOT NULL
)
SELECT
  CASE
    WHEN ensemble_error < catboost_error
      AND ensemble_error < COALESCE(similarity_error, 999)
      AND ensemble_error < COALESCE(zone_error, 999)
      AND ensemble_error < COALESCE(moving_avg_error, 999) THEN 'Ensemble Best'
    WHEN catboost_error < ensemble_error THEN 'CatBoost Better'
    ELSE 'Tie/Other Better'
  END as outcome,
  COUNT(*) as games,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct,
  ROUND(AVG(ensemble_error), 2) as avg_ensemble_mae,
  ROUND(AVG(catboost_error), 2) as avg_catboost_mae
FROM all_systems
GROUP BY outcome
ORDER BY games DESC;

-- ============================================================================
-- QUERY 11: Error Distribution Percentiles
-- ============================================================================
SELECT
  system_id,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(10)] as p10_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(25)] as p25_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(50)] as median_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(75)] as p75_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(90)] as p90_error,
  APPROX_QUANTILES(absolute_error, 100)[OFFSET(95)] as p95_error,
  MAX(absolute_error) as max_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
  AND system_id IN ('catboost_v8', 'ensemble_v1', 'similarity_balanced_v1', 'zone_matchup_v1')
GROUP BY system_id
ORDER BY median_error ASC;

-- ============================================================================
-- QUERY 12: Month-over-Month Performance Comparison
-- ============================================================================
WITH jan_performance AS (
  SELECT
    system_id,
    'January 2026' as period,
    COUNT(*) as predictions,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
  WHERE game_date >= '2026-01-01'
    AND has_real_line = true
    AND is_voided = false
    AND actual_points IS NOT NULL
    AND system_id IN ('catboost_v8', 'ensemble_v1')
  GROUP BY system_id
),
dec_performance AS (
  SELECT
    system_id,
    'December 2025' as period,
    COUNT(*) as predictions,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(100.0 * SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
  WHERE game_date >= '2025-12-01' AND game_date <= '2025-12-31'
    AND has_real_line = true
    AND is_voided = false
    AND actual_points IS NOT NULL
    AND system_id IN ('catboost_v8', 'ensemble_v1')
  GROUP BY system_id
)
SELECT * FROM jan_performance
UNION ALL
SELECT * FROM dec_performance
ORDER BY system_id, period DESC;

-- ============================================================================
-- QUERY 13: Check All Available Systems
-- ============================================================================
SELECT
  system_id,
  COUNT(*) as total_predictions,
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction,
  ROUND(AVG(absolute_error), 2) as avg_mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE has_real_line = true
  AND actual_points IS NOT NULL
GROUP BY system_id
ORDER BY total_predictions DESC;

-- ============================================================================
-- QUERY 14: Data Coverage and Freshness Check
-- ============================================================================
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(DISTINCT game_date) as game_days,
  COUNT(*) as total_records,
  COUNT(DISTINCT CASE WHEN actual_points IS NOT NULL THEN game_date END) as graded_days,
  COUNT(DISTINCT system_id) as unique_systems
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2025-11-01'
  AND has_real_line = true
GROUP BY year, month
ORDER BY year DESC, month DESC;

-- ============================================================================
-- UTILITY QUERIES
-- ============================================================================

-- Check system coverage gaps
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / MAX(COUNT(*)) OVER(), 1) as coverage_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-01'
  AND has_real_line = true
  AND is_voided = false
  AND actual_points IS NOT NULL
GROUP BY system_id
ORDER BY predictions DESC;

-- Sample predictions to verify data quality
SELECT
  player_lookup,
  game_id,
  game_date,
  system_id,
  predicted_points,
  actual_points,
  absolute_error,
  confidence_score,
  recommendation
FROM `nba-props-platform.nba_predictions.prediction_accuracy_real_lines`
WHERE game_date >= '2026-01-15'
  AND has_real_line = true
  AND actual_points IS NOT NULL
ORDER BY game_date DESC, player_lookup, system_id
LIMIT 20;
