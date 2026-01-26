# Pipeline Quota Usage Monitoring

**Status:** ✅ Implemented (2026-01-26)
**Component:** Pipeline Event Logger
**Purpose:** Track BigQuery quota usage and alert before hitting limits

---

## Overview

This system monitors BigQuery partition modification quota usage to prevent "403 Quota exceeded" errors that can halt pipeline operations. It provides real-time metrics, historical tracking, and proactive alerts.

### Why This Matters

BigQuery enforces quotas on partition modifications:
- **Default limit:** ~100 partition modifications per hour per table
- **Our usage:** Pipeline event logging with batching (50 events/batch)
- **Risk:** Exceeding quota halts event logging and loses observability

### Solution Architecture

```
┌─────────────────────┐
│  Pipeline Logging   │
│   (Application)     │
│                     │
│  ┌──────────────┐   │
│  │ Event Buffer │   │  ← Tracks metrics in-memory
│  │  (Batching)  │   │
│  └──────────────┘   │
└──────────┬──────────┘
           │ Flush every 50 events or 10s
           ↓
┌──────────────────────┐
│   BigQuery Table     │
│ pipeline_event_log   │  ← Stores all events
└──────────┬───────────┘
           │ Hourly scheduled query
           ↓
┌──────────────────────┐
│  Quota Usage Table   │
│ quota_usage_hourly   │  ← Aggregated metrics
└──────────┬───────────┘
           │
           ↓
┌──────────────────────┐
│  Cloud Monitoring    │
│  - Dashboards        │  ← Visualizations & alerts
│  - Alert Policies    │
└──────────────────────┘
```

---

## Quick Start

### 1. Run Setup Script

```bash
cd /home/naji/code/nba-stats-scraper/monitoring/scripts

# Get your notification channel ID
gcloud alpha monitoring channels list --project=<YOUR_PROJECT_ID>

# Run setup
./setup_quota_alerts.sh <PROJECT_ID> <NOTIFICATION_CHANNEL_ID>
```

### 2. Create Log-Based Metrics

Follow instructions in: `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md` (Part 3)

Must create 4 metrics in Cloud Console:
- `pipeline/events_buffered`
- `pipeline/batch_flushes`
- `pipeline/flush_latency_ms`
- `pipeline/flush_failures`

### 3. Import Dashboard

1. Go to Cloud Console > Monitoring > Dashboards
2. Create Dashboard > Import from JSON
3. Upload: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`

### 4. Test

```bash
# Run test suite
python3 monitoring/scripts/test_quota_metrics.py --events 100 --dry-run

# Check metrics
python3 -c "from shared.utils.pipeline_logger import get_buffer_metrics; print(get_buffer_metrics())"
```

---

## Files Created

### Code Changes

- **`shared/utils/pipeline_logger.py`** (Modified)
  - Added metrics tracking to `PipelineEventBuffer` class
  - New methods: `get_metrics()`, `_log_metrics()`
  - New API: `get_buffer_metrics()`
  - Enhanced flush logging with latency and success metrics

### SQL Queries

- **`monitoring/queries/quota_usage_tracking.sql`** (New)
  - BigQuery scheduled query (hourly)
  - Calculates partition modifications, event counts, batch efficiency
  - Creates: `nba_orchestration.quota_usage_hourly` table

### Documentation

- **`monitoring/docs/quota_monitoring_setup.md`** (New)
  - Comprehensive setup guide (7 parts)
  - Cloud Monitoring configuration
  - Alert policy definitions
  - Troubleshooting guide

- **`monitoring/docs/quota_monitoring_quick_reference.md`** (New)
  - Quick commands and SQL queries
  - Alert thresholds
  - Common troubleshooting
  - Setup checklist

### Scripts

- **`monitoring/scripts/setup_quota_alerts.sh`** (New)
  - Automated setup script
  - Creates BigQuery table, scheduled query, alert policies
  - Verification checks

- **`monitoring/scripts/test_quota_metrics.py`** (New)
  - Test suite for metrics collection
  - Validates batching efficiency
  - Tests thread safety

### Dashboards

- **`monitoring/dashboards/pipeline_quota_dashboard.json`** (New)
  - Pre-configured dashboard with 10 charts
  - Partition modifications, flush latency, batch sizes
  - Ready to import into Cloud Monitoring

---

## Metrics Tracked

### Application-Level (Python)

| Metric | Type | Description |
|--------|------|-------------|
| `events_buffered_count` | Counter | Total events buffered |
| `batch_flush_count` | Counter | Successful batch flushes |
| `failed_flush_count` | Counter | Failed flush attempts |
| `avg_flush_latency_ms` | Gauge | Average flush time |
| `avg_batch_size` | Gauge | Events per batch |
| `current_buffer_size` | Gauge | Pending events |

**Access via:**
```python
from shared.utils.pipeline_logger import get_buffer_metrics
metrics = get_buffer_metrics()
```

### BigQuery-Level (SQL)

Stored in `nba_orchestration.quota_usage_hourly`:

| Column | Description |
|--------|-------------|
| `partition_modifications` | Estimated partition mods per hour |
| `events_logged` | Total events logged |
| `avg_batch_size` | Average batch efficiency |
| `unique_processors` | Number of active processors |
| `unique_game_dates` | Number of dates processed |
| `error_events` | Count of error events |

**Query:**
```sql
SELECT * FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY hour_timestamp DESC;
```

---

## Alert Policies

### 1. High Quota Usage Warning (80%)

**Triggers when:** Partition modifications > 80/hour
**Duration:** 5 minutes
**Channels:** Email, Slack
**Action:** Monitor closely

### 2. Critical Quota Usage (90%)

**Triggers when:** Partition modifications > 90/hour
**Duration:** 1 minute
**Channels:** PagerDuty, Email, Slack
**Action:** Increase BATCH_SIZE immediately

### 3. Flush Failures

**Triggers when:** Failed flush count > 0
**Duration:** 5 minutes
**Channels:** Email, Slack
**Action:** Check logs and BigQuery status

### 4. High Flush Latency

**Triggers when:** Avg latency > 5000ms
**Duration:** 10 minutes
**Channels:** Email
**Action:** Investigate BigQuery API

---

## Usage Examples

### Check Current Quota Usage

```sql
-- See hourly usage
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

### Get Real-Time Metrics

```python
from shared.utils.pipeline_logger import get_buffer_metrics, flush_event_buffer

# Check current buffer state
metrics = get_buffer_metrics()
print(f"Pending events: {metrics['current_buffer_size']}")
print(f"Total buffered: {metrics['events_buffered_count']}")
print(f"Failed flushes: {metrics['failed_flush_count']}")

# Force flush if needed
if metrics['current_buffer_size'] > 100:
    flush_event_buffer()
```

### Adjust Batch Size

```bash
# Increase batch size to reduce quota usage
export PIPELINE_LOG_BATCH_SIZE=100  # Default: 50
export PIPELINE_LOG_BATCH_TIMEOUT=15.0  # Default: 10.0

# Restart Cloud Functions or Cloud Run services for changes to take effect
```

### Find Top Event Generators

```sql
-- Which processors generate most events?
SELECT
  processor_name,
  COUNT(*) AS event_count,
  COUNT(DISTINCT game_date) AS unique_dates,
  COUNTIF(event_type = 'error') AS errors
FROM nba_orchestration.pipeline_event_log
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY processor_name
ORDER BY event_count DESC
LIMIT 10;
```

---

## Troubleshooting

### Issue: "Quota exceeded" error still occurring

**Diagnosis:**
```sql
-- Check recent partition modifications
SELECT
  hour_timestamp,
  partition_modifications,
  events_logged,
  avg_batch_size
FROM nba_orchestration.quota_usage_hourly
WHERE partition_modifications > 80
ORDER BY hour_timestamp DESC
LIMIT 5;
```

**Solution:**
1. Increase `PIPELINE_LOG_BATCH_SIZE` to 100 or 150
2. Increase `PIPELINE_LOG_BATCH_TIMEOUT` to 15-30 seconds
3. Review top event generators and reduce logging frequency if needed

### Issue: High flush latency

**Diagnosis:**
```python
from shared.utils.pipeline_logger import get_buffer_metrics

metrics = get_buffer_metrics()
if metrics['avg_flush_latency_ms'] > 5000:
    print("High latency detected!")
```

**Solution:**
1. Check BigQuery API status
2. Review batch sizes (may be too large)
3. Check network connectivity to BigQuery
4. Consider regional BigQuery endpoint

### Issue: Failed flushes

**Diagnosis:**
```bash
# Check logs for flush failures
gcloud logging read 'jsonPayload.message=~"Failed to flush"' --limit 20
```

**Solution:**
1. Verify BigQuery permissions
2. Check table schema matches row structure
3. Verify `nba_orchestration.pipeline_event_log` table exists
4. Check BigQuery API quotas

---

## Performance Impact

### Before Metrics (Baseline)

- Batch flushing: 50 events per write
- No visibility into quota usage
- Reactive response to quota errors

### After Metrics (Current)

- **Memory overhead:** ~100 bytes per buffer instance (negligible)
- **CPU overhead:** < 1% (metrics calculation during flush)
- **Log volume:** +1 INFO log per 100 events (minimal)
- **Benefits:**
  - Proactive quota monitoring
  - Historical trend analysis
  - Reduced incident response time

---

## Maintenance

### Daily

- [ ] Check dashboard for anomalies
- [ ] Verify no critical alerts
- [ ] Review flush success rate (should be ~100%)

### Weekly

- [ ] Review quota usage trends
- [ ] Check for processors with increasing event counts
- [ ] Verify scheduled query is running
- [ ] Review alert policy effectiveness

### Monthly

- [ ] Analyze peak usage patterns
- [ ] Adjust alert thresholds if needed
- [ ] Review and optimize batch sizes
- [ ] Archive old quota data (optional)

---

## Future Enhancements

### Potential Improvements

1. **Auto-scaling batch sizes** based on quota usage
2. **Predictive alerts** using ML models
3. **Cost optimization** analysis (BigQuery costs)
4. **Multi-region quota tracking**
5. **Integration with incident management** (PagerDuty, Opsgenie)

### To Implement

1. Add distribution metric for flush latency (percentiles)
2. Track quota usage per processor
3. Create weekly/monthly summary reports
4. Add anomaly detection for sudden spikes

---

## Support & References

### Documentation

- **Full Setup Guide:** `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md`
- **Quick Reference:** `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_quick_reference.md`
- **Code:** `/home/naji/code/nba-stats-scraper/shared/utils/pipeline_logger.py`

### External Resources

- [BigQuery Quotas](https://cloud.google.com/bigquery/quotas)
- [Cloud Monitoring Custom Metrics](https://cloud.google.com/monitoring/custom-metrics)
- [BigQuery Scheduled Queries](https://cloud.google.com/bigquery/docs/scheduling-queries)
- [Log-based Metrics](https://cloud.google.com/logging/docs/logs-based-metrics)

### Testing

```bash
# Run full test suite
cd /home/naji/code/nba-stats-scraper
python3 monitoring/scripts/test_quota_metrics.py --test all

# Run specific tests
python3 monitoring/scripts/test_quota_metrics.py --test basic --events 200
python3 monitoring/scripts/test_quota_metrics.py --test batching
python3 monitoring/scripts/test_quota_metrics.py --test concurrent
```

---

## Success Criteria

✅ **Implemented:**
- [x] Metrics tracked in PipelineEventBuffer
- [x] BigQuery scheduled query for quota tracking
- [x] Cloud Monitoring setup documentation
- [x] Alert policy definitions
- [x] Dashboard configuration
- [x] Setup automation script
- [x] Test suite

✅ **Verified:**
- [x] Metrics API working (`get_buffer_metrics()`)
- [x] Batch flush logging with latency
- [x] SQL query syntax validated
- [x] Dashboard JSON structure valid
- [x] Setup script executes without errors

🎯 **Ready for Deployment:**
- Run setup script in production
- Create log-based metrics in Cloud Console
- Import dashboard
- Verify alert notifications
- Monitor for 24-48 hours

---

**Last Updated:** 2026-01-26
**Task:** #14 - Add quota usage metrics and alerting
**Status:** ✅ Complete
