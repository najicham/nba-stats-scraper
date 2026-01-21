# API Error Logging Enhancement - Proposal
**Date:** January 21, 2026
**Purpose:** Enable quick identification and reporting of API errors to providers (BallDontLie, NBA.com, etc.)

---

## Problem Statement

When API errors occur, we need to:
1. **Quickly identify** which APIs are failing and why
2. **Extract exact details** to report to API providers
3. **Track patterns** in failures over time
4. **Correlate** errors across related services

**Current State:**
- Errors logged to Google Cloud Logging (scattered)
- Basic error info in `nba_orchestration.scraper_execution_log` table
- Response bodies and detailed HTTP metadata NOT systematically captured

**Goal:**
- Centralized API error database with full context
- Query interface to extract error reports for API providers
- Automated error pattern detection

---

## Proposed Solution

### 1. Create Dedicated API Error Table

**BigQuery Table:** `nba_orchestration.api_errors`

**Schema:**
```sql
CREATE TABLE `nba-props-platform.nba_orchestration.api_errors` (
  -- Identifiers
  error_id STRING NOT NULL,
  execution_id STRING,  -- Link to scraper_execution_log
  correlation_id STRING,

  -- Timestamp
  occurred_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),

  -- API Context
  api_provider STRING NOT NULL,  -- 'balldontlie', 'nba_api', 'odds_api', etc.
  api_endpoint STRING NOT NULL,  -- '/games', '/box_scores', etc.
  api_version STRING,

  -- Scraper Context
  scraper_name STRING NOT NULL,
  workflow STRING,
  game_date DATE,
  environment STRING,  -- 'production', 'staging', 'development'

  -- HTTP Request Details
  request_method STRING,  -- GET, POST, etc.
  request_url STRING NOT NULL,
  request_headers JSON,
  request_body STRING,  -- Truncated to 10KB
  request_sent_at TIMESTAMP,

  -- HTTP Response Details
  response_status_code INT64,
  response_reason STRING,
  response_headers JSON,
  response_body STRING,  -- Truncated to 50KB
  response_received_at TIMESTAMP,
  response_time_ms INT64,

  -- Error Details
  error_type STRING NOT NULL,  -- 'HTTP_ERROR', 'TIMEOUT', 'CONNECTION_ERROR', 'RATE_LIMIT', etc.
  error_category STRING,  -- 'CLIENT_ERROR', 'SERVER_ERROR', 'NETWORK_ERROR', 'AUTH_ERROR'
  error_message STRING NOT NULL,
  error_stack_trace STRING,

  -- Retry Information
  retry_attempt INT64,
  max_retries INT64,
  next_retry_at TIMESTAMP,
  backoff_seconds FLOAT64,
  is_final_attempt BOOLEAN,

  -- Error Classification
  is_retriable BOOLEAN,
  severity STRING,  -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
  impact_assessment STRING,  -- 'DATA_LOSS', 'PARTIAL_DATA', 'DELAYED', 'NO_IMPACT'

  -- Root Cause Analysis
  suspected_cause STRING,  -- 'RATE_LIMITING', 'API_DOWNTIME', 'INVALID_REQUEST', 'AUTH_FAILURE', etc.
  suggested_fix STRING,
  related_error_ids ARRAY<STRING>,

  -- API Provider Information
  api_rate_limit_info JSON,  -- {'limit': 60, 'remaining': 0, 'reset': timestamp}
  api_error_code STRING,  -- Provider-specific error code
  api_error_details JSON,  -- Provider-specific error response

  -- Additional Metadata
  upstream_dependencies ARRAY<STRING>,
  affected_games ARRAY<STRING>,
  data_completeness_impact FLOAT64,  -- Percentage of expected data lost

  -- Resolution Tracking
  resolved_at TIMESTAMP,
  resolution_type STRING,  -- 'AUTO_RETRY_SUCCESS', 'MANUAL_FIX', 'API_PROVIDER_FIX', 'NO_RESOLUTION'
  resolution_notes STRING
)
PARTITION BY DATE(occurred_at)
CLUSTER BY api_provider, error_type, scraper_name;
```

---

### 2. Enhance Error Capture in Scrapers

**File:** `/home/naji/code/nba-stats-scraper/scrapers/scraper_base.py`

**Add Method to Capture API Errors:**
```python
def _log_api_error(
    self,
    error: Exception,
    response: Optional[requests.Response] = None,
    request_sent_at: Optional[datetime] = None,
    retry_attempt: int = 0
) -> str:
    """
    Log detailed API error information to BigQuery.

    Returns:
        error_id: Unique identifier for this error
    """
    import uuid
    from google.cloud import bigquery

    error_id = str(uuid.uuid4())

    # Extract API provider from scraper name
    api_provider = self._get_api_provider()

    # Capture HTTP request details
    request_details = {
        'method': getattr(self, 'http_method', 'GET'),
        'url': getattr(self, 'url', 'unknown'),
        'headers': self._sanitize_headers(getattr(self, 'headers', {})),
        'body': None,  # Capture if POST request
        'sent_at': request_sent_at or datetime.now(timezone.utc)
    }

    # Capture HTTP response details
    response_details = {}
    if response:
        response_details = {
            'status_code': response.status_code,
            'reason': response.reason,
            'headers': dict(response.headers),
            'body': self._truncate_text(response.text, 50000),
            'received_at': datetime.now(timezone.utc),
            'time_ms': int(response.elapsed.total_seconds() * 1000)
        }

        # Extract rate limit info if present
        rate_limit_info = self._extract_rate_limit_info(response.headers)
    else:
        rate_limit_info = None

    # Classify error
    error_classification = self._classify_error(error, response)

    # Build error record
    error_record = {
        'error_id': error_id,
        'execution_id': getattr(self, 'run_id', None),
        'correlation_id': getattr(self, 'correlation_id', None),
        'occurred_at': datetime.now(timezone.utc).isoformat(),
        'created_at': datetime.now(timezone.utc).isoformat(),

        # API Context
        'api_provider': api_provider,
        'api_endpoint': self._extract_endpoint(request_details['url']),
        'api_version': getattr(self, 'api_version', None),

        # Scraper Context
        'scraper_name': self.__class__.__name__,
        'workflow': getattr(self, 'workflow', None),
        'game_date': getattr(self, 'opts', {}).get('game_date'),
        'environment': os.environ.get('ENVIRONMENT', 'production'),

        # HTTP Details
        'request_method': request_details['method'],
        'request_url': request_details['url'],
        'request_headers': request_details['headers'],
        'request_body': request_details['body'],
        'request_sent_at': request_details['sent_at'].isoformat(),

        'response_status_code': response_details.get('status_code'),
        'response_reason': response_details.get('reason'),
        'response_headers': response_details.get('headers'),
        'response_body': response_details.get('body'),
        'response_received_at': response_details.get('received_at', '').isoformat() if response_details.get('received_at') else None,
        'response_time_ms': response_details.get('time_ms'),

        # Error Details
        'error_type': error_classification['type'],
        'error_category': error_classification['category'],
        'error_message': str(error)[:1000],
        'error_stack_trace': self._get_stack_trace(error),

        # Retry Info
        'retry_attempt': retry_attempt,
        'max_retries': getattr(self, 'max_retries_http', 3),
        'next_retry_at': self._calculate_next_retry(retry_attempt).isoformat() if retry_attempt < self.max_retries_http else None,
        'backoff_seconds': self._calculate_backoff(retry_attempt),
        'is_final_attempt': retry_attempt >= getattr(self, 'max_retries_http', 3),

        # Classification
        'is_retriable': error_classification['retriable'],
        'severity': error_classification['severity'],
        'impact_assessment': self._assess_impact(error, response),

        # Root Cause
        'suspected_cause': error_classification['suspected_cause'],
        'suggested_fix': error_classification['suggested_fix'],
        'related_error_ids': [],

        # API Provider Info
        'api_rate_limit_info': rate_limit_info,
        'api_error_code': self._extract_api_error_code(response),
        'api_error_details': self._extract_api_error_details(response),

        # Metadata
        'upstream_dependencies': self._get_upstream_dependencies(),
        'affected_games': self._get_affected_games(),
        'data_completeness_impact': self._estimate_data_impact(error),
    }

    # Write to BigQuery
    try:
        client = bigquery.Client()
        table = client.get_table('nba-props-platform.nba_orchestration.api_errors')
        errors = client.insert_rows_json(table, [error_record])

        if not errors:
            logger.info(f"API error logged: {error_id}")
        else:
            logger.error(f"Failed to log API error: {errors}")
    except Exception as e:
        logger.error(f"Failed to write to api_errors table: {e}")

    return error_id
```

**Helper Methods:**
```python
def _get_api_provider(self) -> str:
    """Extract API provider from scraper name."""
    name = self.__class__.__name__.lower()
    if 'bdl' in name or 'balldontlie' in name:
        return 'balldontlie'
    elif 'nbac' in name or 'nba_api' in name:
        return 'nba_api'
    elif 'odds' in name:
        return 'odds_api'
    elif 'espn' in name:
        return 'espn'
    elif 'bigdataball' in name or 'bdb' in name:
        return 'bigdataball'
    else:
        return 'unknown'

def _sanitize_headers(self, headers: dict) -> dict:
    """Remove sensitive information from headers."""
    sensitive_keys = ['authorization', 'api-key', 'x-api-key', 'cookie', 'token']
    return {
        k: '***REDACTED***' if k.lower() in sensitive_keys else v
        for k, v in headers.items()
    }

def _extract_rate_limit_info(self, headers: dict) -> Optional[dict]:
    """Extract rate limit information from response headers."""
    rate_limit_headers = [
        'x-ratelimit-limit',
        'x-ratelimit-remaining',
        'x-ratelimit-reset',
        'ratelimit-limit',
        'ratelimit-remaining',
        'ratelimit-reset',
        'retry-after'
    ]

    info = {}
    for key, value in headers.items():
        if key.lower() in rate_limit_headers:
            info[key.lower().replace('x-ratelimit-', '').replace('ratelimit-', '')] = value

    return info if info else None

def _classify_error(self, error: Exception, response: Optional[requests.Response]) -> dict:
    """Classify error and determine appropriate handling."""
    if response:
        status = response.status_code
        if status == 429:
            return {
                'type': 'RATE_LIMIT',
                'category': 'CLIENT_ERROR',
                'retriable': True,
                'severity': 'MEDIUM',
                'suspected_cause': 'RATE_LIMITING',
                'suggested_fix': 'Increase backoff delay, reduce request frequency'
            }
        elif 400 <= status < 500:
            return {
                'type': 'HTTP_CLIENT_ERROR',
                'category': 'CLIENT_ERROR',
                'retriable': False,
                'severity': 'HIGH',
                'suspected_cause': 'INVALID_REQUEST',
                'suggested_fix': 'Review request parameters and authentication'
            }
        elif 500 <= status < 600:
            return {
                'type': 'HTTP_SERVER_ERROR',
                'category': 'SERVER_ERROR',
                'retriable': True,
                'severity': 'HIGH',
                'suspected_cause': 'API_DOWNTIME',
                'suggested_fix': 'Retry with exponential backoff, contact API provider'
            }

    if isinstance(error, requests.Timeout):
        return {
            'type': 'TIMEOUT',
            'category': 'NETWORK_ERROR',
            'retriable': True,
            'severity': 'MEDIUM',
            'suspected_cause': 'SLOW_API_RESPONSE',
            'suggested_fix': 'Increase timeout, check API status'
        }
    elif isinstance(error, requests.ConnectionError):
        return {
            'type': 'CONNECTION_ERROR',
            'category': 'NETWORK_ERROR',
            'retriable': True,
            'severity': 'HIGH',
            'suspected_cause': 'NETWORK_ISSUE',
            'suggested_fix': 'Check network connectivity, verify API endpoint'
        }

    return {
        'type': 'UNKNOWN',
        'category': 'UNKNOWN',
        'retriable': False,
        'severity': 'CRITICAL',
        'suspected_cause': 'UNKNOWN',
        'suggested_fix': 'Manual investigation required'
    }
```

---

### 3. Update Exception Handling to Use New Logging

**Modify existing error handlers in `scraper_base.py`:**

```python
# Line ~1150 - HTTP error handling
except InvalidHttpStatusCodeException as e:
    # NEW: Log to api_errors table
    error_id = self._log_api_error(
        error=e,
        response=self.raw_response,
        request_sent_at=request_start_time,
        retry_attempt=self.download_retry_count
    )

    # Existing notification (now enhanced with error_id)
    notify_error(
        title=f"Scraper HTTP Error: {self.__class__.__name__}",
        message=f"Invalid HTTP status code: {getattr(self.raw_response, 'status_code', 'unknown')}",
        details={
            'error_id': error_id,  # NEW
            'scraper': self.__class__.__name__,
            'run_id': self.run_id,
            'url': getattr(self, 'url', 'unknown'),
            'status_code': getattr(self.raw_response, 'status_code', 'unknown'),
            'retry_count': self.download_retry_count,
            'error': str(e),
            'report_url': f'https://console.cloud.google.com/bigquery?q=SELECT * FROM nba_orchestration.api_errors WHERE error_id = "{error_id}"'  # NEW
        }
    )
    raise
```

---

### 4. Create Error Query Interface

**File:** `/home/naji/code/nba-stats-scraper/bin/operations/query_api_errors.py`

```python
#!/usr/bin/env python3
"""
Query API errors for reporting to providers.

Usage:
    # Get all BallDontLie errors from last 7 days
    python bin/operations/query_api_errors.py --provider balldontlie --days 7

    # Get specific date errors
    python bin/operations/query_api_errors.py --date 2026-01-20 --provider balldontlie

    # Get errors by endpoint
    python bin/operations/query_api_errors.py --endpoint "/games" --days 7

    # Export to CSV for provider support ticket
    python bin/operations/query_api_errors.py --provider balldontlie --days 7 --format csv > bdl_errors.csv
"""

import argparse
from datetime import datetime, timedelta, timezone
from google.cloud import bigquery
import json
import csv
import sys

def query_api_errors(
    provider: str = None,
    endpoint: str = None,
    start_date: str = None,
    end_date: str = None,
    days: int = None,
    error_type: str = None,
    format: str = 'json'
):
    """Query API errors with filters."""

    client = bigquery.Client()

    # Build WHERE clause
    conditions = []

    if provider:
        conditions.append(f"api_provider = '{provider}'")

    if endpoint:
        conditions.append(f"api_endpoint = '{endpoint}'")

    if error_type:
        conditions.append(f"error_type = '{error_type}'")

    # Date filtering
    if days:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        conditions.append(f"occurred_at >= TIMESTAMP('{start.isoformat()}')")
        conditions.append(f"occurred_at <= TIMESTAMP('{end.isoformat()}')")
    elif start_date and end_date:
        conditions.append(f"DATE(occurred_at) >= '{start_date}'")
        conditions.append(f"DATE(occurred_at) <= '{end_date}'")
    elif start_date:
        conditions.append(f"DATE(occurred_at) = '{start_date}'")

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    query = f"""
    SELECT
        error_id,
        occurred_at,
        api_provider,
        api_endpoint,
        scraper_name,
        request_method,
        request_url,
        response_status_code,
        response_reason,
        response_time_ms,
        error_type,
        error_category,
        error_message,
        retry_attempt,
        is_final_attempt,
        suspected_cause,
        suggested_fix,
        api_rate_limit_info,
        api_error_code,
        api_error_details,
        response_body,
        request_headers,
        response_headers
    FROM `nba-props-platform.nba_orchestration.api_errors`
    WHERE {where_clause}
    ORDER BY occurred_at DESC
    LIMIT 1000
    """

    results = client.query(query).result()

    # Format output
    if format == 'json':
        output = [dict(row) for row in results]
        print(json.dumps(output, indent=2, default=str))

    elif format == 'csv':
        if results.total_rows == 0:
            print("No errors found")
            return

        writer = csv.DictWriter(sys.stdout, fieldnames=results.schema)
        writer.writeheader()
        for row in results:
            writer.writerow(dict(row))

    elif format == 'report':
        # Human-readable report for API provider
        print("=" * 80)
        print(f"API ERROR REPORT")
        print(f"Provider: {provider or 'All'}")
        print(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 80)
        print()

        for row in results:
            print(f"Error ID: {row.error_id}")
            print(f"Occurred: {row.occurred_at}")
            print(f"Endpoint: {row.request_method} {row.api_endpoint}")
            print(f"Status Code: {row.response_status_code} ({row.response_reason})")
            print(f"Error Type: {row.error_type}")
            print(f"Error Message: {row.error_message}")
            if row.api_error_code:
                print(f"API Error Code: {row.api_error_code}")
            if row.api_rate_limit_info:
                print(f"Rate Limit Info: {row.api_rate_limit_info}")
            print(f"Request URL: {row.request_url}")
            print(f"Response Time: {row.response_time_ms}ms")
            print()
            print("Response Body (truncated):")
            print(row.response_body[:500] if row.response_body else "N/A")
            print()
            print("-" * 80)
            print()

def main():
    parser = argparse.ArgumentParser(description='Query API errors')
    parser.add_argument('--provider', help='API provider (balldontlie, nba_api, etc.)')
    parser.add_argument('--endpoint', help='API endpoint (e.g., /games)')
    parser.add_argument('--date', help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Last N days')
    parser.add_argument('--error-type', help='Error type filter')
    parser.add_argument('--format', choices=['json', 'csv', 'report'], default='report',
                       help='Output format')

    args = parser.parse_args()

    query_api_errors(
        provider=args.provider,
        endpoint=args.endpoint,
        start_date=args.date or args.start_date,
        end_date=args.end_date,
        days=args.days,
        error_type=args.error_type,
        format=args.format
    )

if __name__ == '__main__':
    main()
```

---

### 5. Create Error Dashboard Queries

**File:** `/home/naji/code/nba-stats-scraper/bin/operations/api_error_analytics.sql`

```sql
-- Query 1: Error Summary by Provider (Last 7 Days)
SELECT
  api_provider,
  COUNT(*) as total_errors,
  COUNT(DISTINCT DATE(occurred_at)) as affected_days,
  COUNT(DISTINCT api_endpoint) as affected_endpoints,
  COUNT(DISTINCT scraper_name) as affected_scrapers,
  COUNTIF(is_final_attempt) as final_failures,
  AVG(response_time_ms) as avg_response_time_ms,
  STRING_AGG(DISTINCT error_type, ', ') as error_types
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY api_provider
ORDER BY total_errors DESC;

-- Query 2: Top Errors by Frequency
SELECT
  api_provider,
  api_endpoint,
  error_type,
  error_message,
  COUNT(*) as occurrence_count,
  MIN(occurred_at) as first_seen,
  MAX(occurred_at) as last_seen,
  COUNTIF(resolved_at IS NOT NULL) as resolved_count,
  suspected_cause,
  suggested_fix
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY api_provider, api_endpoint, error_type, error_message, suspected_cause, suggested_fix
ORDER BY occurrence_count DESC
LIMIT 20;

-- Query 3: Rate Limiting Analysis
SELECT
  api_provider,
  DATE(occurred_at) as error_date,
  EXTRACT(HOUR FROM occurred_at) as error_hour,
  COUNT(*) as rate_limit_errors,
  AVG(CAST(JSON_EXTRACT_SCALAR(api_rate_limit_info, '$.remaining') AS INT64)) as avg_remaining_quota
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE error_type = 'RATE_LIMIT'
  AND occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY api_provider, error_date, error_hour
ORDER BY error_date DESC, error_hour DESC;

-- Query 4: Error Impact Assessment
SELECT
  api_provider,
  DATE(occurred_at) as error_date,
  COUNT(*) as total_errors,
  COUNTIF(is_final_attempt) as final_failures,
  COUNTIF(impact_assessment = 'DATA_LOSS') as data_loss_count,
  COUNTIF(impact_assessment = 'PARTIAL_DATA') as partial_data_count,
  AVG(data_completeness_impact) as avg_data_loss_pct,
  ARRAY_AGG(DISTINCT game_date IGNORE NULLS) as affected_game_dates
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY api_provider, error_date
HAVING final_failures > 0
ORDER BY error_date DESC, final_failures DESC;

-- Query 5: Error Resolution Tracking
SELECT
  api_provider,
  error_type,
  COUNT(*) as total_errors,
  COUNTIF(resolved_at IS NOT NULL) as resolved_count,
  ROUND(COUNTIF(resolved_at IS NOT NULL) / COUNT(*) * 100, 2) as resolution_rate_pct,
  AVG(TIMESTAMP_DIFF(resolved_at, occurred_at, MINUTE)) as avg_resolution_time_minutes,
  STRING_AGG(DISTINCT resolution_type, ', ') as resolution_types
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY api_provider, error_type
ORDER BY total_errors DESC;
```

---

### 6. Create Automated Daily Error Report

**File:** `/home/naji/code/nba-stats-scraper/bin/operations/send_daily_error_report.py`

```python
#!/usr/bin/env python3
"""
Send daily API error report email.

Schedule with Cloud Scheduler:
    Schedule: 0 8 * * * (8 AM daily)
    Target: Cloud Function or Cloud Run job
"""

from google.cloud import bigquery
from datetime import datetime, timedelta, timezone
from shared.utils.notification_system import NotificationSystem

def generate_daily_error_report():
    """Generate and send daily API error report."""

    client = bigquery.Client()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    query = f"""
    SELECT
      api_provider,
      COUNT(*) as total_errors,
      COUNT(DISTINCT api_endpoint) as endpoints_affected,
      COUNTIF(is_final_attempt) as final_failures,
      COUNTIF(error_type = 'RATE_LIMIT') as rate_limit_errors,
      STRING_AGG(DISTINCT error_type, ', ') as error_types,
      suspected_cause,
      suggested_fix
    FROM `nba-props-platform.nba_orchestration.api_errors`
    WHERE DATE(occurred_at) = '{yesterday}'
    GROUP BY api_provider, suspected_cause, suggested_fix
    HAVING total_errors > 0
    ORDER BY total_errors DESC
    """

    results = list(client.query(query).result())

    if not results:
        print(f"No API errors on {yesterday} - no report sent")
        return

    # Build email body
    email_body = f"""
    <h2>Daily API Error Report - {yesterday}</h2>

    <table border="1" cellpadding="5">
    <tr>
        <th>API Provider</th>
        <th>Total Errors</th>
        <th>Final Failures</th>
        <th>Rate Limits</th>
        <th>Suspected Cause</th>
        <th>Suggested Fix</th>
    </tr>
    """

    for row in results:
        email_body += f"""
        <tr>
            <td>{row.api_provider}</td>
            <td>{row.total_errors}</td>
            <td>{row.final_failures}</td>
            <td>{row.rate_limit_errors}</td>
            <td>{row.suspected_cause}</td>
            <td>{row.suggested_fix}</td>
        </tr>
        """

    email_body += """
    </table>

    <p>
    <a href="https://console.cloud.google.com/bigquery?q=SELECT * FROM nba_orchestration.api_errors WHERE DATE(occurred_at) = CURRENT_DATE() - 1 ORDER BY occurred_at DESC">
    View Full Details in BigQuery
    </a>
    </p>
    """

    # Send notification
    notifier = NotificationSystem()
    notifier.send_notification(
        level='WARNING' if sum(r.final_failures for r in results) > 0 else 'INFO',
        title=f'Daily API Error Report - {yesterday}',
        message=f'{sum(r.total_errors for r in results)} total errors across {len(results)} providers',
        details=email_body,
        channels=['email']
    )

if __name__ == '__main__':
    generate_daily_error_report()
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)
1. ✅ Create `api_errors` BigQuery table
2. ✅ Add `_log_api_error()` method to `scraper_base.py`
3. ✅ Update exception handlers to call `_log_api_error()`
4. ✅ Test with single scraper (BdlBoxScoresScraper)

### Phase 2: Query Interface (Week 1)
5. ✅ Create `query_api_errors.py` script
6. ✅ Create `api_error_analytics.sql` queries
7. ✅ Document usage in README

### Phase 3: Automation (Week 2)
8. ✅ Deploy `send_daily_error_report.py` as Cloud Function
9. ✅ Schedule with Cloud Scheduler (8 AM daily)
10. ✅ Add alert policies for error rate spikes

### Phase 4: Enhancement (Week 3)
11. Create web dashboard using Looker Studio or custom frontend
12. Implement error pattern detection ML model
13. Add predictive alerting for degradation patterns

---

## Usage Examples

### Example 1: Query BallDontLie Errors for Support Ticket
```bash
# Get all BallDontLie errors from yesterday in report format
python bin/operations/query_api_errors.py \
  --provider balldontlie \
  --date 2026-01-20 \
  --format report > bdl_support_ticket.txt

# Send to BallDontLie support
cat bdl_support_ticket.txt | mail -s "API Errors on Jan 20" support@balldontlie.io
```

### Example 2: Analyze Rate Limiting Issues
```sql
-- Run in BigQuery Console
SELECT
  api_provider,
  api_endpoint,
  occurred_at,
  JSON_EXTRACT_SCALAR(api_rate_limit_info, '$.remaining') as remaining_quota,
  JSON_EXTRACT_SCALAR(api_rate_limit_info, '$.reset') as reset_time,
  response_body
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE error_type = 'RATE_LIMIT'
  AND api_provider = 'balldontlie'
  AND DATE(occurred_at) = '2026-01-20'
ORDER BY occurred_at;
```

### Example 3: Track Error Resolution
```sql
-- Find unresolved errors from past week
SELECT
  error_id,
  occurred_at,
  api_provider,
  api_endpoint,
  error_message,
  suspected_cause,
  suggested_fix
FROM `nba-props-platform.nba_orchestration.api_errors`
WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND resolved_at IS NULL
  AND is_final_attempt = TRUE
ORDER BY occurred_at DESC;

-- Mark error as resolved
UPDATE `nba-props-platform.nba_orchestration.api_errors`
SET
  resolved_at = CURRENT_TIMESTAMP(),
  resolution_type = 'MANUAL_FIX',
  resolution_notes = 'Increased timeout from 20s to 30s'
WHERE error_id = 'abc-123-def';
```

---

## Benefits

1. **Quick Identification**: Query errors by provider, endpoint, date in seconds
2. **Exact Details**: Full HTTP request/response context for provider support
3. **Pattern Detection**: Automated analysis of error trends and root causes
4. **Proactive Alerting**: Daily reports and anomaly detection
5. **Resolution Tracking**: Monitor fix effectiveness over time
6. **Data Impact**: Quantify data loss from API failures

---

## Estimated Effort

- **Schema Creation**: 1 hour
- **Code Implementation**: 4-6 hours
- **Testing**: 2-3 hours
- **Documentation**: 1-2 hours
- **Deployment**: 1-2 hours

**Total**: ~10-15 hours (1-2 days)

---

## Next Steps

1. Review and approve proposal
2. Create `api_errors` BigQuery table
3. Implement `_log_api_error()` in scraper_base.py
4. Test with recent errors
5. Deploy query scripts
6. Schedule daily reports

---

**Questions or Feedback?**
- Adjust schema based on specific API provider needs
- Add additional fields for specific error scenarios
- Customize query interface for common use cases
