-- File: schemas/bigquery/validation/validation_results.sql
-- Description: BigQuery schema for validation system - stores validation results, history, and summaries
-- Dataset: validation
-- Tables:
--   - validation_results: Individual validation check results
--   - validation_runs: Metadata about validation runs
-- Views:
--   - validation_failures_recent: Recent failures for alerting
--   - processor_health_summary: Overall processor health metrics
--   - validation_trends: Historical data quality trends

-- ============================================================================
-- Dataset Creation (if not exists)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `validation`
OPTIONS (
  description = "Data validation results, runs, and monitoring",
  location = "us"
);

-- ============================================================================
-- Main Validation Results Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `validation.validation_results` (
  -- Run identification
  validation_run_id STRING NOT NULL,           -- UUID for this validation run
  validation_timestamp TIMESTAMP NOT NULL,     -- When validation ran
  
  -- Processor identification
  processor_name STRING NOT NULL,              -- "espn_scoreboard", "bdl_boxscores", etc.
  processor_type STRING NOT NULL,              -- "raw", "analytics", "reports", "reference"
  
  -- Date range validated
  date_range_start DATE,                       -- Start of validated range
  date_range_end DATE,                         -- End of validated range
  season_year INT64,                           -- Season if applicable
  
  -- Check details
  check_name STRING NOT NULL,                  -- "completeness_game_date", "team_presence", etc.
  check_type STRING NOT NULL,                  -- "completeness", "field_validation", "team_presence", etc.
  validation_layer STRING NOT NULL,            -- "gcs", "bigquery", "schedule"
  
  -- Result
  passed BOOLEAN NOT NULL,                     -- TRUE = check passed, FALSE = failed
  severity STRING NOT NULL,                    -- "info", "warning", "error", "critical"
  message STRING,                              -- Human-readable result message
  
  -- Impact
  affected_count INT64,                        -- Number of records/dates/items affected
  affected_items STRING,                       -- JSON array of affected items (first 20)
  
  -- Technical details
  query_used STRING,                           -- SQL query that was run (if applicable)
  execution_duration_seconds FLOAT64,          -- How long the check took
  
  -- Remediation
  remediation_commands STRING,                 -- JSON array of fix commands
  remediation_generated BOOLEAN DEFAULT FALSE, -- Whether remediation was auto-generated
  
  -- Overall status context
  overall_status STRING NOT NULL,              -- "pass", "warn", "fail" for this run
  
  -- Metadata
  validator_version STRING,                    -- Version of validation framework
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(validation_timestamp)
CLUSTER BY processor_name, check_type, passed, severity
OPTIONS (
  description = "Individual validation check results - one row per check per run",
  partition_expiration_days = 730,  -- Keep 2 years of validation history
  require_partition_filter = false  -- Allow queries without date filter for recent checks
);

-- ============================================================================
-- Validation Runs Table (Run-level metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `validation.validation_runs` (
  -- Run identification
  validation_run_id STRING NOT NULL,           -- UUID for this run (matches validation_results)
  validation_timestamp TIMESTAMP NOT NULL,     -- When run started
  
  -- Processor details
  processor_name STRING NOT NULL,
  processor_type STRING NOT NULL,
  
  -- Configuration
  date_range_start DATE,
  date_range_end DATE,
  season_year INT64,
  layers_validated STRING,                     -- JSON array: ["gcs", "bigquery", "schedule"]
  
  -- Results summary
  total_checks INT64 NOT NULL,
  passed_checks INT64 NOT NULL,
  failed_checks INT64 NOT NULL,
  overall_status STRING NOT NULL,              -- "pass", "warn", "fail"
  
  -- Execution details
  execution_duration_seconds FLOAT64,
  triggered_by STRING,                         -- "manual", "scheduler", "api"
  
  -- Notification
  notification_sent BOOLEAN DEFAULT FALSE,
  notification_channels STRING,                -- JSON array: ["slack", "email"]
  
  -- Remediation
  remediation_available BOOLEAN DEFAULT FALSE,
  remediation_commands_count INT64,
  
  -- Metadata
  validator_version STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(validation_timestamp)
CLUSTER BY processor_name, overall_status
OPTIONS (
  description = "Validation run metadata - one row per validation execution",
  partition_expiration_days = 730
);

-- ============================================================================
-- View: Recent Failures (Last 7 Days)
-- ============================================================================

CREATE OR REPLACE VIEW `validation.validation_failures_recent` AS
SELECT 
  validation_timestamp,
  processor_name,
  processor_type,
  check_name,
  check_type,
  severity,
  message,
  affected_count,
  affected_items,
  remediation_commands,
  overall_status
FROM `validation.validation_results`
WHERE passed = FALSE
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY 
  CASE severity
    WHEN 'critical' THEN 1
    WHEN 'error' THEN 2
    WHEN 'warning' THEN 3
    ELSE 4
  END,
  validation_timestamp DESC;

-- ============================================================================
-- View: Processor Health Summary (Last 30 Days)
-- ============================================================================

CREATE OR REPLACE VIEW `validation.processor_health_summary` AS
WITH daily_stats AS (
  SELECT 
    processor_name,
    processor_type,
    DATE(validation_timestamp) as validation_date,
    COUNT(*) as total_checks,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_checks,
    SUM(CASE WHEN NOT passed THEN 1 ELSE 0 END) as failed_checks,
    SUM(CASE WHEN NOT passed AND severity = 'critical' THEN 1 ELSE 0 END) as critical_failures,
    SUM(CASE WHEN NOT passed AND severity = 'error' THEN 1 ELSE 0 END) as error_failures,
    SUM(CASE WHEN NOT passed AND severity = 'warning' THEN 1 ELSE 0 END) as warning_failures,
    MAX(validation_timestamp) as last_validation
  FROM `validation.validation_results`
  WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY processor_name, processor_type, DATE(validation_timestamp)
)
SELECT 
  processor_name,
  processor_type,
  validation_date,
  total_checks,
  passed_checks,
  failed_checks,
  critical_failures,
  error_failures,
  warning_failures,
  ROUND(passed_checks / total_checks * 100, 2) as pass_rate,
  last_validation
FROM daily_stats
ORDER BY validation_date DESC, processor_name;

-- ============================================================================
-- View: Data Quality Trends (Last 90 Days)
-- ============================================================================

CREATE OR REPLACE VIEW `validation.validation_trends` AS
WITH weekly_stats AS (
  SELECT 
    processor_name,
    processor_type,
    DATE_TRUNC(DATE(validation_timestamp), WEEK) as week_start,
    COUNT(*) as total_checks,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_checks,
    SUM(CASE WHEN NOT passed THEN 1 ELSE 0 END) as failed_checks,
    ROUND(SUM(CASE WHEN passed THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as pass_rate,
    COUNT(DISTINCT validation_run_id) as validation_runs
  FROM `validation.validation_results`
  WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
  GROUP BY processor_name, processor_type, DATE_TRUNC(DATE(validation_timestamp), WEEK)
)
SELECT 
  processor_name,
  processor_type,
  week_start,
  total_checks,
  passed_checks,
  failed_checks,
  pass_rate,
  validation_runs,
  -- Trend indicator (compare to previous week)
  pass_rate - LAG(pass_rate) OVER (
    PARTITION BY processor_name 
    ORDER BY week_start
  ) as pass_rate_change
FROM weekly_stats
ORDER BY week_start DESC, processor_name;

-- ============================================================================
-- View: Current Processor Status (Latest Run Per Processor)
-- ============================================================================

CREATE OR REPLACE VIEW `validation.processor_status_current` AS
WITH latest_runs AS (
  SELECT 
    processor_name,
    processor_type,
    MAX(validation_timestamp) as latest_validation
  FROM `validation.validation_runs`
  GROUP BY processor_name, processor_type
)
SELECT 
  r.processor_name,
  r.processor_type,
  r.validation_timestamp,
  r.overall_status,
  r.total_checks,
  r.passed_checks,
  r.failed_checks,
  ROUND(r.passed_checks / r.total_checks * 100, 2) as pass_rate,
  r.date_range_start,
  r.date_range_end,
  r.remediation_available,
  r.remediation_commands_count,
  -- Time since last validation
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), r.validation_timestamp, HOUR) as hours_since_validation,
  -- Status indicator
  CASE 
    WHEN r.overall_status = 'fail' THEN '🔴 FAILING'
    WHEN r.overall_status = 'warn' THEN '🟡 WARNING'
    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), r.validation_timestamp, HOUR) > 48 THEN '⚠️ STALE'
    ELSE '✅ HEALTHY'
  END as health_status
FROM `validation.validation_runs` r
INNER JOIN latest_runs l
  ON r.processor_name = l.processor_name
  AND r.processor_type = l.processor_type
  AND r.validation_timestamp = l.latest_validation
ORDER BY 
  CASE r.overall_status
    WHEN 'fail' THEN 1
    WHEN 'warn' THEN 2
    ELSE 3
  END,
  r.processor_name;

-- ============================================================================
-- View: Validation Coverage (Which Processors Are Validated?)
-- ============================================================================

CREATE OR REPLACE VIEW `validation.validation_coverage` AS
WITH processor_list AS (
  -- All processors that have ever been validated
  SELECT DISTINCT 
    processor_name,
    processor_type
  FROM `validation.validation_runs`
),
last_7_days AS (
  SELECT DISTINCT processor_name
  FROM `validation.validation_runs`
  WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
),
last_30_days AS (
  SELECT DISTINCT processor_name
  FROM `validation.validation_runs`
  WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
)
SELECT 
  p.processor_name,
  p.processor_type,
  CASE 
    WHEN d7.processor_name IS NOT NULL THEN '✅ Active (7d)'
    WHEN d30.processor_name IS NOT NULL THEN '⚠️ Inactive (7d)'
    ELSE '🔴 No Recent Validation'
  END as validation_status,
  (SELECT MAX(validation_timestamp) 
   FROM `validation.validation_runs` 
   WHERE processor_name = p.processor_name) as last_validated,
  (SELECT COUNT(DISTINCT DATE(validation_timestamp))
   FROM `validation.validation_runs`
   WHERE processor_name = p.processor_name
     AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  ) as validations_last_30d
FROM processor_list p
LEFT JOIN last_7_days d7 ON p.processor_name = d7.processor_name
LEFT JOIN last_30_days d30 ON p.processor_name = d30.processor_name
ORDER BY 
  CASE 
    WHEN d7.processor_name IS NOT NULL THEN 1
    WHEN d30.processor_name IS NOT NULL THEN 2
    ELSE 3
  END,
  p.processor_type,
  p.processor_name;

-- ============================================================================
-- Usage Examples
-- ============================================================================

/*
-- Example 1: Get all failures from last validation run
SELECT * FROM `validation.validation_failures_recent`
WHERE processor_name = 'espn_scoreboard'
ORDER BY severity DESC;

-- Example 2: Check processor health
SELECT * FROM `validation.processor_status_current`
WHERE overall_status IN ('fail', 'warn');

-- Example 3: Get remediation commands for failures
SELECT 
  processor_name,
  check_name,
  message,
  remediation_commands
FROM `validation.validation_results`
WHERE passed = FALSE
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND remediation_commands IS NOT NULL;

-- Example 4: Data quality trend for specific processor
SELECT 
  week_start,
  pass_rate,
  pass_rate_change,
  total_checks
FROM `validation.validation_trends`
WHERE processor_name = 'bdl_boxscores'
  AND processor_type = 'raw'
ORDER BY week_start DESC
LIMIT 12;  -- Last 12 weeks

-- Example 5: Critical failures that need immediate attention
SELECT 
  validation_timestamp,
  processor_name,
  check_name,
  message,
  affected_count,
  remediation_commands
FROM `validation.validation_results`
WHERE severity = 'critical'
  AND passed = FALSE
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY validation_timestamp DESC;

-- Example 6: Validation coverage report
SELECT * FROM `validation.validation_coverage`
ORDER BY 
  CASE validation_status
    WHEN '✅ Active (7d)' THEN 1
    WHEN '⚠️ Inactive (7d)' THEN 2
    ELSE 3
  END,
  processor_type,
  processor_name;
*/