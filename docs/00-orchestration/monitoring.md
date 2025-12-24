# Monitoring & Alerting

How to monitor the pipeline and what alerts exist.

## Quick Health Checks

### 1. Schedule Data Freshness
```sql
-- Should show games updated within last 2 hours during game days
SELECT game_date, 
       MAX(created_at) as last_update,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as mins_stale
FROM nba_raw.nbac_schedule
WHERE game_date >= CURRENT_DATE()
GROUP BY 1
ORDER BY 1;
```

### 2. Scraper Execution Status
```sql
-- Recent scraper runs
SELECT scraper_name, status, 
       FORMAT_TIMESTAMP('%H:%M ET', created_at, 'America/New_York') as run_time,
       CASE WHEN gcs_path IS NULL THEN 'NULL' ELSE 'SET' END as gcs_path_status
FROM nba_orchestration.scraper_execution_log
WHERE DATE(created_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY created_at DESC
LIMIT 20;
```

### 3. Processor Run History
```sql
-- Recent processor runs
SELECT processor_name, status, data_date,
       FORMAT_TIMESTAMP('%H:%M ET', created_at, 'America/New_York') as run_time
FROM nba_orchestration.processor_run_history
WHERE DATE(created_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY created_at DESC
LIMIT 20;
```

### 4. Error Rate Check
```bash
# Errors in last hour
gcloud logging read 'severity>=ERROR' --limit=50 --freshness=1h \
  --format="table(timestamp,resource.labels.service_name,textPayload)"
```

## Cloud Logging Queries

### All Errors Across Services
```
severity>=ERROR
resource.type="cloud_run_revision"
```

### Specific Service Errors
```
resource.type="cloud_run_revision"
resource.labels.service_name="nba-phase2-raw-processors"
severity>=ERROR
```

### Rate Limited Notifications
```
"Rate limited notification"
```

### Pub/Sub Processing Issues
```
resource.type="cloud_run_revision"
"gcs_path" AND ("NULL" OR "skip")
```

## Alerting

### Email Alerts (Rate Limited)

Alerts are sent via `shared/utils/notification_system.py` with rate limiting:
- Max 5 emails/hour per unique error signature
- Aggregation after 3 occurrences
- 60-minute cooldown before reset

Configuration:
```bash
NOTIFICATION_RATE_LIMIT_PER_HOUR=5
NOTIFICATION_COOLDOWN_MINUTES=60
NOTIFICATION_AGGREGATE_THRESHOLD=3
```

### What Triggers Alerts

| Event | Severity | Rate Limited |
|-------|----------|--------------|
| Processor failure | ERROR | Yes |
| Missing required option | ERROR | No (config error) |
| Client init failure | ERROR | No (critical) |
| No data to process | WARNING | Yes |
| Unresolved players > threshold | WARNING | Yes |

## Dashboards (TODO)

**Current State:** No unified dashboard. Must query BigQuery or Cloud Logging manually.

**Proposed Dashboard:**
1. Pipeline flow status (games → phases)
2. Error rates by service (last 24h)
3. Notification volume (rate limit effectiveness)
4. Service deployment ages
5. Workflow execution history

## Key Metrics to Monitor

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Schedule staleness | < 30 min | 30-60 min | > 60 min |
| Phase 2 processing time | < 30s | 30-60s | > 60s |
| Error rate (per hour) | < 5 | 5-20 | > 20 |
| Notification volume | < 10/hr | 10-50/hr | > 50/hr |

## Setting Up Alerts

### Cloud Monitoring Alert Policy
```bash
# Example: Alert on high error rate
gcloud alpha monitoring policies create \
  --notification-channels=YOUR_CHANNEL \
  --display-name="High Error Rate" \
  --condition-filter='resource.type="cloud_run_revision" AND severity>=ERROR' \
  --condition-threshold-value=20 \
  --condition-threshold-duration=300s
```

### Log-Based Alerts
Create in Cloud Console → Logging → Log Router → Create Sink → Pub/Sub → Cloud Function for custom alerting.
