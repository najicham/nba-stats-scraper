-- Path: schemas/bigquery/predictions/10_weight_adjustment_log.sql
-- ============================================================================
-- Table: weight_adjustment_log
-- Purpose: History of system configuration changes for auditing and rollback
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.weight_adjustment_log` (
  -- Identifiers (4 fields)
  adjustment_id STRING NOT NULL,
  system_id STRING NOT NULL,
  adjustment_date DATE NOT NULL,
  adjustment_type STRING NOT NULL,
  
  -- Changes (3 fields)
  previous_config JSON NOT NULL,
  new_config JSON NOT NULL,
  changes_summary STRING NOT NULL,
  
  -- Rationale (3 fields)
  reason STRING NOT NULL,
  triggered_by STRING NOT NULL,
  approved_by STRING,
  
  -- Performance Impact (4 fields)
  performance_before_7d NUMERIC(5,3),
  performance_after_7d NUMERIC(5,3),
  performance_delta NUMERIC(6,3),
  rollback_flag BOOLEAN DEFAULT FALSE,
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  notes STRING
)
PARTITION BY adjustment_date
CLUSTER BY system_id, adjustment_date DESC
OPTIONS(
  description="History of system configuration changes",
  partition_expiration_days=1095,
  require_partition_filter=TRUE
);
