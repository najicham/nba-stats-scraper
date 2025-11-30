# NBA Props Platform - Grafana Setup Guide

`docs/monitoring/grafana_setup_guide.md`

**Version:** 1.0  
**Created:** November 11, 2025  
**Purpose:** Step-by-step guide to set up Grafana dashboards for NBA Props Platform monitoring

---

## Overview

This guide walks through:
1. ✅ BigQuery data source configuration in Grafana
2. ✅ Service account setup and permissions
3. ✅ Creating your first dashboard
4. ✅ Query templates for each monitoring panel
5. ✅ Cost optimization best practices

**Prerequisites:**
- Grafana Cloud account (or self-hosted Grafana 9.0+)
- GCP project: `nba-props-platform`
- BigQuery dataset: `nba_orchestration` (already created)

---

## Part 1: Service Account Setup

### Step 1: Create Grafana Service Account

```bash
# Create service account for Grafana
gcloud iam service-accounts create grafana-viewer \
  --display-name="Grafana Dashboard Viewer" \
  --description="Read-only access for Grafana dashboards" \
  --project=nba-props-platform

# Grant BigQuery Data Viewer role
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:grafana-viewer@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

# Grant BigQuery Job User role (needed to run queries)
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:grafana-viewer@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
```

### Step 2: Generate Service Account Key

```bash
# Create JSON key file
gcloud iam service-accounts keys create ~/grafana-bigquery-key.json \
  --iam-account=grafana-viewer@nba-props-platform.iam.gserviceaccount.com \
  --project=nba-props-platform

# Output: Created key [...] for [grafana-viewer@nba-props-platform.iam.gserviceaccount.com]
# File saved to: ~/grafana-bigquery-key.json
```

⚠️ **Security:** Keep this file secure! It grants read access to your BigQuery data.

---

## Part 2: Configure Grafana Data Source

### Step 1: Add BigQuery Data Source

1. **Open Grafana** → Settings (⚙️) → Data Sources
2. **Click "Add data source"**
3. **Search for "BigQuery"** and select it
4. **Configure:**

```yaml
Name: NBA Props BigQuery
Authentication Type: Google JWT File
Project ID: nba-props-platform
Default Dataset: nba_orchestration
Upload Service Account Key: [Upload grafana-bigquery-key.json]
Processing Location: us-west2
```

5. **Click "Save & Test"**

✅ Expected: "Data source is working"

### Step 2: Test Query

In Grafana Explore panel:
```sql
SELECT COUNT(*) as total_executions
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

✅ Expected: Returns a count (even if 0)

---

## Part 3: Create Your First Dashboard

### Dashboard: Phase 1 Workflow Health

**Create New Dashboard:**
1. Dashboards → New Dashboard
2. Name: "NBA Props - Phase 1 Workflow Health"
3. Add panels using templates below

---

### Panel 1: Expected vs Actual Executions ⭐ MOST IMPORTANT

**Visualization:** Table  
**Query Mode:** SQL  
**Refresh:** 5 minutes

```sql
WITH expected AS (
  SELECT 
    workflow_name, 
    expected_run_time,
    FORMAT_TIMESTAMP('%H:%M ET', expected_run_time, 'America/New_York') as expected_time,
    priority
  FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
actual AS (
  SELECT DISTINCT 
    workflow_name, 
    decision_time,
    FORMAT_TIMESTAMP('%H:%M ET', decision_time, 'America/New_York') as actual_time
  FROM `nba-props-platform.nba_orchestration.workflow_decisions`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND action = 'RUN'
)
SELECT 
  expected.workflow_name as "Workflow",
  expected.priority as "Priority",
  expected.expected_time as "Expected Time",
  COALESCE(actual.actual_time, '—') as "Actual Time",
  CASE 
    WHEN actual.workflow_name IS NULL THEN '🔴 MISSING'
    WHEN actual.decision_time > TIMESTAMP_ADD(expected.expected_run_time, INTERVAL 15 MINUTE) 
      THEN '🟡 LATE'
    ELSE '✅ ON TIME'
  END as "Status",
  TIMESTAMP_DIFF(actual.decision_time, expected.expected_run_time, MINUTE) as "Minutes Late"
FROM expected
LEFT JOIN actual ON expected.workflow_name = actual.workflow_name
ORDER BY 
  CASE 
    WHEN actual.workflow_name IS NULL THEN 1
    WHEN actual.decision_time > TIMESTAMP_ADD(expected.expected_run_time, INTERVAL 15 MINUTE) THEN 2
    ELSE 3
  END,
  expected.expected_run_time
```

**Table Settings:**
- Column: "Status" → Add value mapping:
  - `🔴 MISSING` → Red background
  - `🟡 LATE` → Yellow background
  - `✅ ON TIME` → Green background

---

### Panel 2: Missing Workflows Alert

**Visualization:** Stat (big number)  
**Query Mode:** SQL  
**Refresh:** 1 minute

```sql
WITH expected AS (
  SELECT workflow_name
  FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
actual AS (
  SELECT DISTINCT workflow_name
  FROM `nba-props-platform.nba_orchestration.workflow_decisions`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND action = 'RUN'
)
SELECT COUNT(*) as missing_workflows
FROM expected
LEFT JOIN actual ON expected.workflow_name = actual.workflow_name
WHERE actual.workflow_name IS NULL
```

**Stat Panel Settings:**
- Title: "Missing Workflows Today"
- Unit: None
- Thresholds:
  - 0 = Green
  - 1 = Red
- Display: "Big number" with colored background

---

### Panel 3: Workflow Success Rate (7 Days)

**Visualization:** Time series  
**Query Mode:** SQL  
**Refresh:** 10 minutes

```sql
SELECT 
  TIMESTAMP_TRUNC(decision_time, DAY) as time,
  workflow_name,
  COUNTIF(action = 'RUN') * 100.0 / COUNT(*) as success_rate
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY time, workflow_name
ORDER BY time
```

**Time Series Settings:**
- Y-axis: 0-100 (percentage)
- Legend: Show all workflows
- Add threshold line at 95% (SLA target)

---

### Panel 4: Scraper Execution Status

**Visualization:** Table  
**Query Mode:** SQL  
**Refresh:** 5 minutes

```sql
SELECT 
  scraper_name as "Scraper",
  COUNT(*) as "Total Runs",
  COUNTIF(status = 'success') as "Success",
  COUNTIF(status = 'failed') as "Failed",
  COUNTIF(status = 'no_data') as "No Data",
  ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 1) as "Success Rate %",
  MAX(triggered_at) as "Last Run",
  FORMAT_TIMESTAMP('%H:%M ET', MAX(triggered_at), 'America/New_York') as "Last Run Time"
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY scraper_name
ORDER BY "Success Rate %" ASC, "Total Runs" DESC
```

---

### Panel 5: Self-Healing Activity

**Visualization:** Stat  
**Query Mode:** SQL  
**Refresh:** 5 minutes

```sql
SELECT 
  SUM(files_republished) as total_recovered
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE cleanup_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

**Stat Panel Settings:**
- Title: "Files Auto-Recovered (24h)"
- Unit: None
- Color: Green if > 0 (shows self-healing working)

---

## Part 4: Cost Optimization

### Query Best Practices

**✅ DO:**
```sql
-- Use partitioning filters (reduces data scanned)
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')

-- Limit time ranges
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)

-- Use LIMIT for large result sets
LIMIT 100

-- Aggregate data (not raw rows)
GROUP BY workflow_name
```

**❌ DON'T:**
```sql
-- Scan entire table
SELECT * FROM workflow_decisions  -- NO!

-- No time filter
WHERE workflow_name = 'morning_operations'  -- Scans all history!

-- Return millions of rows
SELECT * FROM scraper_execution_log  -- Expensive!
```

### Dashboard Settings

**Refresh Intervals:**
- Critical panels: 1 minute (Missing Workflows)
- Standard panels: 5 minutes (Execution Status)
- Trend panels: 10 minutes (Success Rate over time)
- Historical panels: 30 minutes (7-day trends)

**Expected Costs:**
- ~10-20 queries per dashboard
- Each query: <1 MB scanned (with partitioning)
- Cost: <$0.01 per dashboard refresh
- Monthly: ~$10-20 for all dashboards

---

## Summary

✅ **What You've Built:**
- BigQuery data source connected to Grafana
- First dashboard with 5 key monitoring panels
- Real-time visibility into Phase 1 orchestration
- Foundation for future phase dashboards

---

## Available Dashboards

### Dashboard Inventory

| Dashboard | File | Purpose | Key Tables |
|-----------|------|---------|------------|
| **Pipeline Run History** | `dashboards/pipeline-run-history-dashboard.json` | Phase 2-5 processor monitoring | `processor_run_history`, `prediction_worker_runs` |
| **Data Quality** | `dashboards/data-quality-dashboard.json` | Name resolution & circuit breakers | `unresolved_player_names`, `circuit_breaker_state` |
| **Completeness** | `dashboards/completeness-dashboard.json` | Data completeness & production readiness | `upcoming_player_game_context`, `ml_feature_store_v2` |

### Import Instructions

1. Open Grafana → Dashboards → Import
2. Click "Upload JSON file"
3. Select dashboard JSON from `docs/07-monitoring/grafana/dashboards/`
4. Select your BigQuery data source
5. Click Import

### Dashboard Documentation

| Dashboard | Guide | SQL Queries |
|-----------|-------|-------------|
| Pipeline Run History | `pipeline-monitoring.md` | `dashboards/pipeline-run-history-queries.sql` |
| Data Quality | `data-quality-monitoring.md` | `dashboards/data-quality-queries.sql` |
| Completeness | `monitoring-guide.md` | `dashboards/completeness-queries.sql` |
| Daily Health Check | `daily-health-check.md` | (inline in guide) |

### Quick Help

**New to monitoring?** Start with `faq-troubleshooting.md` - answers common questions like:
- "How do I check if the pipeline is healthy?"
- "Why did a processor fail?"
- "How do I trace a pipeline execution?"

### Recommended Monitoring Workflow

1. **Daily Health Check** (`daily-health-check.md`)
   - Quick 30-second system health view
   - Phase 1 orchestration status

2. **Pipeline Run History** (`pipeline-run-history-dashboard.json`)
   - Phase 2-5 processor health
   - Processing success rates
   - Prediction coordinator runs

3. **Data Quality** (`data-quality-dashboard.json`)
   - Unresolved player names
   - Circuit breaker status
   - Name resolution progress

4. **Completeness** (`completeness-dashboard.json`)
   - Data completeness checks
   - Production readiness
   - Circuit breaker triggers

---

## File Structure

```
docs/07-monitoring/grafana/
├── setup.md                          # This file - setup & index
├── faq-troubleshooting.md            # FAQ & troubleshooting guide (START HERE)
├── monitoring-guide.md               # Phase 1 orchestration queries
├── pipeline-monitoring.md            # Phase 2-5 pipeline queries
├── data-quality-monitoring.md        # Data quality monitoring guide
├── daily-health-check.md             # Quick daily health check
└── dashboards/
    ├── pipeline-run-history-dashboard.json  (12 panels)
    ├── pipeline-run-history-queries.sql     (16 queries)
    ├── data-quality-dashboard.json          (13 panels)
    ├── data-quality-queries.sql             (12 queries)
    ├── completeness-dashboard.json          (10 panels)
    └── completeness-queries.sql
```

---

**Document Version:** 2.0
**Last Updated:** 2025-11-30
**Status:** Ready for Implementation
