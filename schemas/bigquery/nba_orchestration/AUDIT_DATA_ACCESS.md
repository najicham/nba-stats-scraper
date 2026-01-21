# NBA Environment Variable Audit Data - Access Guide

## Overview

The `nba_orchestration.env_var_audit` table tracks all environment variable changes for the NBA prediction worker service. This provides a complete audit trail for compliance, debugging, and incident investigation.

## Quick Access

### Recent Changes (Last 30 Days)

```sql
SELECT *
FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC
LIMIT 50;
```

### Changes to a Specific Variable

```sql
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
```

### Unexpected Changes (Outside Deployment Windows)

```sql
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
```

### Changes That Triggered Alerts

```sql
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
```

## Visualizing Audit Data

### Option 1: Looker Studio Dashboard

1. Go to https://lookerstudio.google.com/
2. Create a new data source: BigQuery → `nba_orchestration.recent_env_changes`
3. Add charts:
   - **Timeline**: Line chart with timestamp (X) and change count (Y)
   - **Change Types**: Pie chart of change_type distribution
   - **Variables Changed**: Bar chart of affected_variables
   - **Alert Rate**: Scorecard showing % of changes that triggered alerts

### Option 2: BigQuery Export to Sheets

```sql
-- Export last 100 changes to Google Sheets
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', timestamp) as time,
  change_type,
  ARRAY_TO_STRING(affected_variables, ', ') as variables,
  reason,
  CASE WHEN alert_triggered THEN '⚠️ YES' ELSE '✓ No' END as alert
FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC
LIMIT 100;
```

### Option 3: CLI Query

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
'SELECT
  timestamp,
  change_type,
  ARRAY_TO_STRING(affected_variables, ", ") as variables,
  reason
FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC
LIMIT 20'
```

## Common Use Cases

### Incident Investigation

When investigating why the CatBoost model stopped loading:

```sql
SELECT
  timestamp,
  change_type,
  changed_vars,
  deployer,
  reason
FROM `nba_orchestration.env_var_audit`
WHERE
  EXISTS (
    SELECT 1
    FROM UNNEST(changed_vars) as var
    WHERE var.var_name = 'CATBOOST_V8_MODEL_PATH'
  )
ORDER BY timestamp DESC
LIMIT 10;
```

### Compliance Audit

Generate a report of all changes in a specific time period:

```sql
SELECT
  DATE(timestamp) as date,
  COUNT(*) as total_changes,
  COUNTIF(alert_triggered) as alerts_triggered,
  COUNTIF(in_deployment_window) as planned_changes,
  COUNTIF(NOT in_deployment_window AND change_type != 'DEPLOYMENT_START') as unplanned_changes
FROM `nba_orchestration.env_var_audit`
WHERE
  timestamp >= '2026-01-01'
  AND timestamp < '2026-02-01'
GROUP BY date
ORDER BY date DESC;
```

### Deployer Activity

See who has been making changes:

```sql
SELECT
  deployer,
  COUNT(*) as change_count,
  COUNTIF(alert_triggered) as alerts_triggered,
  MAX(timestamp) as last_change
FROM `nba_orchestration.env_var_audit`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY deployer
ORDER BY change_count DESC;
```

## Data Retention

- **Partitioning**: Table is partitioned by DATE(timestamp)
- **Retention**: No automatic expiration (manual cleanup required if needed)
- **Storage Cost**: ~$0.02/GB/month (minimal given small row size)

## Access Control

Ensure proper IAM permissions for BigQuery access:

```bash
# Grant viewer access
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="user:analyst@company.com" \
  --role="roles/bigquery.dataViewer"
```

## Integration with Alerts

The audit table is populated automatically by `env_monitor.py` when:
- Initial baseline is created
- Deployment grace period is activated
- Changes are detected during deployment
- Unexpected changes trigger alerts

All audit events are logged asynchronously and will not block the monitoring check.
