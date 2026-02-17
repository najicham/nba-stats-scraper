-- ============================================================================
-- Table: ml_model_registry
-- File: 11_ml_model_registry.sql
-- Purpose: Registry of ML models for experimentation pipeline
-- ============================================================================
--
-- This table tracks all ML models that can be run in the experimentation
-- pipeline. Models can be enabled/disabled without code changes.
--
-- Workflow:
-- 1. Train model locally (ml/train_*.py)
-- 2. Upload to GCS (gs://nba-props-platform-ml-models/)
-- 3. Register in this table (INSERT statement)
-- 4. ML runner picks up enabled models automatically
-- 5. Compare results in ml_model_predictions table
-- 6. Promote winner by setting is_production = TRUE
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_model_registry` (
  -- Identity
  model_id STRING NOT NULL,                    -- Unique ID: 'catboost_v8', 'xgboost_v9'
  model_name STRING NOT NULL,                  -- Display name: 'CatBoost V8 Stacked Ensemble'
  model_type STRING NOT NULL,                  -- Framework: 'catboost', 'xgboost', 'lightgbm', 'ensemble'
  model_version STRING NOT NULL,               -- Version string: 'v8', 'v9'

  -- Model Location
  model_path STRING NOT NULL,                  -- GCS path: 'gs://nba-props-platform-ml-models/catboost_v8.cbm'
  model_format STRING NOT NULL,                -- File format: 'cbm', 'json', 'txt', 'pkl'

  -- Feature Requirements
  feature_version STRING NOT NULL,             -- Feature set ID: 'v8_33features', 'v9_36features'
  feature_count INT64 NOT NULL,                -- Number of features required: 33, 36
  feature_list JSON,                           -- Ordered list of feature names (for validation)

  -- Training Metrics
  training_mae FLOAT64,                        -- MAE on training set
  validation_mae FLOAT64,                      -- MAE on validation set
  test_mae FLOAT64,                            -- MAE on test set
  training_samples INT64,                      -- Number of training samples
  training_period_start DATE,                  -- Training data start date
  training_period_end DATE,                    -- Training data end date

  -- Status Flags
  enabled BOOL NOT NULL,                       -- TRUE to run in experiments
  is_production BOOL NOT NULL,                 -- TRUE if this is THE production model
  is_baseline BOOL NOT NULL,                   -- TRUE if this is the baseline for comparison

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  created_by STRING,                           -- Who registered this model
  updated_at TIMESTAMP,
  notes STRING,                                -- Free-form notes about the model

  -- Training Configuration (optional, for reproducibility)
  hyperparameters JSON,                        -- Model hyperparameters
  training_script STRING,                      -- Path to training script

  -- Model Family & Feature Metadata (Session 273: Model Management Overhaul)
  model_family STRING,                         -- Family grouping: 'v9_mae', 'v9_q43', 'v12_noveg_mae'
  feature_set STRING,                          -- Feature contract: 'v9', 'v12_noveg' (maps to get_contract())
  loss_function STRING,                        -- CatBoost loss: 'MAE', 'Quantile:alpha=0.43'
  quantile_alpha FLOAT64,                      -- NULL for MAE, 0.43 for Q43, etc.
  strengths_json STRING,                       -- JSON: direction, tiers, line_range, edge_bucket
  evaluation_hr_edge_3plus FLOAT64,            -- Hit rate for edge >= 3 predictions
  evaluation_n_edge_3plus INT64                -- Sample size for edge >= 3 evaluation
)
OPTIONS(
  description="Registry of ML models for experimentation. Add new models here to run them in the ML experiment pipeline."
);

-- ============================================================================
-- Initial Data: Register v8 model
-- ============================================================================

-- Run this after creating the table:
-- INSERT INTO `nba-props-platform.nba_predictions.ml_model_registry` VALUES (
--   'catboost_v8',
--   'CatBoost V8 Stacked Ensemble',
--   'catboost',
--   'v8',
--   'gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm',
--   'cbm',
--   'v8_33features',
--   33,
--   JSON '[
--     "points_avg_last_5", "points_avg_last_10", "points_avg_season",
--     "points_std_last_10", "games_in_last_7_days", "fatigue_score",
--     "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
--     "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
--     "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
--     "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
--     "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
--     "vegas_points_line", "vegas_opening_line", "vegas_line_move",
--     "has_vegas_line", "avg_points_vs_opponent", "games_vs_opponent",
--     "minutes_avg_last_10", "ppm_avg_last_10"
--   ]',
--   3.19,   -- training MAE
--   NULL,   -- validation MAE
--   3.40,   -- test MAE
--   76863,  -- training samples
--   '2021-11-01',
--   '2024-06-01',
--   TRUE,   -- enabled
--   FALSE,  -- is_production (mock is still production)
--   FALSE,  -- is_baseline
--   CURRENT_TIMESTAMP(),
--   'ml_training_session',
--   NULL,
--   'V8 model with minutes/PPM history. 29% better than mock baseline.',
--   JSON '{"depth": 6, "learning_rate": 0.07, "l2_leaf_reg": 3.8}',
--   'ml/train_final_ensemble_v8.py'
-- );

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get all enabled models
-- SELECT model_id, model_name, model_path, test_mae
-- FROM `nba-props-platform.nba_predictions.ml_model_registry`
-- WHERE enabled = TRUE
-- ORDER BY test_mae ASC;

-- Get the production model
-- SELECT *
-- FROM `nba-props-platform.nba_predictions.ml_model_registry`
-- WHERE is_production = TRUE;

-- Enable a new model for experimentation
-- UPDATE `nba-props-platform.nba_predictions.ml_model_registry`
-- SET enabled = TRUE, updated_at = CURRENT_TIMESTAMP()
-- WHERE model_id = 'catboost_v9';

-- Promote a model to production
-- UPDATE `nba-props-platform.nba_predictions.ml_model_registry`
-- SET is_production = FALSE, updated_at = CURRENT_TIMESTAMP()
-- WHERE is_production = TRUE;
--
-- UPDATE `nba-props-platform.nba_predictions.ml_model_registry`
-- SET is_production = TRUE, updated_at = CURRENT_TIMESTAMP()
-- WHERE model_id = 'catboost_v9';
