-- Create phase_boundary_validations table for validation logging
-- Part of: Robustness Improvements - Week 3-4 Phase Boundary Validation
-- Created: January 21, 2026

-- Drop table if it exists (for development/testing only)
-- DROP TABLE IF EXISTS `nba-props-platform.nba_monitoring.phase_boundary_validations`;

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_monitoring.phase_boundary_validations` (
  -- Primary identifiers
  validation_id STRING NOT NULL OPTIONS(description="Unique identifier for this validation run"),
  game_date DATE NOT NULL OPTIONS(description="Date of games being validated"),
  phase_name STRING NOT NULL OPTIONS(description="Phase transition name (e.g., phase2_to_phase3)"),

  -- Validation result
  is_valid BOOL NOT NULL OPTIONS(description="Whether validation passed overall"),
  mode STRING NOT NULL OPTIONS(description="Validation mode: disabled, warning, or blocking"),

  -- Issues (repeated/array field)
  issues ARRAY<STRUCT<
    validation_type STRING OPTIONS(description="Type of validation (game_count, processor_completion, data_quality)"),
    severity STRING OPTIONS(description="Issue severity: info, warning, or error"),
    message STRING OPTIONS(description="Human-readable message describing the issue"),
    details JSON OPTIONS(description="Additional structured details about the issue")
  >> OPTIONS(description="List of validation issues found"),

  -- Metrics
  metrics JSON OPTIONS(description="Validation metrics (counts, scores, thresholds, etc.)"),

  -- Timestamp
  timestamp TIMESTAMP NOT NULL OPTIONS(description="When this validation was performed")
)
PARTITION BY game_date
CLUSTER BY phase_name, is_valid
OPTIONS(
  description="Phase boundary validation results for pipeline quality gates",
  labels=[("component", "validation"), ("project", "robustness-improvements")]
);

-- Create a view for easier querying
CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.phase_validation_summary` AS
SELECT
  game_date,
  phase_name,
  mode,
  COUNTIF(is_valid) as valid_count,
  COUNTIF(NOT is_valid) as invalid_count,
  COUNT(*) as total_validations,
  ROUND(SAFE_DIVIDE(COUNTIF(is_valid), COUNT(*)) * 100, 2) as success_rate_pct,
  MAX(timestamp) as last_validation_time
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date, phase_name, mode
ORDER BY game_date DESC, phase_name;

-- Verification queries

-- 1. Check recent validations
SELECT
  game_date,
  phase_name,
  is_valid,
  mode,
  ARRAY_LENGTH(issues) as issue_count,
  timestamp
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY timestamp DESC
LIMIT 100;

-- 2. Validation failure details
SELECT
  game_date,
  phase_name,
  issue.validation_type,
  issue.severity,
  issue.message,
  JSON_EXTRACT_SCALAR(issue.details, '$.expected') as expected,
  JSON_EXTRACT_SCALAR(issue.details, '$.actual') as actual
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`,
  UNNEST(issues) as issue
WHERE
  game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND is_valid = FALSE
ORDER BY timestamp DESC;

-- 3. Blocking events (critical)
SELECT
  game_date,
  phase_name,
  ARRAY_LENGTH(issues) as issue_count,
  JSON_EXTRACT(metrics, '$.game_count_actual') as actual_games,
  JSON_EXTRACT(metrics, '$.game_count_expected') as expected_games,
  timestamp
FROM `nba-props-platform.nba_monitoring.phase_boundary_validations`
WHERE
  mode = 'blocking'
  AND is_valid = FALSE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY timestamp DESC;
