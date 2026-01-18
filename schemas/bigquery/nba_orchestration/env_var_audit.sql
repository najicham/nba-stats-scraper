-- =====================================================================
-- NBA Orchestration - Environment Variable Audit Table
--
-- Tracks all environment variable changes over time for prediction-worker
-- Used for compliance, debugging, and incident investigation
--
-- Created: 2026-01-17 (Week 3 - Option B Implementation)
-- =====================================================================

CREATE TABLE IF NOT EXISTS `nba_orchestration.env_var_audit` (
  -- Unique identifier for this change event
  change_id STRING NOT NULL,

  -- When this change was detected
  timestamp TIMESTAMP NOT NULL,

  -- Type of change event
  change_type STRING NOT NULL,  -- ADDED, REMOVED, MODIFIED, DEPLOYMENT_START, BASELINE_INIT

  -- Details of what changed
  changed_vars ARRAY<STRUCT<
    var_name STRING,
    old_value STRING,  -- NULL if ADDED
    new_value STRING   -- NULL if REMOVED
  >>,

  -- Who/what initiated this change
  deployer STRING,  -- Service account or user email

  -- Reason for change (if provided)
  reason STRING,  -- e.g., "deployment", "manual update", "emergency fix"

  -- Deployment grace period context
  deployment_started_at TIMESTAMP,
  in_deployment_window BOOLEAN,

  -- Service context
  service_name STRING DEFAULT 'prediction-worker',
  service_revision STRING,
  environment STRING,  -- prod, staging, dev

  -- Hash of env vars for quick comparison
  env_hash STRING,

  -- Metadata
  alert_triggered BOOLEAN DEFAULT FALSE,
  alert_reason STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(timestamp)
CLUSTER BY change_type, service_name, timestamp
OPTIONS (
  description = 'Environment variable change audit log for NBA prediction worker',
  labels = [('project', 'nba-props-platform'), ('component', 'monitoring')]
);

-- Create indexes for common queries
-- Note: BigQuery doesn't support traditional indexes, but clustering handles this

-- =====================================================================
-- Sample Queries
-- =====================================================================

-- Query 1: Recent env var changes (last 30 days)
/*
SELECT
  timestamp,
  change_type,
  changed_vars,
  reason,
  in_deployment_window,
  alert_triggered
FROM `nba_orchestration.env_var_audit`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY timestamp DESC
LIMIT 100;
*/

-- Query 2: All changes to a specific variable
/*
SELECT
  timestamp,
  change_type,
  var.var_name,
  var.old_value,
  var.new_value,
  reason,
  alert_triggered
FROM `nba_orchestration.env_var_audit`,
UNNEST(changed_vars) as var
WHERE
  var.var_name = 'CATBOOST_V8_MODEL_PATH'
ORDER BY timestamp DESC;
*/

-- Query 3: Changes that triggered alerts
/*
SELECT
  timestamp,
  change_type,
  changed_vars,
  alert_reason,
  deployer
FROM `nba_orchestration.env_var_audit`
WHERE
  alert_triggered = TRUE
ORDER BY timestamp DESC
LIMIT 50;
*/

-- Query 4: Changes outside deployment windows (unexpected changes)
/*
SELECT
  timestamp,
  change_type,
  changed_vars,
  reason,
  deployer
FROM `nba_orchestration.env_var_audit`
WHERE
  in_deployment_window = FALSE
  AND change_type IN ('ADDED', 'REMOVED', 'MODIFIED')
ORDER BY timestamp DESC;
*/
