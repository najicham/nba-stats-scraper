# Error Logging Guide - NBA Stats Scraper
**Last Updated:** January 21, 2026
**Purpose:** Central reference for finding and analyzing all types of errors

---

## 🎯 Quick Start for New Chats

When investigating errors, start here:

### 1. **What type of error are you looking for?**

| Error Type | Where to Look | Quick Command |
|------------|---------------|---------------|
| **API/Scraper Errors** | `nba_orchestration.api_errors` (proposed) | `python bin/operations/query_api_errors.py --days 7` |
| **Pipeline Failures** | `nba_orchestration.scraper_execution_log` | `bq query --use_legacy_sql=false 'SELECT * FROM nba_orchestration.scraper_execution_log WHERE status = "failed" AND DATE(created_at) >= CURRENT_DATE() - 7 ORDER BY created_at DESC LIMIT 50'` |
| **Cloud Function Errors** | Google Cloud Logging | `gcloud logging read 'severity>=ERROR' --limit=50 --freshness=24h` |
| **Data Quality Issues** | `nba_orchestration.scraper_output_validation` | `bq query --use_legacy_sql=false 'SELECT * FROM nba_orchestration.scraper_output_validation WHERE validation_status IN ("WARNING", "CRITICAL") AND DATE(timestamp) >= CURRENT_DATE() - 7 ORDER BY timestamp DESC'` |
| **Service Crashes** | Cloud Run logs | `gcloud logging read 'resource.type=cloud_run_revision severity>=ERROR' --limit=50 --freshness=24h` |
| **Orchestration Issues** | Firestore state + Pub/Sub logs | See section 4 below |

### 2. **Common Investigation Workflows**

#### A. "Why is data missing for yesterday?"
```bash
# Step 1: Check if scrapers ran
bq query --use_legacy_sql=false "
  SELECT scraper_name, status, COUNT(*) as count
  FROM nba_orchestration.scraper_execution_log
  WHERE DATE(created_at) = CURRENT_DATE() - 1
  GROUP BY scraper_name, status
"

# Step 2: Check for errors
gcloud logging read 'severity>=ERROR timestamp>="'$(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=100 --format=json | jq -r '.[] | "\(.timestamp) [\(.resource.labels.service_name)] \(.textPayload // .jsonPayload.message)"'

# Step 3: Check data completeness
python scripts/check_30day_completeness.py --days 1
```

#### B. "Why are predictions not generating?"
```bash
# Check prediction pipeline
gcloud logging read 'resource.labels.service_name=~"prediction" severity>=ERROR' \
  --limit=50 --freshness=24h

# Check Phase 4/5 completion
bq query --use_legacy_sql=false "
  SELECT game_date, COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= CURRENT_DATE() - 7 AND is_active = TRUE
  GROUP BY game_date ORDER BY game_date DESC
"
```

#### C. "What APIs are failing?"
```bash
# Once API error logging is deployed:
python bin/operations/query_api_errors.py --days 7 --format report

# Current approach (from execution log):
bq query --use_legacy_sql=false "
  SELECT scraper_name, error_type, COUNT(*) as error_count
  FROM nba_orchestration.scraper_execution_log
  WHERE status = 'failed' AND DATE(created_at) >= CURRENT_DATE() - 7
  GROUP BY scraper_name, error_type
  ORDER BY error_count DESC
"
```

---

## 📚 Comprehensive Error Logging Systems

### 1. **API & Scraper Errors** 🆕 (Proposed)

**Location:** `nba_orchestration.api_errors` BigQuery table

**What It Captures:**
- Full HTTP request/response details
- Status codes, headers, body (truncated)
- Retry attempts and backoff strategies
- Rate limit information
- Error classification and root cause

**When to Use:**
- Reporting errors to API providers (BallDontLie, NBA.com, etc.)
- Analyzing API reliability and performance
- Debugging rate limiting issues
- Tracking error patterns over time

**Query Interface:**
```bash
# Get all BallDontLie errors from last week
python bin/operations/query_api_errors.py \
  --provider balldontlie \
  --days 7 \
  --format report

# Export for support ticket
python bin/operations/query_api_errors.py \
  --provider balldontlie \
  --date 2026-01-20 \
  --format csv > support_ticket.csv
```

**Documentation:**
- Proposal: `docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md`
- Implementation: `scrapers/scraper_base.py::_log_api_error()`

---

### 2. **Pipeline Execution Logs**

**Location:** `nba_orchestration.scraper_execution_log` BigQuery table

**What It Captures:**
- Every scraper execution (success, failure, no_data)
- Execution duration, record counts
- Error type and message (truncated to 1000 chars)
- Retry count, workflow context
- GCS output file paths

**Schema:**
```sql
execution_id       STRING    -- Unique run ID
scraper_name       STRING    -- Name of scraper
workflow           STRING    -- Workflow context
game_date          DATE      -- Associated game date
status             STRING    -- success/failed/no_data
triggered_at       TIMESTAMP
completed_at       TIMESTAMP
duration_seconds   FLOAT64
gcs_path           STRING    -- Output file location
error_type         STRING    -- Exception class name
error_message      STRING    -- Truncated error message
retry_count        INT64
opts               JSON      -- Scraper configuration
```

**Query Examples:**
```sql
-- Failed scrapers in last 7 days
SELECT
  scraper_name,
  error_type,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT game_date IGNORE NULLS) as affected_dates
FROM nba_orchestration.scraper_execution_log
WHERE status = 'failed'
  AND DATE(created_at) >= CURRENT_DATE() - 7
GROUP BY scraper_name, error_type
ORDER BY failure_count DESC;

-- Scraper success rates
SELECT
  scraper_name,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures,
  COUNTIF(status = 'no_data') as no_data,
  ROUND(COUNTIF(status = 'success') / COUNT(*) * 100, 2) as success_rate_pct
FROM nba_orchestration.scraper_execution_log
WHERE DATE(created_at) >= CURRENT_DATE() - 30
GROUP BY scraper_name
ORDER BY failures DESC;

-- Long-running scrapers (potential performance issues)
SELECT
  scraper_name,
  game_date,
  duration_seconds,
  triggered_at,
  completed_at,
  gcs_path
FROM nba_orchestration.scraper_execution_log
WHERE duration_seconds > 300  -- Over 5 minutes
  AND DATE(created_at) >= CURRENT_DATE() - 7
ORDER BY duration_seconds DESC;
```

**Access:**
```bash
# Via gcloud
bq query --use_legacy_sql=false 'SELECT * FROM nba_orchestration.scraper_execution_log WHERE status = "failed" ORDER BY created_at DESC LIMIT 20'

# Via Python
from google.cloud import bigquery
client = bigquery.Client()
query = "SELECT * FROM nba_orchestration.scraper_execution_log WHERE status = 'failed' AND DATE(created_at) = CURRENT_DATE() - 1"
results = client.query(query).result()
```

---

### 3. **Data Validation Errors**

**Location:** `nba_orchestration.scraper_output_validation` BigQuery table

**What It Captures:**
- Output validation results (file size, row counts)
- Data quality issues (empty files, low row counts)
- Validation status: SUCCESS, WARNING, CRITICAL
- Reason for failure and acceptability flag

**Schema:**
```sql
timestamp           TIMESTAMP
scraper_name        STRING
run_id              STRING
file_path           STRING   -- GCS path
file_size           INT64    -- Bytes
row_count           INT64    -- Actual rows written
expected_rows       INT64    -- Expected row count
validation_status   STRING   -- SUCCESS/WARNING/CRITICAL
issues              STRING   -- Comma-separated issues
reason              STRING   -- Detailed reason
is_acceptable       BOOLEAN  -- Whether zero rows is acceptable
```

**Query Examples:**
```sql
-- Critical validation failures
SELECT
  scraper_name,
  file_path,
  validation_status,
  issues,
  reason,
  row_count,
  expected_rows
FROM nba_orchestration.scraper_output_validation
WHERE validation_status = 'CRITICAL'
  AND DATE(timestamp) >= CURRENT_DATE() - 7
ORDER BY timestamp DESC;

-- Scrapers with frequent warnings
SELECT
  scraper_name,
  validation_status,
  COUNT(*) as count,
  ARRAY_AGG(DISTINCT issues) as unique_issues
FROM nba_orchestration.scraper_output_validation
WHERE validation_status IN ('WARNING', 'CRITICAL')
  AND DATE(timestamp) >= CURRENT_DATE() - 30
GROUP BY scraper_name, validation_status
ORDER BY count DESC;
```

**Access:**
```bash
bq query --use_legacy_sql=false "
  SELECT * FROM nba_orchestration.scraper_output_validation
  WHERE validation_status = 'CRITICAL'
  AND DATE(timestamp) >= CURRENT_DATE() - 7
  ORDER BY timestamp DESC
"
```

---

### 4. **Cloud Function Errors**

**Location:** Google Cloud Logging

**What It Captures:**
- Function execution errors
- Timeout errors
- Memory limit errors
- Cold start issues
- Pub/Sub delivery failures

**Query via Console:**
https://console.cloud.google.com/logs/query

**Query via gcloud:**
```bash
# All Cloud Function errors from last 24 hours
gcloud logging read 'resource.type=cloud_function severity>=ERROR' \
  --limit=100 \
  --freshness=24h \
  --format=json

# Specific function errors
gcloud logging read 'resource.labels.function_name="phase2-to-phase3-orchestrator" severity>=ERROR' \
  --limit=50 \
  --freshness=24h

# Timeout errors
gcloud logging read 'textPayload=~"timeout" OR jsonPayload.message=~"timeout"' \
  --limit=50 \
  --freshness=24h

# Memory errors
gcloud logging read 'textPayload=~"memory" OR jsonPayload.message=~"memory limit"' \
  --limit=50 \
  --freshness=24h
```

**Common Error Patterns:**
```bash
# Function not triggered
gcloud logging read 'resource.labels.function_name="phase2-to-phase3-orchestrator"' \
  --limit=10 \
  --freshness=24h

# Import errors
gcloud logging read 'severity>=ERROR textPayload=~"ModuleNotFoundError"' \
  --limit=20 \
  --freshness=24h

# HealthChecker crashes (like Jan 20-21 incident)
gcloud logging read 'severity>=ERROR textPayload=~"HealthChecker"' \
  --limit=20 \
  --freshness=24h
```

---

### 5. **Cloud Run Service Errors**

**Location:** Google Cloud Logging

**What It Captures:**
- Service crashes and restarts
- Container startup failures
- Health check failures
- Request errors (4xx, 5xx)
- Resource exhaustion

**Query Examples:**
```bash
# All Cloud Run errors from last 24 hours
gcloud logging read 'resource.type=cloud_run_revision severity>=ERROR' \
  --limit=100 \
  --freshness=24h

# Specific service errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" severity>=ERROR' \
  --limit=50 \
  --freshness=24h

# Container crashes
gcloud logging read 'textPayload=~"exit" OR textPayload=~"crash"' \
  --limit=50 \
  --freshness=24h

# Health check failures
gcloud logging read 'textPayload=~"health check failed"' \
  --limit=50 \
  --freshness=24h

# HTTP errors (4xx, 5xx)
gcloud logging read 'httpRequest.status>=400' \
  --limit=100 \
  --freshness=24h \
  --format="table(timestamp,httpRequest.status,httpRequest.requestUrl,httpRequest.userAgent)"
```

---

### 6. **Orchestration State Errors**

**Location:** Firestore `phase*_completion` collections

**What It Captures:**
- Phase completion status
- Processor completion counts
- Trigger flags
- Metadata about orchestration decisions

**Access via gcloud:**
```bash
# Cannot query Firestore via gcloud CLI - need to use Python
```

**Access via Python:**
```python
from google.cloud import firestore

db = firestore.Client()

# Check Phase 2 completion for Jan 20
doc = db.collection('phase2_completion').document('2026-01-20').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Completed processors: {data.get('completed_processors')}")
    print(f"Processor count: {data.get('processor_count')}")
    print(f"Triggered: {data.get('metadata', {}).get('_triggered')}")

# Get all incomplete Phase 2 dates from last week
from datetime import datetime, timedelta

dates = []
for i in range(7):
    date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
    doc = db.collection('phase2_completion').document(date).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get('processor_count', 0) < 6:  # Expected count
            dates.append(date)

print(f"Incomplete Phase 2 dates: {dates}")
```

**Quick Check Script:**
```bash
# Create helper script: bin/operations/check_orchestration_state.py
python bin/operations/check_orchestration_state.py --date 2026-01-20
```

---

### 7. **Pub/Sub Delivery Errors**

**Location:** Dead Letter Queues + Cloud Logging

**Dead Letter Queue Topics:**
- `nba-phase1-scrapers-complete-dlq`
- `nba-phase2-raw-complete-dlq`
- Additional DLQs for other phases

**Check DLQ Messages:**
```bash
# List DLQ messages
gcloud pubsub subscriptions list --filter="name:dlq"

# Pull messages from DLQ (doesn't acknowledge)
gcloud pubsub subscriptions pull nba-phase2-raw-complete-dlq \
  --limit=10 \
  --auto-ack=false

# Check Pub/Sub errors in logs
gcloud logging read 'resource.type=pubsub_subscription severity>=ERROR' \
  --limit=50 \
  --freshness=24h
```

**Python Script to Analyze DLQ:**
```python
# bin/operations/check_dlq.py
from google.cloud import pubsub_v1

subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path('nba-props-platform', 'nba-phase2-raw-complete-dlq')

response = subscriber.pull(
    request={"subscription": subscription_path, "max_messages": 10}
)

for msg in response.received_messages:
    print(f"Message ID: {msg.message.message_id}")
    print(f"Data: {msg.message.data.decode('utf-8')}")
    print(f"Attributes: {msg.message.attributes}")
    print("---")
```

---

### 8. **Sentry Exception Tracking**

**Location:** Sentry.io Dashboard

**What It Captures:**
- All Python exceptions
- Stack traces with source code context
- Environment context (dev/staging/prod)
- User context (if applicable)
- Breadcrumbs (events leading to error)

**Access:**
- Dashboard: https://sentry.io/organizations/[your-org]/projects/
- Direct link: Included in error notifications

**Configuration:**
```python
# scrapers/scraper_base.py, lines 26-40
import sentry_sdk

sentry_dsn = os.environ.get('SENTRY_DSN')
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=ENV,
        traces_sample_rate=1.0 if ENV == "development" else 0.1,
        profiles_sample_rate=1.0 if ENV == "development" else 0.01,
        send_default_pii=False,
    )
```

**Manual Capture:**
```python
import sentry_sdk

try:
    # ... code that might fail
except Exception as e:
    sentry_sdk.capture_exception(e)
    sentry_sdk.set_tag("scraper.status", "error")
    raise
```

---

### 9. **Email/Slack Notifications**

**Location:** Email inbox / Slack channels

**What It Captures:**
- High-severity errors requiring immediate attention
- Daily summary reports
- Data quality warnings
- Pipeline completion alerts

**Configuration:**
```bash
# Environment variables
SLACK_WEBHOOK_URL_ERROR=https://hooks.slack.com/services/...
SLACK_WEBHOOK_URL_WARNING=https://hooks.slack.com/services/...
EMAIL_RECIPIENT_ERROR=alerts@example.com
EMAIL_RECIPIENT_WARNING=notifications@example.com
```

**Notification Channels:**
- Email: AWS SES or Brevo
- Slack: Webhook-based
- Discord: Optional

**Search Tips:**
- Email: Search for "ERROR" or "CRITICAL" in subject
- Slack: Search for specific scraper names or error types
- Check #alerts channel for automated notifications

---

## 🔍 Error Investigation Flowchart

```
Start: "Something is wrong"
  |
  v
Is it a data gap?
  YES -> Check scraper_execution_log -> Found failures?
           YES -> Check Cloud Logging for details -> API error?
                    YES -> Check api_errors table (once deployed)
                    NO -> Check stack trace in Sentry
           NO -> Check orchestration state (Firestore) -> Phase not triggered?
                    YES -> Check Pub/Sub DLQ
                    NO -> Check validation table
  NO -> Is it a service crash?
           YES -> Check Cloud Run logs -> Container startup issue?
                    YES -> Check recent deployments, HealthChecker, dependencies
                    NO -> Memory/timeout issue?
                           YES -> Check resource limits, query performance
                           NO -> Check application logs for exceptions
           NO -> Check monitoring queries (bin/operations/monitoring_queries.sql)
```

---

## 📝 Error Log Retention Policies

| Log Type | Retention | Location | Cost |
|----------|-----------|----------|------|
| Cloud Logging | 30 days (default) | Google Cloud Logging | ~$0.50/GB |
| BigQuery Tables | Indefinite (manual delete) | BigQuery | ~$0.02/GB/month |
| Sentry | 90 days | Sentry.io | Varies by plan |
| Email/Slack | Depends on email/Slack plan | External | N/A |
| GCS Logs | 90 days (lifecycle policy) | Cloud Storage | ~$0.004/GB/month (Nearline) |

**Recommendations:**
- Keep critical error logs indefinitely in BigQuery
- Archive Cloud Logging to GCS after 30 days
- Export important errors to BigQuery for long-term analysis

---

## 🚀 Quick Reference Commands

### Daily Health Check
```bash
# One-liner to check all critical systems
./bin/validation/daily_data_quality_check.sh
```

### Recent Errors Summary
```bash
# Get error summary from last 24 hours
gcloud logging read 'severity>=ERROR' \
  --limit=100 \
  --freshness=24h \
  --format="table(timestamp,resource.labels.service_name,severity,textPayload.slice(0:100))"
```

### Scraper Status Dashboard
```bash
# Run monitoring queries
bq query --use_legacy_sql=false < bin/operations/monitoring_queries.sql
```

### Export Errors for Analysis
```bash
# Export last 7 days of errors to JSON
gcloud logging read 'severity>=ERROR' \
  --limit=1000 \
  --freshness=7d \
  --format=json > errors_last_7days.json

# Analyze with jq
cat errors_last_7days.json | jq -r '.[] | "\(.timestamp) [\(.resource.labels.service_name)] \(.textPayload // .jsonPayload.message)"' | sort | uniq -c | sort -rn | head -20
```

---

## 📖 Documentation Index

**Core Documentation:**
- This Guide: `/docs/ERROR-LOGGING-GUIDE.md`
- API Error Logging: `/docs/08-projects/current/week-1-improvements/API-ERROR-LOGGING-PROPOSAL.md`
- Root Cause Analysis: `/docs/08-projects/current/week-1-improvements/ROOT-CAUSE-ANALYSIS-JAN-15-21-2026.md`
- Validation System: `/validation/VALIDATOR_QUICK_REFERENCE.md`

**Operational Scripts:**
- Query API Errors: `/bin/operations/query_api_errors.py` (proposed)
- Monitoring Queries: `/bin/operations/monitoring_queries.sql`
- Daily Quality Check: `/bin/validation/daily_data_quality_check.sh`
- Check Completeness: `/scripts/check_30day_completeness.py`

**Recent Investigation Reports:**
- Data Completeness: `/COMPLETENESS-CHECK-SUMMARY.txt`
- Error Scan: `/docs/08-projects/current/week-1-improvements/ERROR-SCAN-JAN-15-21-2026.md`
- Backfill Priority: `/BACKFILL-PRIORITY-PLAN.md`

---

## 🆕 Proposed Enhancements

### 1. Centralized Error Dashboard (Future)
- Looker Studio or custom web dashboard
- Real-time error metrics by service
- Error trend visualization
- Top N errors by frequency/impact

### 2. Error Pattern Detection (Future)
- ML model to detect anomalous error rates
- Predictive alerting for degradation patterns
- Automated root cause suggestions

### 3. Error Correlation System (Future)
- Link related errors across services
- Detect cascading failures
- Track error propagation through pipeline

### 4. Automated Error Reporting (In Progress)
- Daily error summary emails
- Weekly error trend reports
- Monthly reliability metrics

---

## 🎓 Best Practices for New Chats

When investigating issues:

1. **Start with the Quick Start section** at the top
2. **Identify error type** (API, pipeline, data quality, infrastructure)
3. **Check recent logs first** (last 24-48 hours)
4. **Look for patterns** (same scraper, same time of day, same API)
5. **Correlate across systems** (Cloud Logging + BigQuery + Firestore)
6. **Document findings** (create investigation reports like this one)
7. **Reference this guide** in handoff documents for future chats

---

## 🔗 Quick Links

**GCP Console:**
- [Cloud Logging](https://console.cloud.google.com/logs/query)
- [BigQuery](https://console.cloud.google.com/bigquery)
- [Cloud Run Services](https://console.cloud.google.com/run)
- [Cloud Functions](https://console.cloud.google.com/functions/list)
- [Pub/Sub Topics](https://console.cloud.google.com/cloudpubsub/topic/list)
- [Firestore](https://console.cloud.google.com/firestore/data)

**External:**
- [Sentry Dashboard](https://sentry.io)

---

**Last Updated:** January 21, 2026
**Maintained By:** Engineering Team
**Questions?** Review this guide first, then check recent investigation reports in `/docs/08-projects/current/`
