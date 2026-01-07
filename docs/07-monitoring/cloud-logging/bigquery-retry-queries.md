# BigQuery Retry Metrics - Cloud Logging Queries

**Purpose**: Query structured retry logs from Cloud Logging to monitor BigQuery serialization conflict patterns.

**Context**: The enhanced `bigquery_retry.py` module logs structured events to Cloud Logging with the following event types:
- `bigquery_serialization_conflict` - When a conflict is detected (before retry)
- `bigquery_retry_success` - When operation completes successfully (may have retried)
- `bigquery_retry_exhausted` - When retries are exhausted (operation failed)
- `bigquery_operation_failed` - Non-retryable error

---

## Quick Start

### 1. View All Retry Events (Last 24 Hours)

```bash
gcloud logging read 'jsonPayload.event_type=~"bigquery_.*"' \
  --limit=100 \
  --freshness=24h \
  --format=json
```

### 2. Count Conflicts by Event Type (Last 24 Hours)

```bash
gcloud logging read 'jsonPayload.event_type=~"bigquery_.*"' \
  --limit=1000 \
  --freshness=24h \
  --format=json | \
  jq -r '.[] | .jsonPayload.event_type' | sort | uniq -c
```

**Expected Output:**
```
  12 bigquery_serialization_conflict
  10 bigquery_retry_success
   2 bigquery_retry_exhausted
```

### 3. Extract Table Names from Conflicts

```bash
gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=50 \
  --freshness=24h \
  --format=json | \
  jq -r '.[] | "\(.timestamp) - Table: \(.jsonPayload.table_name)"'
```

---

## Monitoring Queries

### Success Rate Calculation

```bash
# Count conflicts vs successes
CONFLICTS=$(gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=1000 --freshness=24h --format=json | jq -s 'length')

SUCCESSES=$(gcloud logging read 'jsonPayload.event_type="bigquery_retry_success"' \
  --limit=1000 --freshness=24h --format=json | jq -s 'length')

echo "Conflicts: $CONFLICTS"
echo "Successes: $SUCCESSES"
echo "Success Rate: $(echo "scale=2; $SUCCESSES * 100 / $CONFLICTS" | bc)%"
```

### Tables with Most Conflicts

```bash
gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=500 \
  --freshness=7d \
  --format=json | \
  jq -r '.[] | .jsonPayload.table_name' | \
  sort | uniq -c | sort -rn | head -10
```

**Example Output:**
```
  45 nba_raw.br_rosters_current
  23 nba_raw.odds_game_lines
  12 nba_analytics.daily_stats
```

### Recent Retry Exhaustions (Failures)

```bash
gcloud logging read 'jsonPayload.event_type="bigquery_retry_exhausted"' \
  --limit=20 \
  --freshness=24h \
  --format=json | \
  jq -r '.[] | "\(.timestamp) - \(.jsonPayload.table_name) - \(.jsonPayload.error_message[:100])"'
```

### Retry Duration Analysis

```bash
# Average duration for operations with retries
gcloud logging read 'jsonPayload.event_type="bigquery_retry_success"' \
  --limit=200 \
  --freshness=24h \
  --format=json | \
  jq -r '.[] | .jsonPayload.duration_ms' | \
  awk '{sum+=$1; count++} END {print "Average duration: " sum/count "ms"}'
```

---

## Detailed Analytics Queries

### 1. Hourly Conflict Pattern (Last 7 Days)

```bash
gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=5000 \
  --freshness=7d \
  --format=json | \
  jq -r '.[] | .timestamp' | \
  cut -d'T' -f2 | cut -d':' -f1 | sort | uniq -c | sort -k2n
```

**Output shows conflicts by hour UTC:**
```
  12 00
  15 01
  45 02  ← Peak time (morning pipeline runs)
   8 03
   ...
```

### 2. Conflicts by Function Name

```bash
gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=500 \
  --freshness=7d \
  --format=json | \
  jq -r '.[] | .jsonPayload.function_name // "unknown"' | \
  sort | uniq -c | sort -rn
```

### 3. Success vs Exhaustion Rate by Table

```bash
#!/bin/bash
# Save as: analyze_retry_success_by_table.sh

TABLES=$(gcloud logging read 'jsonPayload.event_type=~"bigquery_.*"' \
  --limit=1000 --freshness=7d --format=json | \
  jq -r '.[] | .jsonPayload.table_name' | sort -u)

echo "Table Name | Conflicts | Successes | Exhausted | Success Rate"
echo "-----------|-----------|-----------|-----------|-------------"

for table in $TABLES; do
  if [ -n "$table" ] && [ "$table" != "null" ]; then
    CONFLICTS=$(gcloud logging read "jsonPayload.event_type=\"bigquery_serialization_conflict\" AND jsonPayload.table_name=\"$table\"" \
      --limit=1000 --freshness=7d --format=json | jq -s 'length')

    SUCCESSES=$(gcloud logging read "jsonPayload.event_type=\"bigquery_retry_success\" AND jsonPayload.table_name=\"$table\"" \
      --limit=1000 --freshness=7d --format=json | jq -s 'length')

    EXHAUSTED=$(gcloud logging read "jsonPayload.event_type=\"bigquery_retry_exhausted\" AND jsonPayload.table_name=\"$table\"" \
      --limit=1000 --freshness=7d --format=json | jq -s 'length')

    if [ "$CONFLICTS" -gt 0 ]; then
      RATE=$(echo "scale=1; $SUCCESSES * 100 / $CONFLICTS" | bc)
      echo "$table | $CONFLICTS | $SUCCESSES | $EXHAUSTED | $RATE%"
    fi
  fi
done
```

---

## Monitoring Dashboard Queries

### Daily Health Check (Run Each Morning)

```bash
#!/bin/bash
# Check BigQuery retry health for last 24 hours

echo "=== BigQuery Retry Health Check ==="
echo "Period: Last 24 hours"
echo ""

# Count events
CONFLICTS=$(gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=1000 --freshness=24h --format=json | jq -s 'length')

SUCCESSES=$(gcloud logging read 'jsonPayload.event_type="bigquery_retry_success"' \
  --limit=1000 --freshness=24h --format=json | jq -s 'length')

EXHAUSTED=$(gcloud logging read 'jsonPayload.event_type="bigquery_retry_exhausted"' \
  --limit=1000 --freshness=24h --format=json | jq -s 'length')

echo "Conflicts detected: $CONFLICTS"
echo "Operations succeeded: $SUCCESSES"
echo "Retries exhausted: $EXHAUSTED"
echo ""

if [ "$CONFLICTS" -gt 0 ]; then
  SUCCESS_RATE=$(echo "scale=1; $SUCCESSES * 100 / $CONFLICTS" | bc)
  echo "Success Rate: $SUCCESS_RATE%"

  if (( $(echo "$SUCCESS_RATE < 80" | bc -l) )); then
    echo "⚠️  WARNING: Success rate below 80% - investigate retry failures"
  elif (( $(echo "$SUCCESS_RATE >= 95" | bc -l) )); then
    echo "✅ EXCELLENT: Success rate >= 95% - retry logic working well"
  else
    echo "✅ GOOD: Success rate acceptable"
  fi
else
  echo "✅ PERFECT: No conflicts detected in last 24 hours"
fi

echo ""
echo "Top 5 tables with conflicts:"
gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=1000 --freshness=24h --format=json | \
  jq -r '.[] | .jsonPayload.table_name' | \
  sort | uniq -c | sort -rn | head -5
```

---

## Alert Conditions

### Alert 1: Low Success Rate (< 80%)

```bash
# Run hourly via cron
SUCCESS_RATE=$(./scripts/calculate_retry_success_rate.sh)

if (( $(echo "$SUCCESS_RATE < 80" | bc -l) )); then
  # Send alert
  echo "ALERT: BigQuery retry success rate dropped to $SUCCESS_RATE%"
  # Trigger email/PagerDuty/Slack notification
fi
```

### Alert 2: High Conflict Volume (> 50/hour)

```bash
CONFLICTS_LAST_HOUR=$(gcloud logging read 'jsonPayload.event_type="bigquery_serialization_conflict"' \
  --limit=1000 --freshness=1h --format=json | jq -s 'length')

if [ "$CONFLICTS_LAST_HOUR" -gt 50 ]; then
  echo "ALERT: $CONFLICTS_LAST_HOUR conflicts in last hour (threshold: 50)"
fi
```

### Alert 3: Retry Exhaustion Detected

```bash
EXHAUSTED=$(gcloud logging read 'jsonPayload.event_type="bigquery_retry_exhausted"' \
  --limit=100 --freshness=1h --format=json | jq -s 'length')

if [ "$EXHAUSTED" -gt 0 ]; then
  echo "ALERT: $EXHAUSTED retry exhaustions in last hour - review logs"
  gcloud logging read 'jsonPayload.event_type="bigquery_retry_exhausted"' \
    --limit=10 --freshness=1h --format=json | \
    jq -r '.[] | "\(.timestamp) - \(.jsonPayload.table_name)"'
fi
```

---

## Exporting to BigQuery (Optional)

To enable long-term analytics and complex queries, export Cloud Logging to BigQuery:

### 1. Create Log Sink

```bash
gcloud logging sinks create bigquery-retry-metrics \
  bigquery.googleapis.com/projects/nba-props-platform/datasets/nba_orchestration \
  --log-filter='jsonPayload.event_type=~"bigquery_.*"' \
  --description="Export BigQuery retry metrics to BigQuery for analytics"
```

### 2. Grant Sink Permissions

```bash
# Get the sink's service account
SINK_SA=$(gcloud logging sinks describe bigquery-retry-metrics --format='value(writerIdentity)')

# Grant BigQuery Data Editor role
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="$SINK_SA" \
  --role="roles/bigquery.dataEditor"
```

### 3. Verify Export

```bash
# Wait a few minutes, then check if data is flowing
bq query --use_legacy_sql=false "
SELECT
  timestamp,
  jsonPayload.event_type as event_type,
  jsonPayload.table_name as table_name
FROM \`nba-props-platform.nba_orchestration.cloudaudit_googleapis_com_activity_*\`
WHERE jsonPayload.event_type IS NOT NULL
ORDER BY timestamp DESC
LIMIT 10
"
```

---

## Troubleshooting

### No Logs Found

```bash
# Check if structured logging is working
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=10 --freshness=1h --format=json | \
  jq '.[] | {timestamp, message: .textPayload, json: .jsonPayload}'
```

### Verify Structured Fields

```bash
# List all jsonPayload fields being logged
gcloud logging read 'jsonPayload.event_type=~"bigquery_.*"' \
  --limit=10 --freshness=24h --format=json | \
  jq -r '.[0].jsonPayload | keys[]'
```

**Expected fields:**
```
event_type
table_name
error_message
timestamp
retry_triggered
function_name
duration_ms
```

---

## Performance Notes

- Cloud Logging queries are limited to ~1000 results by default
- Use `--limit` to increase (max: depends on quota)
- For large-scale analytics (> 7 days, > 10,000 events), export to BigQuery
- Cloud Logging retention: 30 days (default)

---

## Next Steps

1. **Week 1**: Monitor Cloud Logging queries to validate retry logic
2. **Week 2**: Analyze patterns and success rates
3. **Week 3**: If needed, set up automatic BigQuery export for long-term storage
4. **Week 4**: Build monitoring dashboards based on data patterns

For BigQuery analytics queries, see: `sql/orchestration/bigquery_retry_analytics.sql`
