# Pipeline Quota Monitoring - Quick Reference

**Quick Links:**
- Full Documentation: `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md`
- Setup Script: `/home/naji/code/nba-stats-scraper/monitoring/scripts/setup_quota_alerts.sh`
- Dashboard JSON: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`
- Query File: `/home/naji/code/nba-stats-scraper/monitoring/queries/quota_usage_tracking.sql`

---

## Common Commands

### Check Current Quota Usage

```sql
-- Current hour's usage
SELECT *
FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp = TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), HOUR);

-- Last 24 hours
SELECT
  hour_timestamp,
  partition_modifications,
  ROUND(partition_modifications / 100.0 * 100, 1) AS quota_pct,
  events_logged,
  avg_batch_size
FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY hour_timestamp DESC;
```

### Get Buffer Metrics from Python

```python
from shared.utils.pipeline_logger import get_buffer_metrics

metrics = get_buffer_metrics()
print(f"Events: {metrics['events_buffered_count']}")
print(f"Flushes: {metrics['batch_flush_count']} (failed: {metrics['failed_flush_count']})")
print(f"Avg batch: {metrics['avg_batch_size']}")
print(f"Avg latency: {metrics['avg_flush_latency_ms']}ms")
```

### Check Event Log

```sql
-- Find top processors by event count (last hour)
SELECT
  processor_name,
  COUNT(*) AS event_count,
  COUNT(DISTINCT game_date) AS unique_dates
FROM nba_orchestration.pipeline_event_log
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY processor_name
ORDER BY event_count DESC
LIMIT 10;

-- Check for errors
SELECT
  timestamp,
  processor_name,
  game_date,
  error_message
FROM nba_orchestration.pipeline_event_log
WHERE event_type = 'error'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY timestamp DESC;
```

---

## Alert Thresholds

| Alert Level | Condition | Action |
|-------------|-----------|--------|
| **WARN** | > 80 partition mods/hour | Monitor closely |
| **CRITICAL** | > 90 partition mods/hour | Increase BATCH_SIZE |
| **FLUSH FAIL** | > 0 failed flushes | Check logs and BigQuery status |
| **HIGH LATENCY** | > 5000ms flush latency | Investigate BigQuery API |

---

## Quick Fixes

### Increase Batch Size (Reduce Quota Usage)

```bash
# Increase to 100 events per batch (reduces quota by 50%)
export PIPELINE_LOG_BATCH_SIZE=100
export PIPELINE_LOG_BATCH_TIMEOUT=15.0
```

### Force Buffer Flush

```python
from shared.utils.pipeline_logger import flush_event_buffer

# Manually flush all pending events
success = flush_event_buffer()
print(f"Flush {'succeeded' if success else 'failed'}")
```

### Check Scheduled Query Status

```bash
# List all transfer configs
bq ls --transfer_config --transfer_location=US

# Get specific transfer runs
bq ls --transfer_run --transfer_config=<CONFIG_ID> --max_results=10
```

---

## Troubleshooting

### Metrics not appearing
```bash
# Check logs for metric events
gcloud logging read 'jsonPayload.message=~"Pipeline Event Buffer Metrics"' --limit 10

# Verify log-based metrics exist
# Go to: Cloud Console > Logging > Logs-based metrics
```

### Alert not firing
```bash
# Check alert policy status
gcloud alpha monitoring policies list --filter="displayName:'Pipeline Quota'"

# View alert incidents
gcloud alpha monitoring policies describe <POLICY_ID>
```

### Scheduled query not running
```bash
# Check recent runs
bq ls --transfer_run --transfer_config=<CONFIG_ID>

# View run details
bq show --transfer_run <RUN_ID>
```

---

## Monitoring Dashboard

Import dashboard: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`

**Location:** Cloud Console > Monitoring > Dashboards > Create Dashboard > Import from JSON

---

## Key Metrics Summary

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Partition mods/hour | < 50 | 80-90 | > 90 |
| Avg batch size | > 40 | 20-40 | < 20 |
| Flush latency | < 500ms | 1000-5000ms | > 5000ms |
| Failed flushes | 0 | 1-5 | > 5 |
| Buffer size | < 50 | 50-100 | > 100 |

---

## Setup Checklist

- [ ] Run setup script: `./monitoring/scripts/setup_quota_alerts.sh <PROJECT_ID> <CHANNEL>`
- [ ] Create log-based metrics in Cloud Console (see Part 3 of full docs)
- [ ] Import dashboard JSON
- [ ] Test alert policies
- [ ] Verify scheduled query runs hourly
- [ ] Update notification channels

---

## Support

**Documentation:** `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md`

**Code Reference:** `/home/naji/code/nba-stats-scraper/shared/utils/pipeline_logger.py` (lines 89-247)
