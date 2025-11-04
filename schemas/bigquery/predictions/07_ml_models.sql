-- Path: schemas/bigquery/predictions/07_ml_models.sql
-- ============================================================================
-- Table: ml_models
-- Purpose: Registry of trained ML models (XGBoost, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_models` (
  -- Identifiers (5 fields)
  model_id STRING NOT NULL,
  model_name STRING NOT NULL,
  model_type STRING NOT NULL,
  version STRING NOT NULL,
  model_scope STRING NOT NULL,
  
  -- Scope Details (2 fields)
  player_lookup STRING,
  position STRING,
  
  -- Model Storage (2 fields)
  model_file_path STRING NOT NULL,
  model_size_bytes INT64,
  
  -- Training Performance (6 fields)
  training_mae NUMERIC(5,2),
  validation_mae NUMERIC(5,2),
  test_mae NUMERIC(5,2),
  training_samples INT64,
  validation_samples INT64,
  test_samples INT64,
  
  -- Features (2 fields)
  features_used JSON NOT NULL,
  feature_importance JSON,
  
  -- Hyperparameters (1 field)
  hyperparameters JSON NOT NULL,
  
  -- Status (3 fields)
  active BOOLEAN NOT NULL DEFAULT TRUE,
  production_ready BOOLEAN NOT NULL DEFAULT FALSE,
  trained_on_date DATE NOT NULL,
  
  -- Performance Tracking (3 fields)
  last_retrained DATE,
  production_predictions INT64 DEFAULT 0,
  production_accuracy NUMERIC(5,3),
  
  -- Retraining Triggers (2 fields)
  needs_retraining BOOLEAN DEFAULT FALSE,
  retraining_reason STRING,
  
  -- Metadata (3 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP,
  notes STRING
)
OPTIONS(
  description="Registry of trained ML models with performance metrics"
);
