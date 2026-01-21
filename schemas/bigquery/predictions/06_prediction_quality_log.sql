-- Path: schemas/bigquery/predictions/06_prediction_quality_log.sql
-- ============================================================================
-- Table: prediction_quality_log
-- Purpose: Track data quality issues that might affect predictions
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_quality_log` (
  log_id STRING NOT NULL,
  prediction_id STRING NOT NULL,
  system_id STRING NOT NULL,
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  
  -- Quality Flags (4 fields)
  has_insufficient_data BOOLEAN DEFAULT FALSE,
  has_missing_features BOOLEAN DEFAULT FALSE,
  has_stale_data BOOLEAN DEFAULT FALSE,
  has_outlier_prediction BOOLEAN DEFAULT FALSE,
  
  -- Quality Details (3 fields)
  missing_features ARRAY<STRING>,
  data_age_hours INT64,
  prediction_z_score NUMERIC(5,2),
  
  -- Action Taken (2 fields)
  fallback_used BOOLEAN DEFAULT FALSE,
  fallback_system STRING,
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup, game_date
OPTIONS(
  description="Log of data quality issues encountered during predictions",
  partition_expiration_days=90,
  require_partition_filter=TRUE
);
