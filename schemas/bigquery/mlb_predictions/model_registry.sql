-- ============================================================================
-- MLB Model Registry Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: model_registry
-- Purpose: Registry of ML models for the MLB pitcher strikeout prediction
--          pipeline. Models can be enabled/disabled without code changes.
--          Modeled after nba_predictions.ml_model_registry.
-- Created: 2026-03-06
-- ============================================================================
--
-- Workflow:
-- 1. Train model locally (mlb/train_*.py)
-- 2. Upload to GCS (gs://nba-props-platform-ml-models/mlb/)
-- 3. Register in this table (INSERT statement)
-- 4. Prediction worker picks up enabled models automatically
-- 5. Compare results in prediction_accuracy table
-- 6. Promote winner by setting is_production = TRUE
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.model_registry` (
  -- Identity
  model_id STRING NOT NULL,                     -- Unique ID: 'xgboost_v2_mae', 'catboost_v1_q45'
  model_name STRING NOT NULL,                   -- Display name: 'XGBoost V2 MAE Strikeouts'
  model_type STRING NOT NULL,                   -- Framework: 'xgboost', 'catboost', 'lightgbm', 'ensemble'
  model_version STRING NOT NULL,                -- Version string: 'v1', 'v2'

  -- Model Location
  model_path STRING NOT NULL,                   -- GCS path: 'gs://nba-props-platform-ml-models/mlb/xgboost_v2.json'
  model_format STRING NOT NULL,                 -- File format: 'json', 'cbm', 'txt', 'pkl'

  -- Feature Requirements
  feature_version STRING NOT NULL,              -- Feature set ID: 'v1_20features', 'v2_28features'
  feature_count INT64 NOT NULL,                 -- Number of features required
  feature_list JSON,                            -- Ordered list of feature names (for validation)

  -- Training Metrics
  training_mae FLOAT64,                         -- MAE on training set
  validation_mae FLOAT64,                       -- MAE on validation set
  test_mae FLOAT64,                             -- MAE on test set
  training_samples INT64,                       -- Number of training samples
  training_period_start DATE,                   -- Training data start date
  training_period_end DATE,                     -- Training data end date

  -- Status Flags
  enabled BOOL NOT NULL,                        -- TRUE to run in prediction pipeline
  is_production BOOL NOT NULL,                  -- TRUE if this is THE production model
  is_baseline BOOL NOT NULL,                    -- TRUE if this is the baseline for comparison

  -- Model Family & Loss Configuration
  model_family STRING,                          -- Family grouping: 'v2_mae', 'v2_q43', 'v1_mae'
  feature_set STRING,                           -- Feature contract: 'v1', 'v2' (maps to get_contract())
  loss_function STRING,                         -- Loss function: 'MAE', 'Quantile:alpha=0.43', 'RMSE'
  quantile_alpha FLOAT64,                       -- NULL for MAE, 0.43 for Q43, 0.45 for Q45

  -- Evaluation Metrics (at key edge thresholds)
  evaluation_hr_edge_1plus FLOAT64,             -- Hit rate for edge >= 1 predictions
  evaluation_n_edge_1plus INT64,                -- Sample size for edge >= 1 evaluation

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  created_by STRING,                            -- Who registered this model
  updated_at TIMESTAMP,
  notes STRING,                                 -- Free-form notes about the model

  -- Training Configuration (for reproducibility)
  hyperparameters JSON,                         -- Model hyperparameters
  training_script STRING                        -- Path to training script
)
OPTIONS(
  description='Registry of MLB pitcher strikeout ML models. Add new models here to run them in the prediction pipeline. '
              'Enable/disable models without code changes. Promote winners by setting is_production = TRUE.'
);

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get all enabled models
-- SELECT model_id, model_name, model_path, test_mae
-- FROM `nba-props-platform.mlb_predictions.model_registry`
-- WHERE enabled = TRUE
-- ORDER BY test_mae ASC;

-- Get the production model
-- SELECT *
-- FROM `nba-props-platform.mlb_predictions.model_registry`
-- WHERE is_production = TRUE;

-- Enable a new model for experimentation
-- UPDATE `nba-props-platform.mlb_predictions.model_registry`
-- SET enabled = TRUE, updated_at = CURRENT_TIMESTAMP()
-- WHERE model_id = 'xgboost_v2_mae';

-- Promote a model to production
-- UPDATE `nba-props-platform.mlb_predictions.model_registry`
-- SET is_production = FALSE, updated_at = CURRENT_TIMESTAMP()
-- WHERE is_production = TRUE;
--
-- UPDATE `nba-props-platform.mlb_predictions.model_registry`
-- SET is_production = TRUE, updated_at = CURRENT_TIMESTAMP()
-- WHERE model_id = 'xgboost_v2_mae';
