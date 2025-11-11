# NBA Orchestration Dataset - Phase 1 Orchestration

**File:** `schemas/bigquery/nba_orchestration/README.md`

## Overview

The `nba_orchestration` dataset provides comprehensive logging infrastructure for Phase 1 orchestration, enabling workflow automation, discovery mode support, expected vs actual monitoring, and self-healing capabilities.

### Tables

| Table | Purpose | Update Frequency | Key Use Case |
|-------|---------|------------------|--------------|
| `scraper_execution_log` | Every scraper run with 3-status tracking | Real-time | Discovery mode decisions, success rate analysis |
| `workflow_decisions` | Controller evaluation decisions | Hourly (or on-demand) | Expected vs actual comparison, workflow patterns |
| `daily_expected_schedule` | Expected workflow schedule for the day | Daily at 5 AM ET | Grafana monitoring, missed execution alerts |
| `cleanup_operations` | Self-healing recovery operations | Every 30 minutes | Processing pipeline health, recovery effectiveness |

## Three-Status System

The core innovation in Phase 1 orchestration is the **3-status system** for scraper execution results:

| Status | Meaning | Record Count | Discovery Mode Behavior |
|--------|---------|--------------|------------------------|
| `success` | Got data | > 0 | ✅ **Stop trying** - data found, mission accomplished |
| `no_data` | Tried but empty | = 0 | 📭 **Keep trying** - data not published yet, try again in 1 hour |
| `failed` | Real error | N/A | ❌ **Retry immediately** - network/API issue, retry up to max_retries |

### Why This Matters

**Old Approach (2-status):**
- `success` or `failed` only
- "No data yet" considered a failure
- Caused retry loops and false alerts

**New Approach (3-status):**
- Distinguishes between "no data yet" and "real error"
- Discovery mode works cleanly
- No false alerts when injury report not published yet

### Discovery Mode Example

**Scenario:** Injury report typically published between 11 AM - 3 PM ET

```python
# Controller evaluates injury_discovery workflow every hour:

11:00 AM → status='no_data' → Try again at 12:00 PM
12:00 PM → status='no_data' → Try again at 1:00 PM  
1:00 PM → status='success', record_count=12 → ✅ STOP! Data found!
2:00 PM → Check scraper_execution_log → Already success today → SKIP
```

## Quick Start

### 1. Deploy Tables

```bash
cd schemas/bigquery/nba_orchestration
./deploy_tables.sh
```

### 2. Verify Deployment

```bash
# List tables
bq ls nba-props-platform:nba_orchestration

# Check schema
bq show --schema nba-props-platform:nba_orchestration.scraper_execution_log

# Test query
bq query "SELECT table_name FROM \`nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.TABLES\`"
```

### 3. Test with Sample Data

```bash
# Run a scraper locally (will log to execution_log)
python -m scrapers.nbacom.nbac_injury_report \
  --gamedate 20250115 \
  --hour 8 \
  --period AM

# Check log
bq query "
SELECT 
  scraper_name,
  status,
  source,
  JSON_VALUE(data_summary, '$.record_count') as records
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
ORDER BY triggered_at DESC
LIMIT 1
"
```

## Common Queries

### Discovery Mode: Check if Data Found Today

```sql
SELECT 
  status,
  JSON_VALUE(data_summary, '$.record_count') as records,
  triggered_at,
  FORMAT_TIMESTAMP('%I:%M %p', triggered_at, 'America/New_York') as time_et
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_injury_report'
  AND DATE(triggered_at) = CURRENT_DATE()
ORDER BY triggered_at DESC
LIMIT 1;
```

**Expected Results:**
- Early morning: `status='no_data', records='0'` (not published yet)
- After 1 PM ET: `status='success', records='12'` (found data!)

### Count Discovery Attempts Today

```sql
SELECT 
  COUNT(*) as attempts_today,
  COUNTIF(status = 'success' AND CAST(JSON_VALUE(data_summary, '$.record_count') AS INT64) > 0) as found_data,
  COUNTIF(status = 'no_data') as no_data_yet,
  COUNTIF(status = 'failed') as failures
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE scraper_name = 'nbac_injury_report'
  AND DATE(triggered_at) = CURRENT_DATE();
```

### Success Rates by Scraper (Last 7 Days)

```sql
SELECT 
  scraper_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as success_count,
  ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 1) as success_rate_pct,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY scraper_name
ORDER BY success_rate_pct ASC;
```

### Expected vs Actual Today (Grafana Query)

```sql
WITH expected AS (
  SELECT 
    workflow_name,
    expected_run_time,
    reason as expected_reason
  FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
  WHERE date = CURRENT_DATE('America/New_York')
),
actual AS (
  SELECT 
    workflow_name,
    decision_time as actual_run_time,
    action,
    reason as actual_reason
  FROM `nba-props-platform.nba_orchestration.workflow_decisions`
  WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
    AND action = 'RUN'
)
SELECT 
  expected.workflow_name,
  FORMAT_TIMESTAMP('%H:%M', expected.expected_run_time, 'America/New_York') as expected_time,
  FORMAT_TIMESTAMP('%H:%M', actual.actual_run_time, 'America/New_York') as actual_time,
  CASE 
    WHEN actual.workflow_name IS NULL THEN '🔴 MISSING'
    WHEN TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) > 30 THEN '🟡 LATE'
    ELSE '✅ ON TIME'
  END as status,
  expected.expected_reason,
  actual.actual_reason
FROM expected
LEFT JOIN actual 
  ON expected.workflow_name = actual.workflow_name
  AND TIMESTAMP_DIFF(actual.actual_run_time, expected.expected_run_time, MINUTE) < 60
ORDER BY expected.expected_run_time;
```

### Self-Healing: Currently Missing Files

```sql
WITH latest_cleanup AS (
  SELECT 
    cleanup_time,
    missing_files
  FROM `nba-props-platform.nba_orchestration.cleanup_operations`
  ORDER BY cleanup_time DESC
  LIMIT 1
)
SELECT 
  mf.scraper_name,
  mf.gcs_path,
  mf.age_minutes,
  mf.republished,
  CASE 
    WHEN mf.age_minutes > 240 THEN '🔴 CRITICAL (>4h)'
    WHEN mf.age_minutes > 120 THEN '🟡 WARNING (>2h)'
    ELSE '🟠 RECENT (<2h)'
  END as urgency
FROM latest_cleanup,
UNNEST(missing_files) as mf
ORDER BY mf.age_minutes DESC;
```

## Source Tracking

Every scraper execution tracks where it came from:

| Source | Meaning | Use Case |
|--------|---------|----------|
| `CONTROLLER` | Master workflow controller | Automated orchestration |
| `MANUAL` | Direct API call | Testing, debugging |
| `LOCAL` | Dev machine | Development |
| `CLOUD_RUN` | Direct endpoint call | Integration tests |
| `SCHEDULER` | Cloud Scheduler job | Legacy cron jobs |
| `RECOVERY` | Cleanup processor | Self-healing |

### Cost Analysis by Source

```sql
SELECT 
  source,
  environment,
  COUNT(*) as executions,
  COUNTIF(status = 'success') as successful,
  ROUND(AVG(duration_seconds), 2) as avg_duration,
  SUM(duration_seconds) as total_seconds
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY source, environment
ORDER BY executions DESC;
```

## Monitoring & Alerts

### Alert Thresholds

| Alert | Threshold | Severity | Action |
|-------|-----------|----------|--------|
| No successful runs in last hour | CRITICAL workflows | 🔴 CRITICAL | Check controller, scraper health |
| High failure rate | >20% failed | 🟡 WARNING | Investigate specific scraper |
| Missing workflow execution | Expected but not run | 🔴 CRITICAL | Check controller logs |
| High missing file count | >10 files | 🟡 WARNING | Check Phase 2 processors |
| Cleanup not running | No runs in 2 hours | 🔴 CRITICAL | Restart cleanup processor |

### Sample Alert Queries

**Alert: Critical Workflow Not Run**
```sql
SELECT 
  'workflow_decisions' as alert_source,
  workflow_name,
  MAX(decision_time) as last_evaluation,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(decision_time), HOUR) as hours_since_last
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE priority = 'CRITICAL'
  AND DATE(decision_time) = CURRENT_DATE()
GROUP BY workflow_name
HAVING TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(decision_time), HOUR) > 2;
```

**Alert: High Failure Rate**
```sql
SELECT 
  scraper_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'failed') as failures,
  ROUND(COUNTIF(status = 'failed') * 100.0 / COUNT(*), 1) as failure_rate_pct
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY scraper_name
HAVING ROUND(COUNTIF(status = 'failed') * 100.0 / COUNT(*), 1) > 20.0;
```

## Partitioning & Clustering

All tables use **daily partitioning** for efficient queries:

```sql
-- ✅ GOOD - Filters on partition key
SELECT * FROM scraper_execution_log
WHERE DATE(triggered_at) = '2025-01-15';

-- ❌ BAD - Full table scan
SELECT * FROM scraper_execution_log
WHERE scraper_name = 'nbac_injury_report';

-- ✅ BETTER - Partition filter + clustering
SELECT * FROM scraper_execution_log
WHERE DATE(triggered_at) = '2025-01-15'
  AND scraper_name = 'nbac_injury_report';
```

### Clustering Keys

| Table | Clustering Keys | Why |
|-------|----------------|-----|
| `scraper_execution_log` | scraper_name, workflow, status, source | Common filter combinations |
| `workflow_decisions` | workflow_name, action, alert_level | Expected vs actual queries |
| `daily_expected_schedule` | workflow_name, expected_run_time | Time-based monitoring |
| `cleanup_operations` | missing_files_found, republished_count | Alert queries |

## Integration Examples

### Scraper Base Class Integration

```python
# In scrapers/scraper_base.py

def _log_execution_to_bigquery(self):
    """Log execution to nba_orchestration.scraper_execution_log"""
    source, environment, triggered_by = self._determine_execution_source()
    
    # Determine status (3-status system)
    if isinstance(self.data, dict):
        record_count = len(self.data.get('records', []))
        is_empty = self.data.get('metadata', {}).get('is_empty_report', False)
        status = 'no_data' if (is_empty or record_count == 0) else 'success'
    elif isinstance(self.data, list):
        record_count = len(self.data)
        status = 'success' if record_count > 0 else 'no_data'
    else:
        record_count = 0
        status = 'no_data'
    
    record = {
        'execution_id': self.run_id,
        'scraper_name': self._get_scraper_name(),
        'workflow': self.opts.get('workflow', 'MANUAL'),
        'status': status,
        'triggered_at': datetime.utcnow(),
        'completed_at': datetime.utcnow(),
        'duration_seconds': self.stats.get('total_runtime', 0),
        'source': source,
        'environment': environment,
        'triggered_by': triggered_by,
        'gcs_path': self.opts.get('gcs_output_path'),
        'data_summary': {
            'record_count': record_count,
            'scraper_stats': self.get_scraper_stats()
        },
        'recovery': self.opts.get('recovery', False),
        'run_id': self.run_id,
        'opts': {k: v for k, v in self.opts.items() if k not in ['password', 'api_key']}
    }
    
    from shared.utils.bigquery_utils import insert_bigquery_rows
    insert_bigquery_rows('nba_orchestration', 'scraper_execution_log', [record])
    logger.info(f"✅ Logged execution: {status} from {source}")
```

### Master Controller Integration

```python
# In orchestration/master_controller.py

def log_workflow_decision(self, workflow_name: str, action: str, reason: str, context: dict):
    """Log workflow evaluation decision"""
    record = {
        'decision_id': str(uuid.uuid4()),
        'decision_time': datetime.utcnow(),
        'workflow_name': workflow_name,
        'action': action,  # RUN, SKIP, ABORT
        'reason': reason,
        'context': context,
        'scrapers_triggered': context.get('scrapers', []),
        'target_games': context.get('target_games', []),
        'next_check_time': context.get('next_check_time'),
        'priority': workflow_config.get('priority'),
        'alert_level': self._determine_alert_level(action, workflow_config),
        'controller_version': self.version,
        'environment': self.environment,
        'triggered_by': 'cloud-scheduler'
    }
    
    insert_bigquery_rows('nba_orchestration', 'workflow_decisions', [record])
    logger.info(f"📋 Logged decision: {workflow_name} → {action}")
```

## Data Retention

All tables use **90-day partition expiration**:

- Keeps recent data for debugging and analysis
- Automatically removes old partitions
- Reduces storage costs
- Compliance with data retention policies

To query older data before it expires:
```bash
# Export to GCS before expiration
bq extract \
  --destination_format=NEWLINE_DELIMITED_JSON \
  nba-props-platform:nba_orchestration.scraper_execution_log\$20241015 \
  gs://nba-props-archive/logs/scraper_execution_log/2024-10-15.json
```

## Troubleshooting

### Issue: JSON field returns NULL

**Problem:** `JSON_VALUE(data_summary, '$.record_count')` returns NULL

**Solution:**
```sql
-- Check if field exists
SELECT 
  data_summary,
  JSON_VALUE(data_summary, '$.record_count') as records
FROM scraper_execution_log
WHERE scraper_name = 'nbac_injury_report'
LIMIT 5;

-- Verify JSON structure
SELECT 
  scraper_name,
  JSON_EXTRACT(data_summary, '$') as full_json
FROM scraper_execution_log
LIMIT 1;
```

### Issue: Query scans too much data

**Problem:** "This query will process 10 GB"

**Solution:** Always filter on partition key
```sql
-- ❌ BAD
SELECT * FROM scraper_execution_log
WHERE scraper_name = 'nbac_injury_report';

-- ✅ GOOD  
SELECT * FROM scraper_execution_log
WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND scraper_name = 'nbac_injury_report';
```

### Issue: Missing expected workflows

**Problem:** Expected schedule shows workflow, but no actual execution

**Steps:**
1. Check `workflow_decisions` for SKIP/ABORT actions
2. Check controller logs for evaluation errors
3. Verify workflow config is correct
4. Check if schedule was generated today

```sql
-- Check why workflow was skipped
SELECT 
  decision_time,
  action,
  reason,
  context
FROM workflow_decisions
WHERE workflow_name = 'betting_lines'
  AND DATE(decision_time) = CURRENT_DATE()
ORDER BY decision_time DESC;
```

## Best Practices

### 1. Always Filter on Partition Keys

```sql
-- Every query should have this:
WHERE DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

### 2. Use Clustering Fields in WHERE Clauses

```sql
-- Takes advantage of clustering:
WHERE DATE(triggered_at) = CURRENT_DATE()
  AND scraper_name = 'nbac_injury_report'
  AND status = 'success'
```

### 3. Avoid SELECT *

```sql
-- ❌ BAD - Scans all columns
SELECT * FROM scraper_execution_log;

-- ✅ GOOD - Only needed columns
SELECT scraper_name, status, triggered_at
FROM scraper_execution_log;
```

### 4. Use Views for Common Queries

```sql
-- Create view for frequently used query
CREATE OR REPLACE VIEW v_todays_scraper_summary AS
SELECT 
  scraper_name,
  COUNT(*) as runs,
  COUNTIF(status = 'success') as successes
FROM scraper_execution_log
WHERE DATE(triggered_at) = CURRENT_DATE()
GROUP BY scraper_name;

-- Use the view
SELECT * FROM v_todays_scraper_summary;
```

## Next Steps

After deploying the nba_orchestration dataset:

1. **Week 1 (Current)**
   - [x] Deploy tables
   - [ ] Add logging to `scraper_base.py`
   - [ ] Create `config/workflows.yaml`
   - [ ] Implement `master_controller.py`
   - [ ] Test with sample scrapers

2. **Week 2 (Pub/Sub Integration)**
   - [ ] Implement cleanup processor
   - [ ] Setup Pub/Sub topic
   - [ ] Enable self-healing (pubsub_enabled=true)
   - [ ] Test recovery operations

3. **Week 3 (Monitoring)**
   - [ ] Create Grafana dashboards
   - [ ] Configure alerts
   - [ ] Test alert escalation
   - [ ] Document runbooks

4. **Week 4 (Optimization)**
   - [ ] Tune workflow schedules
   - [ ] Optimize discovery mode intervals
   - [ ] Review and adjust alert thresholds
   - [ ] Performance optimization

## Support

**Questions?** Check existing documentation:
- `schemas/bigquery/nba_orchestration/datasets.sql` - Dataset overview
- Individual table SQL files for detailed field descriptions
- `DEPLOYMENT_GUIDE.md` - Deployment instructions

**Issues?** Run validation queries in each table SQL file to diagnose problems.
