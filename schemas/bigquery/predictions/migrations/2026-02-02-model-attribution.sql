-- ============================================================================
-- Migration: Model Attribution Tracking
-- Date: February 2, 2026
-- Session: 84
-- Purpose: Add model file tracking and training metadata to predictions
-- ============================================================================
--
-- Problem: Cannot determine which exact model file generated which predictions
-- - prediction_execution_log is empty (0 records)
-- - No model file name tracking
-- - No training period metadata
-- - Historical analysis impossible
--
-- Solution: Add comprehensive model attribution fields
-- ============================================================================

-- ============================================================================
-- Part 1: player_prop_predictions - Add model attribution fields
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`

-- Exact model file that generated this prediction
ADD COLUMN IF NOT EXISTS model_file_name STRING
  OPTIONS (description='Exact model file name (e.g., catboost_v9_feb_02_retrain.cbm). Session 84.'),

-- Model training period
ADD COLUMN IF NOT EXISTS model_training_start_date DATE
  OPTIONS (description='Start date of training data window. Session 84.'),

ADD COLUMN IF NOT EXISTS model_training_end_date DATE
  OPTIONS (description='End date of training data window. Session 84.'),

-- Expected performance metrics (from training/validation)
ADD COLUMN IF NOT EXISTS model_expected_mae FLOAT64
  OPTIONS (description='Expected MAE from model training/validation. Session 84.'),

ADD COLUMN IF NOT EXISTS model_expected_hit_rate FLOAT64
  OPTIONS (description='Expected hit rate for high-edge picks (5+ edge) from validation. Session 84.'),

-- Model training timestamp
ADD COLUMN IF NOT EXISTS model_trained_at TIMESTAMP
  OPTIONS (description='When this model was trained. Session 84.');

-- ============================================================================
-- Part 2: prediction_execution_log - Add model tracking fields
-- ============================================================================

ALTER TABLE `nba-props-platform.nba_predictions.prediction_execution_log`

-- Model identification
ADD COLUMN IF NOT EXISTS model_file_name STRING
  OPTIONS (description='Exact model file name used for this execution. Session 84.'),

ADD COLUMN IF NOT EXISTS model_path STRING
  OPTIONS (description='Full GCS path to model file. Session 84.'),

-- Model metadata
ADD COLUMN IF NOT EXISTS model_training_start_date DATE
  OPTIONS (description='Start date of model training window. Session 84.'),

ADD COLUMN IF NOT EXISTS model_training_end_date DATE
  OPTIONS (description='End date of model training window. Session 84.'),

ADD COLUMN IF NOT EXISTS model_expected_mae FLOAT64
  OPTIONS (description='Expected MAE from model training. Session 84.');

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Check if new columns exist
-- SELECT column_name, data_type, description
-- FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
-- WHERE table_name = 'player_prop_predictions'
--   AND column_name LIKE 'model_%'
-- ORDER BY column_name;

-- Check model attribution coverage for recent predictions
-- SELECT
--   game_date,
--   system_id,
--   COUNT(*) as predictions,
--   COUNTIF(model_file_name IS NOT NULL) as with_attribution,
--   ROUND(100.0 * COUNTIF(model_file_name IS NOT NULL) / COUNT(*), 1) as coverage_pct
-- FROM `nba-props-platform.nba_predictions.player_prop_predictions`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
-- GROUP BY game_date, system_id
-- ORDER BY game_date DESC, system_id;

-- ============================================================================
-- Expected Results After Code Deployment
-- ============================================================================
--
-- After prediction-worker is deployed with model attribution code:
--
-- 1. New predictions will have model_file_name populated
-- 2. Model training dates will be present
-- 3. Expected performance metrics will be stored
-- 4. prediction_execution_log will have records
--
-- Verification command (run after overnight predictions):
--   ./bin/verify-model-attribution.sh
--
-- ============================================================================
