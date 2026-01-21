-- Path: schemas/bigquery/predictions/03_system_daily_performance.sql
-- ============================================================================
-- Table: system_daily_performance
-- Purpose: Daily performance summary for each prediction system
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.system_daily_performance` (
  -- Identifiers (3 fields)
  system_id STRING NOT NULL,
  performance_date DATE NOT NULL,
  calculated_at TIMESTAMP NOT NULL,
  
  -- Volume Metrics (4 fields)
  total_predictions INT64 NOT NULL,
  over_recommendations INT64 NOT NULL,
  under_recommendations INT64 NOT NULL,
  pass_recommendations INT64 NOT NULL,
  
  -- Accuracy Metrics (8 fields)
  overall_accuracy NUMERIC(5,3) NOT NULL,
  avg_prediction_error NUMERIC(5,2) NOT NULL,
  rmse NUMERIC(5,2) NOT NULL,
  within_3_points_rate NUMERIC(5,3) NOT NULL,
  within_5_points_rate NUMERIC(5,3) NOT NULL,
  over_accuracy NUMERIC(5,3),
  under_accuracy NUMERIC(5,3),
  avg_confidence NUMERIC(5,2),
  
  -- Confidence Calibration (3 fields)
  high_conf_predictions INT64,
  high_conf_accuracy NUMERIC(5,3),
  confidence_calibration_score NUMERIC(5,3),
  
  -- Performance Trends (3 fields)
  performance_vs_7day_avg NUMERIC(6,3),
  performance_vs_30day_avg NUMERIC(6,3),
  trend_direction STRING,
  
  -- Best/Worst (2 fields)
  best_prediction_id STRING,
  worst_prediction_id STRING,
  
  -- System Info (2 fields)
  system_version STRING,
  system_config_snapshot JSON
)
PARTITION BY performance_date
CLUSTER BY system_id, performance_date DESC
OPTIONS(
  description="Daily performance metrics for each prediction system",
  partition_expiration_days=1095,
  require_partition_filter=TRUE
);
