-- =====================================================================
-- NBA Orchestration - Recent Environment Variable Changes View
--
-- Provides a user-friendly view of env var changes in the last 30 days
-- Used by dashboards and Slack summaries
--
-- Created: 2026-01-17 (Week 3 - Option B Implementation)
-- =====================================================================

CREATE OR REPLACE VIEW `nba_orchestration.recent_env_changes` AS
SELECT
  change_id,
  timestamp,
  change_type,
  changed_vars,
  reason,
  deployer,
  in_deployment_window,
  alert_triggered,
  alert_reason,
  service_name,
  environment,
  -- Calculate days ago for easier reading
  DATE_DIFF(CURRENT_DATE(), DATE(timestamp), DAY) as days_ago,
  -- Extract variable names for easier filtering
  ARRAY(
    SELECT var.var_name
    FROM UNNEST(changed_vars) as var
  ) as affected_variables
FROM `nba_orchestration.env_var_audit`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
ORDER BY timestamp DESC;

-- =====================================================================
-- Example Usage
-- =====================================================================

/*
-- Query: Changes in last 7 days
SELECT
  timestamp,
  change_type,
  affected_variables,
  reason,
  alert_triggered
FROM `nba_orchestration.recent_env_changes`
WHERE days_ago <= 7
ORDER BY timestamp DESC;

-- Query: Unexpected changes (outside deployment window)
SELECT
  timestamp,
  change_type,
  affected_variables,
  reason,
  deployer,
  alert_reason
FROM `nba_orchestration.recent_env_changes`
WHERE
  in_deployment_window = FALSE
  AND change_type IN ('ADDED', 'REMOVED', 'MODIFIED')
ORDER BY timestamp DESC;

-- Query: Changes to CATBOOST_V8_MODEL_PATH
SELECT
  timestamp,
  change_type,
  reason,
  deployer
FROM `nba_orchestration.recent_env_changes`
WHERE 'CATBOOST_V8_MODEL_PATH' IN UNNEST(affected_variables)
ORDER BY timestamp DESC;
*/
