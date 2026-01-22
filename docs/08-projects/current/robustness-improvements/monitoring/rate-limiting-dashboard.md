# Rate Limiting Monitoring Dashboard

**Part of:** Robustness Improvements - Week 7 Monitoring
**Created:** January 21, 2026
**Purpose:** Monitor rate limit handling, circuit breakers, and API health

---

## Overview

This dashboard monitors the rate limiting system to ensure:
1. 429 errors are being handled correctly
2. Circuit breakers are working as expected
3. Backoff strategies are effective
4. APIs are healthy and responsive

---

## Data Sources

### Primary: Cloud Logging

Rate limit events are logged to Cloud Logging with structured data:

```python
# Example log entry from RateLimitHandler
{
  "severity": "WARNING",
  "message": "Rate limit hit for domain api.balldontlie.io",
  "jsonPayload": {
    "domain": "api.balldontlie.io",
    "retry_after": 60,
    "backoff_seconds": 45.3,
    "attempt": 2,
    "circuit_breaker_status": "closed",
    "component": "rate_limit_handler"
  }
}
```

### Logs-Based Metrics

Create the following log-based metrics in Cloud Logging:

1. **rate_limit_429_count**
   - Filter: `jsonPayload.component="rate_limit_handler" AND severity="WARNING"`
   - Metric type: Counter
   - Labels: domain, phase

2. **circuit_breaker_trips**
   - Filter: `jsonPayload.component="rate_limit_handler" AND textPayload=~"Circuit breaker OPENED"`
   - Metric type: Counter
   - Labels: domain

3. **rate_limit_backoff_duration**
   - Filter: `jsonPayload.component="rate_limit_handler" AND jsonPayload.backoff_seconds!=null`
   - Metric type: Distribution
   - Field: `jsonPayload.backoff_seconds`
   - Labels: domain, attempt

---

## Dashboard Panels

### Panel 1: 429 Error Rate

**Type:** Time Series Chart
**Query:**
```sql
-- Cloud Monitoring MQL
fetch cloud_function
| metric 'logging.googleapis.com/user/rate_limit_429_count'
| group_by 1m, [value_rate_limit_429_count_aggregate: aggregate(value.rate_limit_429_count)]
| every 1m
| group_by [resource.function_name, metric.domain],
    [value_rate_limit_429_count_aggregate_aggregate: aggregate(value_rate_limit_429_count_aggregate)]
```

**Visualization:**
- X-axis: Time (1-hour window)
- Y-axis: 429 errors per minute
- Group by: Domain
- Colors: By domain

**Alert Threshold:** > 10 errors in 5 minutes

---

### Panel 2: Circuit Breaker Status

**Type:** Gauge / Indicator
**Query:**
```sql
fetch cloud_function
| metric 'logging.googleapis.com/user/circuit_breaker_trips'
| group_by 1h, [value_circuit_breaker_trips_aggregate: aggregate(value.circuit_breaker_trips)]
| every 1h
| group_by [metric.domain],
    [value_circuit_breaker_trips_aggregate_max: max(value_circuit_breaker_trips_aggregate)]
```

**Visualization:**
- Show current count of circuit breaker trips per domain
- Color coding:
  - Green: 0 trips
  - Yellow: 1-5 trips
  - Red: > 5 trips

**Alert Threshold:** > 5 trips in 1 hour

---

### Panel 3: Backoff Duration Distribution

**Type:** Heatmap
**Query:**
```sql
fetch cloud_function
| metric 'logging.googleapis.com/user/rate_limit_backoff_duration'
| group_by 5m, [value_rate_limit_backoff_duration_percentile: percentile(value.rate_limit_backoff_duration, 50, 95, 99)]
| every 5m
```

**Visualization:**
- Show P50, P95, P99 backoff times
- Track over time to see if backoffs are increasing (API degradation)

---

### Panel 4: Domain Health Scorecard

**Type:** Table
**Query:**
```sql
-- BigQuery SQL (requires exporting logs to BigQuery)
WITH rate_limit_events AS (
  SELECT
    JSON_EXTRACT_SCALAR(jsonPayload, '$.domain') as domain,
    COUNT(*) as error_count,
    AVG(CAST(JSON_EXTRACT_SCALAR(jsonPayload, '$.backoff_seconds') AS FLOAT64)) as avg_backoff,
    MAX(CAST(JSON_EXTRACT_SCALAR(jsonPayload, '$.backoff_seconds') AS FLOAT64)) as max_backoff,
    MIN(timestamp) as first_error,
    MAX(timestamp) as last_error
  FROM `nba-props-platform.logs.cloudaudit_googleapis_com_data_access_*`
  WHERE
    timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND JSON_EXTRACT_SCALAR(jsonPayload, '$.component') = 'rate_limit_handler'
    AND severity = 'WARNING'
  GROUP BY domain
)
SELECT
  domain,
  error_count,
  ROUND(avg_backoff, 2) as avg_backoff_seconds,
  ROUND(max_backoff, 2) as max_backoff_seconds,
  TIMESTAMP_DIFF(last_error, first_error, MINUTE) as error_duration_minutes,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', last_error) as last_error_time
FROM rate_limit_events
ORDER BY error_count DESC;
```

**Visualization:**
- Table with columns: Domain, Error Count, Avg Backoff, Max Backoff, Last Error
- Conditional formatting:
  - Red: error_count > 100
  - Yellow: error_count > 50
  - Green: error_count < 50

---

### Panel 5: Retry Success Rate

**Type:** Percentage Bar
**Query:**
```sql
-- Calculate success rate after retries
WITH retry_events AS (
  SELECT
    JSON_EXTRACT_SCALAR(jsonPayload, '$.domain') as domain,
    COUNTIF(JSON_EXTRACT_SCALAR(jsonPayload, '$.circuit_breaker_status') = 'closed') as successful_retries,
    COUNTIF(JSON_EXTRACT_SCALAR(jsonPayload, '$.circuit_breaker_status') = 'open') as failed_retries
  FROM `nba-props-platform.logs.cloudaudit_googleapis_com_data_access_*`
  WHERE
    timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
    AND JSON_EXTRACT_SCALAR(jsonPayload, '$.component') = 'rate_limit_handler'
  GROUP BY domain
)
SELECT
  domain,
  successful_retries,
  failed_retries,
  ROUND(SAFE_DIVIDE(successful_retries, successful_retries + failed_retries) * 100, 2) as success_rate_pct
FROM retry_events
ORDER BY success_rate_pct ASC;
```

---

### Panel 6: Time Series - API Response Times

**Type:** Line Chart
**Query:**
```sql
fetch cloud_function
| metric 'cloudfunctions.googleapis.com/function/execution_times'
| group_by 1m, [value_execution_times_percentile: percentile(value.execution_times, 50, 95, 99)]
| every 1m
| group_by [resource.function_name],
    [value_execution_times_percentile_aggregate: aggregate(value_execution_times_percentile)]
```

**Purpose:** Correlate rate limits with increased execution times

---

## Alerts

### Critical Alerts (Page On-Call)

1. **Circuit Breaker Storm**
   ```
   Condition: > 10 circuit breaker trips in 15 minutes across any domain
   Severity: Critical
   Notification: PagerDuty, Slack #alerts
   ```

2. **Sustained Rate Limiting**
   ```
   Condition: > 100 429 errors in 30 minutes for any domain
   Severity: Critical
   Notification: PagerDuty, Slack #alerts
   ```

### Warning Alerts (Slack Only)

3. **Elevated 429 Errors**
   ```
   Condition: > 20 429 errors in 10 minutes
   Severity: Warning
   Notification: Slack #monitoring
   ```

4. **High Backoff Times**
   ```
   Condition: P95 backoff time > 60 seconds for 15 minutes
   Severity: Warning
   Notification: Slack #monitoring
   ```

---

## Dashboard Creation Steps

### Using Cloud Monitoring (Google Cloud Console)

1. **Navigate to Monitoring → Dashboards**

2. **Create New Dashboard:** "NBA Pipeline - Rate Limiting"

3. **Add Metrics:**
   - Use MQL queries above for each panel
   - Configure time windows (default: Last 6 hours)
   - Set auto-refresh: 1 minute

4. **Configure Alerts:**
   - Go to Monitoring → Alerting
   - Create policies for each alert defined above
   - Configure notification channels (Slack, PagerDuty)

### Using Terraform (Infrastructure as Code)

```hcl
# monitoring/dashboards/rate_limiting_dashboard.tf

resource "google_monitoring_dashboard" "rate_limiting" {
  dashboard_json = file("${path.module}/dashboards/rate_limiting_dashboard.json")
  project        = var.project_id
}

resource "google_monitoring_alert_policy" "circuit_breaker_storm" {
  display_name = "Circuit Breaker Storm"
  project      = var.project_id

  conditions {
    display_name = "Circuit breaker trips > 10 in 15m"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/circuit_breaker_trips\""
      duration        = "900s"
      comparison      = "COMPARISON_GT"
      threshold_value = 10

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.pagerduty.id,
    google_monitoring_notification_channel.slack_alerts.id
  ]

  alert_strategy {
    auto_close = "1800s"
  }
}
```

---

## Usage Guide

### Daily Monitoring Checklist

**Morning Check (9:00 AM ET):**
1. Check 429 error count for last 24 hours
2. Verify no circuit breaker trips overnight
3. Review domain health scorecard
4. Check for any active alerts

**Incident Response:**
1. Check Circuit Breaker Status panel
2. Identify affected domain(s)
3. Review backoff duration - if increasing, API may be degrading
4. Check API status pages:
   - BallDontLie: https://www.balldontlie.io/status
   - NBA.com: Check manually
   - Odds API: https://the-odds-api.com/status

**Weekly Review (Monday):**
1. Review 7-day trend of 429 errors
2. Identify domains with recurring issues
3. Adjust rate limit thresholds if needed
4. Review alert noise - tune thresholds

---

## Query Examples

### Find top domains by 429 errors (last 7 days)

```sql
SELECT
  JSON_EXTRACT_SCALAR(jsonPayload, '$.domain') as domain,
  COUNT(*) as error_count,
  AVG(CAST(JSON_EXTRACT_SCALAR(jsonPayload, '$.backoff_seconds') AS FLOAT64)) as avg_backoff
FROM `nba-props-platform.logs.cloudaudit_googleapis_com_data_access_*`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND JSON_EXTRACT_SCALAR(jsonPayload, '$.component') = 'rate_limit_handler'
  AND severity >= 'WARNING'
GROUP BY domain
ORDER BY error_count DESC
LIMIT 10;
```

### Circuit breaker events timeline

```sql
SELECT
  timestamp,
  JSON_EXTRACT_SCALAR(jsonPayload, '$.domain') as domain,
  textPayload as message
FROM `nba-props-platform.logs.cloudaudit_googleapis_com_data_access_*`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND textPayload LIKE '%Circuit breaker%'
ORDER BY timestamp DESC;
```

### Retry success analysis

```sql
WITH attempts AS (
  SELECT
    JSON_EXTRACT_SCALAR(jsonPayload, '$.domain') as domain,
    CAST(JSON_EXTRACT_SCALAR(jsonPayload, '$.attempt') AS INT64) as attempt,
    JSON_EXTRACT_SCALAR(jsonPayload, '$.circuit_breaker_status') as cb_status
  FROM `nba-props-platform.logs.cloudaudit_googleapis_com_data_access_*`
  WHERE
    timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND JSON_EXTRACT_SCALAR(jsonPayload, '$.component') = 'rate_limit_handler'
)
SELECT
  domain,
  attempt,
  COUNT(*) as count,
  COUNTIF(cb_status = 'open') as circuit_open_count,
  ROUND(SAFE_DIVIDE(COUNTIF(cb_status = 'open'), COUNT(*)) * 100, 2) as circuit_open_pct
FROM attempts
GROUP BY domain, attempt
ORDER BY domain, attempt;
```

---

## Metrics Glossary

- **429 Error Rate:** Number of HTTP 429 (Too Many Requests) responses per minute
- **Circuit Breaker Trip:** Event where circuit breaker opens due to consecutive failures
- **Backoff Duration:** Time to wait before retrying after rate limit
- **Retry Success Rate:** Percentage of retries that succeed vs fail
- **Domain Health Score:** Composite score based on error rate, backoff times, and circuit breaker status

---

## Related Dashboards

- **Phase Validation Dashboard:** Monitor validation gate metrics
- **Pipeline Health Dashboard:** Overall pipeline status
- **API Latency Dashboard:** Track external API response times

---

## Maintenance

**Update Frequency:** Review and update dashboard quarterly
**Owner:** Data Engineering Team
**Last Updated:** January 21, 2026
**Next Review:** April 21, 2026
