-- Migration: Add Error Tracking Fields
-- Date: 2026-01-30
-- Purpose: Enable better visibility into prediction errors and data quality issues
-- Session: 37 - V8 Model Investigation
--
-- Background:
-- The January 7-9 model collapse went undetected for weeks because:
-- 1. Feature version mismatches were silent
-- 2. Data quality issues didn't propagate to predictions
-- 3. No error codes tracked why predictions failed
--
-- This migration adds fields to make issues visible immediately.

-- ============================================================================
-- PLAYER_PROP_PREDICTIONS TABLE
-- ============================================================================

-- Feature tracking (propagate from ml_feature_store_v2)
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_version STRING
OPTIONS(description="Feature version used for this prediction (e.g., v2_33features)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_count INT64
OPTIONS(description="Number of features used for this prediction");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_quality_score NUMERIC(5,2)
OPTIONS(description="Quality score of features at prediction time (0-100)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS feature_data_source STRING
OPTIONS(description="Data source: phase4, early_season, mixed");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN
OPTIONS(description="TRUE if prediction made with < 10 games of history");

-- Error tracking
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS prediction_error_code STRING
OPTIONS(description="Error code if prediction failed or used fallback");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS prediction_warnings ARRAY<STRING>
OPTIONS(description="Array of warning flags for this prediction");

-- Confidence calibration tracking
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS raw_confidence_score NUMERIC(4,3)
OPTIONS(description="Pre-calibration confidence score (0-1)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS calibrated_confidence_score NUMERIC(4,3)
OPTIONS(description="Post-calibration confidence score (0-1)");

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS calibration_method STRING
OPTIONS(description="Method used for calibration: none, temperature_scaling, isotonic");


-- ============================================================================
-- PREDICTION_ACCURACY TABLE
-- ============================================================================

-- Feature tracking (for post-hoc analysis of what features were used)
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS feature_version STRING
OPTIONS(description="Feature version used for this prediction");

ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS feature_count INT64
OPTIONS(description="Number of features used");

ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS feature_quality_score NUMERIC(5,2)
OPTIONS(description="Feature quality score at prediction time");

ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS feature_data_source STRING
OPTIONS(description="Data source used");

ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN
OPTIONS(description="TRUE if early season prediction");

-- Calibration tracking (for analyzing calibration effectiveness)
ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS raw_confidence_score NUMERIC(4,3)
OPTIONS(description="Pre-calibration confidence");

ALTER TABLE `nba-props-platform.nba_predictions.prediction_accuracy`
ADD COLUMN IF NOT EXISTS calibration_method STRING
OPTIONS(description="Calibration method used");


-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- After running the migration, verify new columns exist:
/*
SELECT column_name, data_type
FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'player_prop_predictions'
  AND column_name IN ('feature_version', 'feature_count', 'prediction_error_code', 'prediction_warnings')
ORDER BY column_name;
*/

-- Example query to analyze errors by code:
/*
SELECT
  game_date,
  prediction_error_code,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND prediction_error_code IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
*/

-- Example query to check feature version distribution:
/*
SELECT
  game_date,
  feature_version,
  COUNT(*) as predictions,
  AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
*/
