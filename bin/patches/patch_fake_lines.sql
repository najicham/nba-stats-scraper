-- ============================================================================
-- PATCH: Fix Fake Line=20 in Historical Predictions
-- ============================================================================
-- Created: 2026-01-10
-- Purpose: Replace fake line=20 with real Vegas lines from BettingPros
--
-- Scope:
--   - ~367K predictions across 5 systems have fake line=20
--   - ~55% can be matched to real Vegas lines
--   - ~45% will be set to NULL/NO_LINE (no Vegas data available)
--
-- Systems to patch:
--   - moving_average_baseline_v1 (edge=2.0, conf=0.45)
--   - zone_matchup_v1 (edge=2.0, conf=0.45)
--   - similarity_balanced_v1 (edge=2.0, conf=0.65)
--   - xgboost_v1 (edge=1.5, conf=0.60)
--   - ensemble_v1 (edge=1.5, conf=0.65)
--
-- Run order:
--   1. Create vegas_lines temp table
--   2. Patch each system (5 queries)
--   3. Handle unmatched predictions (set to NULL/NO_LINE)
--   4. Patch prediction_accuracy table
--   5. Regenerate system_daily_performance
-- ============================================================================

-- ============================================================================
-- STEP 0: Verify before patching
-- ============================================================================
-- Run this first to see current state:
/*
SELECT
  system_id,
  COUNTIF(current_points_line = 20) as fake_lines,
  COUNTIF(current_points_line IS NULL) as null_lines,
  COUNTIF(current_points_line NOT IN (20) AND current_points_line IS NOT NULL) as real_lines
FROM nba_predictions.player_prop_predictions
GROUP BY system_id
ORDER BY system_id;
*/

-- ============================================================================
-- STEP 1: Create Vegas Lines Reference Table
-- ============================================================================
-- This creates a clean lookup table with one consensus line per player/date

CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions._patch_vegas_lines` AS
SELECT
  player_lookup,
  game_date,
  -- Use median of all points lines as consensus
  APPROX_QUANTILES(points_line, 2)[OFFSET(1)] as consensus_line,
  COUNT(*) as source_rows
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE market_type = 'points'
  AND game_date >= '2021-01-01'
  AND points_line IS NOT NULL
GROUP BY player_lookup, game_date;

-- Verify: SELECT COUNT(*) FROM `nba_predictions._patch_vegas_lines`;
-- Expected: ~100K+ rows

-- ============================================================================
-- STEP 2A: Patch moving_average_baseline_v1
-- ============================================================================
-- Thresholds: edge_threshold=2.0, confidence_threshold=0.45

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    -- Confidence threshold: 0.45
    WHEN p.confidence_score < 0.45 THEN 'PASS'
    -- Edge threshold: 2.0 points
    WHEN ABS(p.predicted_points - v.consensus_line) < 2.0 THEN 'PASS'
    -- Direction based on prediction vs line
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'moving_average_baseline_v1'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- ============================================================================
-- STEP 2B: Patch zone_matchup_v1
-- ============================================================================
-- Thresholds: edge_threshold=2.0, confidence_threshold=0.45

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    WHEN p.confidence_score < 0.45 THEN 'PASS'
    WHEN ABS(p.predicted_points - v.consensus_line) < 2.0 THEN 'PASS'
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'zone_matchup_v1'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- ============================================================================
-- STEP 2C: Patch similarity_balanced_v1
-- ============================================================================
-- Thresholds: edge_threshold=2.0, confidence_threshold=0.65 (higher!)

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    -- Higher confidence threshold: 0.65
    WHEN p.confidence_score < 0.65 THEN 'PASS'
    WHEN ABS(p.predicted_points - v.consensus_line) < 2.0 THEN 'PASS'
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'similarity_balanced_v1'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- ============================================================================
-- STEP 2D: Patch xgboost_v1
-- ============================================================================
-- Thresholds: edge_threshold=1.5, confidence_threshold=0.60 (like catboost)

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    WHEN p.confidence_score < 0.60 THEN 'PASS'
    -- Lower edge threshold: 1.5
    WHEN ABS(p.predicted_points - v.consensus_line) < 1.5 THEN 'PASS'
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'xgboost_v1'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- ============================================================================
-- STEP 2E: Patch ensemble_v1
-- ============================================================================
-- Thresholds: edge_threshold=1.5, confidence_threshold=0.65
-- NOTE: Ignoring majority vote bug - just using predicted_points vs line

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    WHEN p.confidence_score < 0.65 THEN 'PASS'
    WHEN ABS(p.predicted_points - v.consensus_line) < 1.5 THEN 'PASS'
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'ensemble_v1'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- ============================================================================
-- STEP 3: Handle Unmatched Predictions (no Vegas line available)
-- ============================================================================
-- These predictions had line=20 but no matching Vegas line was found
-- Set them to NULL and mark as NO_LINE

UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET
  current_points_line = NULL,
  line_margin = NULL,
  has_prop_line = FALSE,
  line_source = 'NO_VEGAS_DATA',
  recommendation = 'NO_LINE'
WHERE current_points_line = 20
  AND system_id IN (
    'moving_average_baseline_v1',
    'zone_matchup_v1',
    'similarity_balanced_v1',
    'xgboost_v1',
    'ensemble_v1'
  );

-- Also patch the few catboost_v8 fake lines (83 rows)
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = v.consensus_line,
  line_margin = ROUND(p.predicted_points - v.consensus_line, 2),
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  recommendation = CASE
    WHEN p.confidence_score < 0.60 THEN 'PASS'
    WHEN ABS(p.predicted_points - v.consensus_line) < 1.0 THEN 'PASS'
    WHEN p.predicted_points > v.consensus_line THEN 'OVER'
    ELSE 'UNDER'
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE p.system_id = 'catboost_v8'
  AND p.current_points_line = 20
  AND p.player_lookup = v.player_lookup
  AND p.game_date = v.game_date;

-- Handle remaining catboost_v8 fake lines
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET
  current_points_line = NULL,
  line_margin = NULL,
  has_prop_line = FALSE,
  line_source = 'NO_VEGAS_DATA',
  recommendation = 'NO_LINE'
WHERE current_points_line = 20
  AND system_id = 'catboost_v8';

-- ============================================================================
-- STEP 4: Patch prediction_accuracy Table
-- ============================================================================
-- This table also needs line_value updated and prediction_correct recalculated

UPDATE `nba-props-platform.nba_predictions.prediction_accuracy` pa
SET
  line_value = v.consensus_line,
  has_prop_line = TRUE,
  line_source = 'VEGAS_BACKFILL',
  prediction_correct = CASE
    WHEN pa.recommendation = 'OVER' AND pa.actual_points > v.consensus_line THEN TRUE
    WHEN pa.recommendation = 'UNDER' AND pa.actual_points < v.consensus_line THEN TRUE
    WHEN pa.recommendation IN ('PASS', 'NO_LINE') THEN NULL
    ELSE FALSE
  END
FROM `nba-props-platform.nba_predictions._patch_vegas_lines` v
WHERE pa.line_value = 20
  AND pa.player_lookup = v.player_lookup
  AND pa.game_date = v.game_date;

-- Handle unmatched prediction_accuracy rows
UPDATE `nba-props-platform.nba_predictions.prediction_accuracy`
SET
  line_value = NULL,
  has_prop_line = FALSE,
  line_source = 'NO_VEGAS_DATA',
  prediction_correct = NULL
WHERE line_value = 20;

-- ============================================================================
-- STEP 5: Regenerate system_daily_performance
-- ============================================================================
-- Delete and regenerate aggregates for affected date range

DELETE FROM `nba-props-platform.nba_predictions.system_daily_performance`
WHERE game_date >= '2021-11-01';

INSERT INTO `nba-props-platform.nba_predictions.system_daily_performance`
SELECT
  game_date,
  system_id,
  -- Volume
  COUNT(*) as predictions_count,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations_count,
  COUNTIF(prediction_correct = TRUE) as correct_count,
  COUNTIF(prediction_correct = FALSE) as incorrect_count,
  COUNTIF(recommendation = 'PASS') as pass_count,
  -- Core Accuracy
  ROUND(SAFE_DIVIDE(
    COUNTIF(prediction_correct = TRUE),
    COUNTIF(recommendation IN ('OVER', 'UNDER'))
  ), 3) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as avg_bias,
  -- OVER/UNDER Breakdown
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE) as over_correct,
  ROUND(SAFE_DIVIDE(
    COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE),
    COUNTIF(recommendation = 'OVER')
  ), 3) as over_win_rate,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE) as under_correct,
  ROUND(SAFE_DIVIDE(
    COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE),
    COUNTIF(recommendation = 'UNDER')
  ), 3) as under_win_rate,
  -- Threshold Accuracy
  COUNTIF(within_3_points = TRUE) as within_3_count,
  ROUND(SAFE_DIVIDE(COUNTIF(within_3_points = TRUE), COUNT(*)), 3) as within_3_pct,
  COUNTIF(within_5_points = TRUE) as within_5_count,
  ROUND(SAFE_DIVIDE(COUNTIF(within_5_points = TRUE), COUNT(*)), 3) as within_5_pct,
  -- Confidence Analysis
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  COUNTIF(confidence_score >= 0.70) as high_confidence_count,
  COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE) as high_confidence_correct,
  ROUND(SAFE_DIVIDE(
    COUNTIF(confidence_score >= 0.70 AND prediction_correct = TRUE),
    COUNTIF(confidence_score >= 0.70 AND recommendation IN ('OVER', 'UNDER'))
  ), 3) as high_confidence_win_rate,
  -- Metadata
  CURRENT_TIMESTAMP() as computed_at
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2021-11-01'
GROUP BY game_date, system_id;

-- ============================================================================
-- STEP 6: Cleanup
-- ============================================================================
DROP TABLE IF EXISTS `nba-props-platform.nba_predictions._patch_vegas_lines`;

-- ============================================================================
-- STEP 7: Validate Results
-- ============================================================================
/*
-- Run after patching to verify:

-- Check no more fake lines (except legitimate ones)
SELECT
  system_id,
  COUNTIF(current_points_line = 20) as fake_lines,
  COUNTIF(current_points_line IS NULL) as null_lines,
  COUNTIF(current_points_line NOT IN (20) AND current_points_line IS NOT NULL) as real_lines,
  COUNTIF(has_prop_line = FALSE) as no_prop_line
FROM nba_predictions.player_prop_predictions
GROUP BY system_id
ORDER BY system_id;

-- Check recommendation distribution
SELECT
  system_id,
  recommendation,
  COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2023-01-01'
GROUP BY system_id, recommendation
ORDER BY system_id, recommendation;

-- Compare system performance (should now be meaningful)
SELECT
  system_id,
  SUM(recommendations_count) as picks,
  ROUND(SUM(correct_count) / SUM(recommendations_count) * 100, 1) as win_rate_pct
FROM nba_predictions.system_daily_performance
WHERE game_date >= '2023-01-01'
GROUP BY system_id
ORDER BY win_rate_pct DESC;
*/
