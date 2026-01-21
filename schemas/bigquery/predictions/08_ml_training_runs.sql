-- Path: schemas/bigquery/predictions/08_ml_training_runs.sql
-- ============================================================================
-- Table: ml_training_runs
-- Purpose: History of model training runs with metrics and deployment decisions
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_training_runs` (
  -- Identifiers (4 fields)
  run_id STRING NOT NULL,
  model_id STRING NOT NULL,
  run_date DATE NOT NULL,
  run_type STRING NOT NULL,
  
  -- Training Details (4 fields)
  training_start_date DATE NOT NULL,
  training_end_date DATE NOT NULL,
  training_duration_seconds INT64,
  training_completed_at TIMESTAMP,
  
  -- Data Splits (4 fields)
  total_samples INT64 NOT NULL,
  training_samples INT64 NOT NULL,
  validation_samples INT64 NOT NULL,
  test_samples INT64 NOT NULL,
  
  -- Performance Metrics (6 fields)
  train_mae NUMERIC(5,2) NOT NULL,
  validation_mae NUMERIC(5,2) NOT NULL,
  test_mae NUMERIC(5,2) NOT NULL,
  train_rmse NUMERIC(5,2),
  validation_rmse NUMERIC(5,2),
  test_rmse NUMERIC(5,2),
  
  -- Over/Under Accuracy (3 fields)
  validation_ou_accuracy NUMERIC(5,3),
  validation_within_3_pts NUMERIC(5,3),
  validation_within_5_pts NUMERIC(5,3),
  
  -- Hyperparameters (2 fields)
  hyperparameters_tested JSON,
  best_hyperparameters JSON NOT NULL,
  
  -- Feature Importance (1 field)
  feature_importance JSON NOT NULL,
  
  -- Comparison to Previous (2 fields)
  previous_model_version STRING,
  improvement_over_previous NUMERIC(6,3),
  
  -- Status (2 fields)
  training_status STRING NOT NULL,
  error_message STRING,
  
  -- Deployment Decision (3 fields)
  deployed_to_production BOOLEAN DEFAULT FALSE,
  deployment_reason STRING,
  deployed_at TIMESTAMP,
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  notes STRING
)
PARTITION BY run_date
CLUSTER BY model_id, run_date DESC
OPTIONS(
  description="History of ML model training runs",
  partition_expiration_days=1095,
  require_partition_filter=TRUE
);
