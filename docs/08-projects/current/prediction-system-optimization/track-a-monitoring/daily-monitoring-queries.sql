-- XGBoost V1 Daily Performance Monitoring
-- Created: 2026-01-18
-- Purpose: Track XGBoost V1 V2 production performance
-- Run: Daily (morning after games complete)
-- Baseline: Validation MAE 3.726, Target Production MAE ≤ 4.2

-- =============================================================================
-- QUERY 1: Overall Daily Performance Summary
-- =============================================================================
-- Use this as your primary daily check
-- Expected: MAE ~3.73 ± 0.5, Win Rate ≥52%, Zero placeholders

SELECT
  game_date,

  -- Volume metrics
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,

  -- Performance metrics
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate_pct,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(STDDEV(absolute_error), 2) as mae_stddev,

  -- Quality metrics
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  ROUND(MIN(confidence_score), 3) as min_confidence,
  ROUND(MAX(confidence_score), 3) as max_confidence,

  -- Prediction range
  ROUND(AVG(predicted_points), 1) as avg_prediction,
  ROUND(MIN(predicted_points), 1) as min_prediction,
  ROUND(MAX(predicted_points), 1) as max_prediction,

  -- Edge over breakeven (52.4%)
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100 - 52.4, 1) as edge_over_breakeven,

  -- Alert flags
  CASE
    WHEN AVG(absolute_error) > 4.2 THEN '🚨 HIGH MAE'
    WHEN AVG(absolute_error) > 4.0 THEN '⚠️ ELEVATED MAE'
    ELSE '✅ GOOD'
  END as mae_status,

  CASE
    WHEN SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) < 0.50 THEN '🚨 LOW WIN RATE'
    WHEN SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) < 0.52 THEN '⚠️ BELOW BREAKEVEN'
    ELSE '✅ GOOD'
  END as win_rate_status

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-18'  -- XGBoost V1 V2 deployment date
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30;

-- Expected Output (when grading working):
-- - mae: 3.2 to 4.2 (within range)
-- - win_rate_pct: 52-60%
-- - mae_status: ✅ GOOD
-- - win_rate_status: ✅ GOOD


-- =============================================================================
-- QUERY 2: Week-to-Date Summary
-- =============================================================================
-- Roll-up for weekly review
-- Compare to baseline: MAE 3.726, check for degradation

SELECT
  'Week-to-Date' as period,
  MIN(game_date) as start_date,
  MAX(game_date) as end_date,
  COUNT(DISTINCT game_date) as days_with_data,

  -- Volume
  COUNT(*) as total_predictions,
  ROUND(COUNT(*) / COUNT(DISTINCT game_date), 0) as avg_predictions_per_day,

  -- Performance
  COUNTIF(prediction_correct = TRUE) as total_wins,
  COUNTIF(prediction_correct = FALSE) as total_losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as overall_win_rate,
  ROUND(AVG(absolute_error), 2) as overall_mae,

  -- vs Baseline
  ROUND(AVG(absolute_error) - 3.726, 2) as mae_vs_validation,
  ROUND((AVG(absolute_error) - 3.726) / 3.726 * 100, 1) as pct_change_vs_validation,

  -- Status
  CASE
    WHEN AVG(absolute_error) <= 4.2 THEN '✅ ON TARGET'
    WHEN AVG(absolute_error) <= 4.5 THEN '⚠️ ELEVATED'
    ELSE '🚨 ABOVE THRESHOLD'
  END as performance_status

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND game_date >= '2026-01-18'  -- Only V2 data
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE;

-- Expected:
-- - overall_mae: Within ±15% of 3.726 (3.2 to 4.2)
-- - performance_status: ✅ ON TARGET


-- =============================================================================
-- QUERY 3: OVER vs UNDER Performance
-- =============================================================================
-- Check for bias in predictions
-- Both should be roughly equal

SELECT
  recommendation,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(predicted_margin), 2) as avg_predicted_edge,

  -- Distribution
  COUNTIF(predicted_margin BETWEEN 0 AND 2) as small_edge_0_2,
  COUNTIF(predicted_margin BETWEEN 2 AND 5) as medium_edge_2_5,
  COUNTIF(predicted_margin > 5) as large_edge_5plus

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-18'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY recommendation;

-- Expected:
-- - Both OVER and UNDER should have similar win rates (within 5%)
-- - No significant bias toward one direction


-- =============================================================================
-- QUERY 4: Confidence Tier Analysis
-- =============================================================================
-- Validate that higher confidence = higher accuracy
-- This is critical for calibration

SELECT
  CASE
    WHEN confidence_score >= 0.90 THEN '1. VERY HIGH (90%+)'
    WHEN confidence_score >= 0.80 THEN '2. HIGH (80-90%)'
    WHEN confidence_score >= 0.70 THEN '3. MEDIUM-HIGH (70-80%)'
    WHEN confidence_score >= 0.60 THEN '4. MEDIUM (60-70%)'
    WHEN confidence_score >= 0.55 THEN '5. MEDIUM-LOW (55-60%)'
    ELSE '6. LOW (<55%)'
  END as confidence_tier,

  COUNT(*) as predictions,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence_pct,

  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,

  -- Calibration check
  ROUND(AVG(confidence_score) * 100, 1) as expected_win_rate,
  ROUND(
    SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100 - AVG(confidence_score) * 100,
    1
  ) as calibration_gap

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-18'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY confidence_tier
ORDER BY confidence_tier;

-- Expected:
-- - Higher confidence tiers should have higher win rates
-- - Calibration gap should be within ±10%
-- - If calibration is off, model needs recalibration


-- =============================================================================
-- QUERY 5: Recent Trend (Last 7 Days)
-- =============================================================================
-- Check for performance degradation over time

SELECT
  game_date,
  COUNT(*) as predictions,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(confidence_score), 3) as avg_confidence,

  -- 3-day moving average (helps smooth daily variance)
  ROUND(AVG(AVG(absolute_error)) OVER (
    ORDER BY game_date
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ), 2) as mae_3day_ma

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND game_date >= '2026-01-18'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC;

-- Expected:
-- - No consistent upward trend in MAE (would indicate degradation)
-- - Daily variance is normal, look at 3-day moving average for trends


-- =============================================================================
-- QUERY 6: Prediction Volume Check
-- =============================================================================
-- Ensure system is generating expected volume
-- Alert if volume drops significantly

WITH daily_volume AS (
  SELECT
    game_date,
    COUNT(*) as predictions,
    COUNT(DISTINCT player_lookup) as players
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= '2026-01-18'
  GROUP BY game_date
)
SELECT
  game_date,
  predictions,
  players,

  -- Compare to baseline (280 predictions on 2026-01-18)
  predictions - 280 as vs_baseline,
  ROUND((predictions - 280.0) / 280 * 100, 1) as pct_change,

  -- Status
  CASE
    WHEN predictions < 140 THEN '🚨 VOLUME DROP >50%'
    WHEN predictions < 224 THEN '⚠️ VOLUME DROP >20%'
    ELSE '✅ NORMAL'
  END as volume_status

FROM daily_volume
ORDER BY game_date DESC;

-- Expected:
-- - predictions: 200-600 depending on games scheduled
-- - volume_status: ✅ NORMAL
-- - Alert if 🚨 VOLUME DROP appears


-- =============================================================================
-- USAGE INSTRUCTIONS
-- =============================================================================

-- DAILY ROUTINE (5 minutes):
-- 1. Run QUERY 1 (Overall Daily Performance)
-- 2. Check mae_status and win_rate_status
-- 3. If any 🚨 or ⚠️ appears, investigate
-- 4. Log results in PROGRESS-LOG.md

-- WEEKLY ROUTINE (15 minutes):
-- 1. Run QUERY 2 (Week-to-Date Summary)
-- 2. Run QUERY 3 (OVER vs UNDER)
-- 3. Run QUERY 4 (Confidence Tiers)
-- 4. Run QUERY 5 (Recent Trend)
-- 5. Create weekly report in track-a-monitoring/

-- ALERT CONDITIONS:
-- 🚨 CRITICAL (investigate immediately):
--    - MAE > 5.0 for any day
--    - Win rate < 45% for 3+ consecutive days
--    - Volume drop > 50%
--    - Confidence calibration gap > 20%

-- ⚠️ WARNING (monitor closely):
--    - MAE > 4.2 for 3+ consecutive days
--    - Win rate < 50% for 7+ days
--    - Volume drop > 20%
--    - Confidence calibration gap > 10%

-- ✅ GOOD:
--    - MAE 3.2 to 4.2
--    - Win rate ≥ 52%
--    - Volume within 20% of baseline
--    - Calibration gap ≤ 10%
