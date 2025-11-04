-- Path: schemas/bigquery/predictions/09_ml_prediction_metadata.sql
-- ============================================================================
-- Table: ml_prediction_metadata
-- Purpose: ML-specific prediction details for explainability and debugging
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_prediction_metadata` (
  -- Identifiers (4 fields)
  prediction_id STRING NOT NULL,
  model_id STRING NOT NULL,
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  
  -- Prediction Details (3 fields)
  raw_prediction NUMERIC(5,2),
  prediction_std_dev NUMERIC(5,2),
  prediction_confidence_score NUMERIC(5,2),
  
  -- Feature Values (1 field)
  feature_values JSON NOT NULL,
  
  -- Feature Contributions (2 fields)
  top_positive_features JSON,
  top_negative_features JSON,
  
  -- Model Diagnostics (3 fields)
  out_of_distribution_flag BOOLEAN,
  out_of_distribution_score NUMERIC(5,3),
  feature_warnings JSON,
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  ml_framework_version STRING
)
PARTITION BY game_date
CLUSTER BY model_id, player_lookup, game_date
OPTIONS(
  description="ML-specific prediction metadata for explainability and debugging",
  partition_expiration_days=365
);
