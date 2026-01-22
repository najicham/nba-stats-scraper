# Proxy Health Monitoring Setup

**Last Updated:** 2026-01-22

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Scraper Base   │────▶│ proxy_health_    │────▶│   BigQuery      │
│  (proxy calls)  │     │ logger.py        │     │   Metrics       │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                         │
                                                         ▼
                                                 ┌─────────────────┐
                                                 │  Summary View   │
                                                 │  (daily stats)  │
                                                 └─────────────────┘
                                                         │
                                                         ▼
                                                 ┌─────────────────┐
                                                 │  Alerting       │
                                                 │  (threshold)    │
                                                 └─────────────────┘
```

## BigQuery Schema

### Table: `nba_orchestration.proxy_health_metrics`

| Column | Type | Description |
|--------|------|-------------|
| timestamp | TIMESTAMP | When the request was made |
| scraper_name | STRING | Scraper class name |
| target_host | STRING | Target hostname (e.g., api.bettingpros.com) |
| proxy_provider | STRING | Provider name (default: proxyfuel) |
| http_status_code | INT64 | HTTP response code |
| response_time_ms | INT64 | Response time in milliseconds |
| success | BOOL | Whether request succeeded |
| error_type | STRING | Classified error type |
| error_message | STRING | Detailed error message |
| proxy_ip | STRING | Proxy IP used (if available) |

**Partitioning:** By `DATE(timestamp)`
**Clustering:** By `scraper_name`, `target_host`

### View: `nba_orchestration.proxy_health_summary`

Aggregates metrics by day and target host:
- Total requests
- Success/failure counts
- Success rate percentage
- Error type breakdown (403s, timeouts, etc.)
- Response time stats

## Queries

### Check Current Proxy Health (Last 24 Hours)

```sql
SELECT
  target_host,
  COUNT(*) as total,
  COUNTIF(success) as successful,
  ROUND(COUNTIF(success) * 100.0 / COUNT(*), 1) as success_rate,
  COUNTIF(http_status_code = 403) as forbidden_403,
  COUNTIF(error_type = 'timeout') as timeouts
FROM nba_orchestration.proxy_health_metrics
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY target_host
ORDER BY total DESC;
```

### Hourly Failure Trend

```sql
SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) as hour,
  target_host,
  COUNT(*) as requests,
  COUNTIF(NOT success) as failures,
  ROUND(COUNTIF(NOT success) * 100.0 / COUNT(*), 1) as failure_rate
FROM nba_orchestration.proxy_health_metrics
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
GROUP BY hour, target_host
HAVING failures > 0
ORDER BY hour DESC, failures DESC;
```

### Detect Sudden Failure Spike

```sql
-- Alert if failure rate > 50% in last hour for any target
SELECT
  target_host,
  COUNT(*) as requests,
  COUNTIF(NOT success) as failures,
  ROUND(COUNTIF(NOT success) * 100.0 / COUNT(*), 1) as failure_rate
FROM nba_orchestration.proxy_health_metrics
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY target_host
HAVING failure_rate > 50 AND requests >= 5;
```

## Error Types

| error_type | Description | Likely Cause |
|------------|-------------|--------------|
| `forbidden` | HTTP 403 | IP blocked by target site |
| `timeout` | Connection timeout | Target blocking or slow |
| `proxy_auth_failed` | HTTP 407 | Invalid proxy credentials |
| `rate_limited` | HTTP 429 | Too many requests |
| `connection_error` | Connection failed | Proxy down or network issue |
| `server_error` | HTTP 5xx | Target site error |

## Integration Points

### Scraper Base (`scrapers/scraper_base.py`)

The `log_proxy_result()` function is called:
1. After successful proxy request (status 200)
2. After failed proxy request (non-200 status)
3. After connection errors (timeout, refused, etc.)

### Health Logger (`shared/utils/proxy_health_logger.py`)

Provides:
- `log_proxy_result()` - Main logging function
- `extract_host_from_url()` - URL parsing helper
- `classify_error()` - Error type classification

## Alerting (TODO)

Add to daily health check or create dedicated Cloud Function:

```python
def check_proxy_health():
    """Alert if proxy failure rate exceeds threshold."""
    query = """
    SELECT target_host, failure_rate
    FROM (
      SELECT
        target_host,
        ROUND(COUNTIF(NOT success) * 100.0 / COUNT(*), 1) as failure_rate
      FROM nba_orchestration.proxy_health_metrics
      WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
      GROUP BY target_host
      HAVING COUNT(*) >= 5
    )
    WHERE failure_rate > 50
    """
    # If results, send alert
```

## Deployment Notes

After modifying proxy monitoring code:
1. Redeploy `nba-phase1-scrapers` to pick up changes
2. Monitor `proxy_health_metrics` table for new data
3. Verify summary view shows expected aggregations
