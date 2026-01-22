-- Phase Boundary Validations Table
-- Stores validation results from phase transitions
-- Used for monitoring data quality and catching issues early

CREATE TABLE IF NOT EXISTS `nba_monitoring.phase_boundary_validations` (
  -- Validation metadata
  validation_timestamp TIMESTAMP NOT NULL,
  game_date DATE NOT NULL,
  phase_name STRING NOT NULL,  -- phase1, phase2, phase3, etc.
  validation_type STRING NOT NULL,  -- game_count, processor_completion, data_quality

  -- Validation result
  is_valid BOOL NOT NULL,
  severity STRING NOT NULL,  -- info, warning, error
  message STRING,

  -- Metrics
  expected_value FLOAT64,
  actual_value FLOAT64,
  threshold FLOAT64,

  -- Additional details (JSON)
  details STRING,

  -- Partitioning for performance
  -- Partitioned by validation_timestamp for efficient querying
  _PARTITIONING_COLUMN TIMESTAMP AS validation_timestamp
)
PARTITION BY DATE(validation_timestamp)
CLUSTER BY phase_name, validation_type, is_valid
OPTIONS (
  description = "Phase boundary validation results for monitoring data quality",
  partition_expiration_days = 90,  -- Keep 90 days of validation history
  require_partition_filter = false
);

-- Indexes for common queries
-- BigQuery automatically creates indexes on clustered columns

-- Example queries:
--
-- Get recent validation failures:
-- SELECT * FROM nba_monitoring.phase_boundary_validations
-- WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- AND is_valid = FALSE
-- ORDER BY validation_timestamp DESC;
--
-- Get validation summary by phase:
-- SELECT
--   phase_name,
--   validation_type,
--   COUNT(*) as total_validations,
--   SUM(CASE WHEN is_valid THEN 1 ELSE 0 END) as valid_count,
--   SUM(CASE WHEN is_valid THEN 0 ELSE 1 END) as invalid_count,
--   ROUND(AVG(CASE WHEN is_valid THEN 1 ELSE 0 END) * 100, 2) as success_rate_pct
-- FROM nba_monitoring.phase_boundary_validations
-- WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
-- GROUP BY phase_name, validation_type
-- ORDER BY phase_name, validation_type;
--
-- Get game count validation trends:
-- SELECT
--   DATE(validation_timestamp) as validation_date,
--   phase_name,
--   AVG(actual_value) as avg_actual_games,
--   AVG(expected_value) as avg_expected_games,
--   AVG(actual_value / NULLIF(expected_value, 0)) as avg_ratio
-- FROM nba_monitoring.phase_boundary_validations
-- WHERE validation_type = 'game_count'
-- AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
-- GROUP BY validation_date, phase_name
-- ORDER BY validation_date DESC, phase_name;
