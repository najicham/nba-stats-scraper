# Pipeline Quota Usage Monitoring Setup Guide

## Overview

This guide documents how to set up comprehensive monitoring and alerting for BigQuery quota usage to prevent "403 Quota exceeded: partition modifications" errors that can halt pipeline operations.

**Last Updated:** 2026-01-26
**Component:** Pipeline Event Logger
**Related Files:**
- `/home/naji/code/nba-stats-scraper/shared/utils/pipeline_logger.py`
- `/home/naji/code/nba-stats-scraper/monitoring/queries/quota_usage_tracking.sql`

---

## Architecture

### Metrics Collection Strategy

1. **Application-Level Metrics** (Python code)
   - Real-time tracking in `PipelineEventBuffer` class
   - Logged to application logs at INFO level
   - Available via `get_buffer_metrics()` API

2. **BigQuery Query Metrics** (SQL)
   - Hourly scheduled query analyzes `pipeline_event_log` table
   - Calculates partition modifications, batch sizes, event counts
   - Stores results in `quota_usage_hourly` table

3. **Cloud Monitoring Metrics** (GCP Console)
   - Custom metrics exported from logs
   - Dashboards and alert policies
   - Integration with notification channels

---

## Part 1: Application-Level Metrics

### Metrics Tracked by PipelineEventBuffer

The `PipelineEventBuffer` class in `pipeline_logger.py` tracks:

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|-----------------|
| `events_buffered_count` | Counter | Total events buffered since process start | N/A (informational) |
| `batch_flush_count` | Counter | Number of successful batch flushes | N/A (informational) |
| `failed_flush_count` | Counter | Number of failed flush attempts | > 0 (WARN), > 5 (CRITICAL) |
| `avg_flush_latency_ms` | Gauge | Average time to flush a batch to BigQuery | > 5000ms (WARN) |
| `avg_batch_size` | Gauge | Average events per batch | < 20 (WARN - inefficient batching) |
| `current_buffer_size` | Gauge | Current number of pending events | > 100 (WARN - backlog building) |

### Accessing Metrics

```python
from shared.utils.pipeline_logger import get_buffer_metrics

# Get current metrics
metrics = get_buffer_metrics()
print(f"Events buffered: {metrics['events_buffered_count']}")
print(f"Failed flushes: {metrics['failed_flush_count']}")
print(f"Avg batch size: {metrics['avg_batch_size']}")
print(f"Avg flush latency: {metrics['avg_flush_latency_ms']}ms")
```

### Metric Logging

Metrics are automatically logged every 100 events at INFO level:

```
Pipeline Event Buffer Metrics: events_buffered=500, batch_flushes=10, failed_flushes=0, avg_batch_size=50.0, avg_flush_latency=234.56ms, current_buffer_size=0
```

---

## Part 2: BigQuery Scheduled Query

### Setup Instructions

#### Step 1: Create Destination Table

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.quota_usage_hourly (
  hour_timestamp TIMESTAMP,
  partition_modifications INT64,
  events_logged INT64,
  avg_batch_size FLOAT64,
  failed_flushes INT64,
  unique_processors INT64,
  unique_game_dates INT64,
  error_events INT64
)
PARTITION BY DATE(hour_timestamp)
OPTIONS(
  description='Hourly quota usage tracking for pipeline event logging',
  labels=[('purpose', 'monitoring'), ('component', 'pipeline_logger')]
);
```

#### Step 2: Create Scheduled Query

**Option A: Using Cloud Console**

1. Navigate to: BigQuery > Scheduled Queries > Create Scheduled Query
2. Configuration:
   - **Name:** Pipeline Quota Usage Tracking
   - **Schedule:** Every 1 hours
   - **Query:** Contents of `monitoring/queries/quota_usage_tracking.sql`
   - **Destination:**
     - Dataset: `nba_orchestration`
     - Table: `quota_usage_hourly`
   - **Write preference:** Append to table

**Option B: Using bq CLI**

```bash
bq mk --transfer_config \
  --project_id=<YOUR_PROJECT_ID> \
  --data_source=scheduled_query \
  --schedule='every 1 hours' \
  --display_name='Pipeline Quota Usage Tracking' \
  --target_dataset=nba_orchestration \
  --params='{
    "query": "<QUERY_FROM_FILE>",
    "destination_table_name_template": "quota_usage_hourly",
    "write_disposition": "WRITE_APPEND",
    "partitioning_type": "DAY"
  }'
```

### Key Metrics Calculated

1. **Partition Modifications**: Estimated based on event count and batch size (50)
2. **Events Logged**: Total pipeline events in the hour
3. **Avg Batch Size**: Efficiency metric (higher = fewer partition mods)
4. **Unique Processors**: Cardinality of processors active
5. **Unique Game Dates**: Cardinality of dates processed
6. **Error Events**: Count of error-type events

### Query Usage Examples

```sql
-- Check current hour's quota usage
SELECT * FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp = TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), HOUR);

-- Find hours approaching quota limit (100 mods/hour)
SELECT
  hour_timestamp,
  partition_modifications,
  ROUND(partition_modifications / 100.0 * 100, 1) AS quota_usage_pct
FROM nba_orchestration.quota_usage_hourly
WHERE partition_modifications > 80
ORDER BY hour_timestamp DESC;

-- 7-day trend analysis
SELECT
  DATE(hour_timestamp) AS date,
  AVG(partition_modifications) AS avg_hourly_mods,
  MAX(partition_modifications) AS peak_hourly_mods,
  SUM(events_logged) AS total_daily_events
FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date
ORDER BY date DESC;
```

---

## Part 3: Cloud Monitoring Setup

### Creating Custom Metrics (Log-Based Metrics)

#### Metric 1: Pipeline Events Buffered

1. **Navigate to:** Cloud Console > Logging > Logs-based metrics
2. **Click:** Create Metric
3. **Configuration:**
   - **Metric Type:** Counter
   - **Name:** `pipeline/events_buffered`
   - **Description:** Total pipeline events buffered for batch write
   - **Filter:**
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Pipeline Event Buffer Metrics"
     ```
   - **Labels:**
     - `phase`: `jsonPayload.phase`
     - `processor`: `jsonPayload.processor_name`

#### Metric 2: Batch Flush Count

1. **Configuration:**
   - **Metric Type:** Counter
   - **Name:** `pipeline/batch_flushes`
   - **Description:** Number of batch flushes to BigQuery
   - **Filter:**
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Flushed .* events to"
     severity="INFO"
     ```

#### Metric 3: Flush Latency

1. **Configuration:**
   - **Metric Type:** Distribution
   - **Name:** `pipeline/flush_latency_ms`
   - **Description:** Time taken to flush batch to BigQuery (milliseconds)
   - **Filter:**
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Flushed .* events to"
     ```
   - **Value Field:** Extract from log message: `latency: (\d+\.?\d*)ms`

#### Metric 4: Flush Failures

1. **Configuration:**
   - **Metric Type:** Counter
   - **Name:** `pipeline/flush_failures`
   - **Description:** Number of failed batch flush attempts
   - **Filter:**
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Failed to flush .* events"
     severity="WARNING"
     ```

---

## Part 4: Alert Policies

### Alert Policy 1: High Quota Usage (WARN)

**Condition:** Partition modifications > 80/hour (80% of 100 limit)

```yaml
Display Name: Pipeline Quota Usage Warning
Condition Type: Metric Threshold
Metric: custom.googleapis.com/bigquery/partition_modifications
Filter: resource.type="bigquery_table" AND resource.table_id="pipeline_event_log"
Threshold: 80
Duration: 5 minutes
Comparison: COMPARISON_GT
Notification Channels: [email, slack]
Documentation:
  "Pipeline event logging is approaching BigQuery partition modification quota.
   Current usage: ${metric.value} modifications/hour (limit: 100).

   Action: Monitor closely. If this persists, consider:
   1. Increasing BATCH_SIZE (currently 50)
   2. Increasing BATCH_TIMEOUT_SECONDS
   3. Reducing event logging frequency

   Query to investigate:
   SELECT * FROM nba_orchestration.quota_usage_hourly
   WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
   ORDER BY partition_modifications DESC;"
```

### Alert Policy 2: Quota Exceeded (CRITICAL)

**Condition:** Partition modifications > 90/hour (90% of 100 limit)

```yaml
Display Name: Pipeline Quota Usage CRITICAL
Condition Type: Metric Threshold
Metric: custom.googleapis.com/bigquery/partition_modifications
Filter: resource.type="bigquery_table" AND resource.table_id="pipeline_event_log"
Threshold: 90
Duration: 1 minute
Comparison: COMPARISON_GT
Notification Channels: [pagerduty, email, slack]
Auto Close Duration: 30 minutes
Documentation:
  "CRITICAL: Pipeline event logging quota nearly exceeded!
   Current usage: ${metric.value} modifications/hour (limit: 100).

   IMMEDIATE ACTIONS:
   1. Increase BATCH_SIZE environment variable to 100
   2. Check for event logging loops or excessive retries
   3. Temporarily disable non-critical event logging

   Investigation queries:
   -- Find processors generating most events
   SELECT processor_name, COUNT(*) as event_count
   FROM nba_orchestration.pipeline_event_log
   WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
   GROUP BY processor_name
   ORDER BY event_count DESC
   LIMIT 10;"
```

### Alert Policy 3: Failed Batch Flushes

**Condition:** Failed flush count > 0

```yaml
Display Name: Pipeline Event Buffer Flush Failures
Condition Type: Metric Threshold
Metric: custom.googleapis.com/pipeline/flush_failures
Filter: resource.type="cloud_function"
Threshold: 0
Duration: 5 minutes
Comparison: COMPARISON_GT
Notification Channels: [email, slack]
Documentation:
  "Pipeline event buffer is experiencing flush failures.
   Failed flushes: ${metric.value}

   This means events are not being written to BigQuery for audit logging.

   Possible causes:
   1. BigQuery API rate limiting
   2. Permission issues
   3. Network connectivity
   4. BigQuery table schema mismatch

   Check logs for details:
   gcloud logging read 'jsonPayload.message=~\"Failed to flush\"' --limit 50"
```

### Alert Policy 4: High Flush Latency

**Condition:** Average flush latency > 5000ms

```yaml
Display Name: Pipeline Event Buffer High Latency
Condition Type: Metric Threshold
Metric: custom.googleapis.com/pipeline/flush_latency_ms
Aggregation: ALIGN_MEAN (1m)
Filter: resource.type="cloud_function"
Threshold: 5000
Duration: 10 minutes
Comparison: COMPARISON_GT
Notification Channels: [email]
Documentation:
  "Pipeline event buffer flush latency is high.
   Current latency: ${metric.value}ms

   High latency can cause buffer backlog and eventual quota issues.

   Investigation steps:
   1. Check BigQuery API status
   2. Review batch sizes (may be too large)
   3. Check network connectivity to BigQuery
   4. Review concurrent flush attempts"
```

---

## Part 5: Dashboard Configuration

### Creating Dashboard in Cloud Monitoring

1. **Navigate to:** Cloud Console > Monitoring > Dashboards
2. **Create Dashboard:** Pipeline Quota Monitoring
3. **Add Charts:**

#### Chart 1: Partition Modifications (Hourly)

```json
{
  "displayName": "Partition Modifications per Hour",
  "xyChart": {
    "dataSets": [{
      "timeSeriesQuery": {
        "timeSeriesFilter": {
          "filter": "resource.type=\"bigquery_table\" resource.table_id=\"pipeline_event_log\"",
          "aggregation": {
            "perSeriesAligner": "ALIGN_SUM",
            "alignmentPeriod": "3600s"
          }
        }
      },
      "plotType": "LINE",
      "targetAxis": "Y1"
    }],
    "timeshiftDuration": "0s",
    "yAxis": {
      "label": "Partition Modifications",
      "scale": "LINEAR"
    },
    "thresholds": [
      {"value": 80, "color": "YELLOW", "label": "Warning"},
      {"value": 90, "color": "RED", "label": "Critical"}
    ]
  }
}
```

#### Chart 2: Events Buffered per Minute

```json
{
  "displayName": "Pipeline Events Buffered",
  "xyChart": {
    "dataSets": [{
      "timeSeriesQuery": {
        "timeSeriesFilter": {
          "filter": "metric.type=\"custom.googleapis.com/pipeline/events_buffered\"",
          "aggregation": {
            "perSeriesAligner": "ALIGN_RATE",
            "alignmentPeriod": "60s"
          }
        }
      },
      "plotType": "LINE"
    }]
  }
}
```

#### Chart 3: Flush Success Rate

```json
{
  "displayName": "Batch Flush Success Rate",
  "scorecard": {
    "timeSeriesQuery": {
      "timeSeriesFilter": {
        "filter": "metric.type=\"custom.googleapis.com/pipeline/batch_flushes\"",
        "aggregation": {
          "perSeriesAligner": "ALIGN_RATE",
          "alignmentPeriod": "300s"
        }
      }
    },
    "gaugeView": {
      "lowerBound": 0,
      "upperBound": 10
    }
  }
}
```

#### Chart 4: Average Flush Latency

```json
{
  "displayName": "Average Flush Latency (ms)",
  "xyChart": {
    "dataSets": [{
      "timeSeriesQuery": {
        "timeSeriesFilter": {
          "filter": "metric.type=\"custom.googleapis.com/pipeline/flush_latency_ms\"",
          "aggregation": {
            "perSeriesAligner": "ALIGN_MEAN",
            "alignmentPeriod": "60s"
          }
        }
      },
      "plotType": "LINE"
    }],
    "thresholds": [
      {"value": 1000, "color": "YELLOW"},
      {"value": 5000, "color": "RED"}
    ]
  }
}
```

### Example Dashboard JSON

See: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`

---

## Part 6: Setting Up Alert Policies via gcloud CLI

```bash
#!/bin/bash
# Script to create all alert policies for pipeline quota monitoring

PROJECT_ID="your-gcp-project-id"
NOTIFICATION_CHANNEL_EMAIL="your-channel-id"  # Get from: gcloud alpha monitoring channels list

# Alert 1: High Quota Usage (WARN)
gcloud alpha monitoring policies create \
  --project="${PROJECT_ID}" \
  --notification-channels="${NOTIFICATION_CHANNEL_EMAIL}" \
  --display-name="Pipeline Quota Usage Warning" \
  --condition-display-name="Partition mods > 80/hour" \
  --condition-threshold-value=80 \
  --condition-threshold-duration=300s \
  --condition-metric="custom.googleapis.com/bigquery/partition_modifications" \
  --condition-filter='resource.type="bigquery_table" AND resource.table_id="pipeline_event_log"' \
  --documentation-content="Pipeline approaching quota limit. See monitoring/docs/quota_monitoring_setup.md"

# Alert 2: Quota Exceeded (CRITICAL)
gcloud alpha monitoring policies create \
  --project="${PROJECT_ID}" \
  --notification-channels="${NOTIFICATION_CHANNEL_EMAIL}" \
  --display-name="Pipeline Quota Usage CRITICAL" \
  --condition-display-name="Partition mods > 90/hour" \
  --condition-threshold-value=90 \
  --condition-threshold-duration=60s \
  --condition-metric="custom.googleapis.com/bigquery/partition_modifications" \
  --condition-filter='resource.type="bigquery_table" AND resource.table_id="pipeline_event_log"' \
  --documentation-content="CRITICAL quota alert. Immediate action required."

# Alert 3: Failed Flushes
gcloud alpha monitoring policies create \
  --project="${PROJECT_ID}" \
  --notification-channels="${NOTIFICATION_CHANNEL_EMAIL}" \
  --display-name="Pipeline Event Buffer Flush Failures" \
  --condition-display-name="Flush failures > 0" \
  --condition-threshold-value=0 \
  --condition-threshold-duration=300s \
  --condition-metric="custom.googleapis.com/pipeline/flush_failures" \
  --condition-filter='resource.type="cloud_function"'

echo "Alert policies created successfully!"
```

---

## Part 7: Testing and Validation

### Test 1: Verify Metrics Collection

```python
# In a Cloud Function or script
from shared.utils.pipeline_logger import log_pipeline_event, PipelineEventType, get_buffer_metrics

# Generate test events
for i in range(100):
    log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_START,
        phase='test',
        processor_name='test_processor',
        game_date='2026-01-26'
    )

# Check metrics
metrics = get_buffer_metrics()
assert metrics['events_buffered_count'] == 100
assert metrics['batch_flush_count'] > 0
print(f"Test passed! Metrics: {metrics}")
```

### Test 2: Verify Scheduled Query

```sql
-- Check if query ran successfully
SELECT *
FROM nba_orchestration.quota_usage_hourly
WHERE hour_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY hour_timestamp DESC;

-- Should return 1-2 rows with recent data
```

### Test 3: Trigger Test Alert

```python
# Generate enough events to trigger warning alert
from shared.utils.pipeline_logger import log_pipeline_event, PipelineEventType

# Generate 4000 events (will create ~80 partition mods if batch_size=50)
for i in range(4000):
    log_pipeline_event(
        event_type=PipelineEventType.PROCESSOR_START,
        phase='load_test',
        processor_name='test_processor',
        game_date='2026-01-26'
    )

# Wait 5-10 minutes and check for alert notification
```

---

## Troubleshooting

### Issue: Metrics not appearing in Cloud Monitoring

**Cause:** Log-based metrics not created or filter incorrect

**Solution:**
1. Verify logs exist: `gcloud logging read 'jsonPayload.message=~"Pipeline Event Buffer Metrics"' --limit 10`
2. Check metric filters in Cloud Console > Logging > Logs-based metrics
3. Wait up to 5 minutes for metrics to propagate

### Issue: Scheduled query not running

**Cause:** Permissions or query syntax error

**Solution:**
1. Check transfer config: `bq ls --transfer_config --transfer_location=US`
2. View run history: `bq ls --transfer_run --transfer_config=<CONFIG_ID>`
3. Check service account permissions: `bigquery.dataEditor`, `bigquery.jobUser`

### Issue: False positive alerts

**Cause:** Threshold too low or incorrect filter

**Solution:**
1. Review alert policy conditions in Cloud Console
2. Adjust threshold values based on actual usage patterns
3. Add longer duration requirements to reduce noise

---

## Maintenance

### Weekly Tasks

- Review quota usage trends
- Check for anomalies in partition modifications
- Verify alert policies are firing correctly
- Review and archive old `quota_usage_hourly` data (optional)

### Monthly Tasks

- Review and adjust alert thresholds
- Analyze peak usage patterns
- Optimize batch sizes if needed
- Update documentation with new findings

---

## References

- [BigQuery Quotas Documentation](https://cloud.google.com/bigquery/quotas)
- [Cloud Monitoring Custom Metrics](https://cloud.google.com/monitoring/custom-metrics)
- [BigQuery Scheduled Queries](https://cloud.google.com/bigquery/docs/scheduling-queries)
- Pipeline Logger Code: `/home/naji/code/nba-stats-scraper/shared/utils/pipeline_logger.py`
