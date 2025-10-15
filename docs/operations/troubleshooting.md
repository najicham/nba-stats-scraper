# NBA Platform Troubleshooting Guide

## Overview

This guide covers common issues, debugging techniques, and solutions for the NBA analytics platform running on Cloud Run.

## Quick Diagnosis Commands

### 🔍 **Service Status Check**
```bash
# Check all services
./bin/check_service_health.sh

# Individual service status
gcloud run services describe nba-scraper-events --region=us-central1

# Get service URLs  
gcloud run services list --platform=managed --region=us-central1
```

### 📝 **Log Analysis**
```bash
# Recent errors across all services
gcloud logs read "resource.type=cloud_run_revision AND severity=ERROR" --limit=20

# Service-specific logs
gcloud logs read "resource.labels.service_name=nba-scraper-events" --limit=50

# Real-time log streaming
gcloud logs tail "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scraper-events"

# Search for specific errors
gcloud logs read "resource.type=cloud_run_revision AND textPayload=~'API.*error'" --limit=10
```

## Common Issues by Service

### 🕷️ **Scraper Issues**

#### Issue: API Rate Limiting
**Symptoms:**
- HTTP 429 responses in logs
- "Rate limit exceeded" error messages
- Scrapers failing consistently

**Diagnosis:**
```bash
# Check for rate limit errors
gcloud logs read "resource.labels.service_name=nba-scraper-events AND textPayload=~'429|rate.limit'" --limit=10

# Check API call frequency
gcloud logs read "jsonPayload.message=~'SCRAPER_STATS.*'" --limit=20 | grep api_calls
```

**Solutions:**
```python
# 1. Implement exponential backoff (already in scraper_base.py)
# 2. Add rate limiting configuration
RATE_LIMITS = {
    'odds_api': {'calls_per_minute': 500, 'burst': 10},
    'ball_dont_lie': {'calls_per_minute': 60, 'burst': 5}
}

# 3. Distribute requests across time
import time
import random

def distributed_delay():
    base_delay = 60 / RATE_LIMITS['odds_api']['calls_per_minute']
    jitter = random.uniform(0.5, 1.5)
    time.sleep(base_delay * jitter)
```

**Prevention:**
- Monitor API usage in dashboards
- Set up alerts for rate limit approaches
- Use multiple API keys if available

#### Issue: Container Memory Limits
**Symptoms:**
- Services crashing with exit code 137
- "out of memory" in logs
- Slow response times

**Diagnosis:**
```bash
# Check memory usage
gcloud monitoring metrics list --filter="resource.type=cloud_run_revision" | grep memory

# Check container limits
gcloud run services describe nba-scraper-events --region=us-central1 --format="yaml" | grep -A 5 resources
```

**Solutions:**
```bash
# Increase memory limits
gcloud run services update nba-scraper-events \
  --memory 2Gi \
  --region us-central1

# Optimize Python memory usage
export PYTHONOPTIMIZE=1
export PYTHONUNBUFFERED=1
```

**Prevention:**
- Monitor memory usage patterns
- Profile memory-intensive operations
- Implement data streaming for large datasets

#### Issue: API Authentication Failures
**Symptoms:**
- HTTP 401/403 responses
- "Invalid API key" errors
- "Authentication failed" messages

**Diagnosis:**
```bash
# Check secret access
gcloud secrets versions list odds-api-key

# Test secret access from service account
gcloud secrets versions access latest --secret=odds-api-key \
  --impersonate-service-account=nba-scraper-sa@PROJECT_ID.iam.gserviceaccount.com

# Check IAM permissions
gcloud projects get-iam-policy PROJECT_ID --filter="bindings.members:nba-scraper-sa@PROJECT_ID.iam.gserviceaccount.com"
```

**Solutions:**
```bash
# 1. Verify secret exists and is accessible
gcloud secrets describe odds-api-key

# 2. Update secret if needed
echo -n "NEW_API_KEY" | gcloud secrets versions add odds-api-key --data-file=-

# 3. Check service account permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:nba-scraper-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 4. Restart service to pick up new secrets
gcloud run services update nba-scraper-events --region=us-central1
```

### ⚙️ **Processor Issues**

#### Issue: BigQuery Loading Failures
**Symptoms:**
- "Table not found" errors
- "Schema mismatch" errors
- Data not appearing in BigQuery

**Diagnosis:**
```bash
# Check BigQuery job errors
bq ls -j --max_results=10

# Check specific job details
bq show -j JOB_ID

# Check dataset and table permissions
bq show --dataset PROJECT_ID:nba_analytics
```

**Solutions:**
```python
# 1. Auto-create tables with schema detection
from google.cloud import bigquery

def load_data_with_auto_schema(data, table_id):
    client = bigquery.Client()
    job_config = bigquery.LoadJobConfig(
        autodetect=True,
        write_disposition="WRITE_APPEND",
        create_disposition="CREATE_IF_NEEDED"
    )
    
    job = client.load_table_from_json(data, table_id, job_config=job_config)
    job.result()  # Wait for completion

# 2. Implement schema validation
def validate_schema(data, expected_schema):
    for record in data:
        for field, field_type in expected_schema.items():
            if field not in record:
                raise ValueError(f"Missing field: {field}")
            if not isinstance(record[field], field_type):
                raise ValueError(f"Wrong type for {field}: expected {field_type}")
```

**Prevention:**
- Version control BigQuery schemas
- Implement schema migration procedures
- Add data validation before loading

#### Issue: Pub/Sub Message Processing Failures
**Symptoms:**
- Messages stuck in subscription
- Dead letter queue filling up
- Processing timeouts

**Diagnosis:**
```bash
# Check subscription metrics
gcloud pubsub subscriptions describe nba-processing-subscription

# Check dead letter queue
gcloud pubsub topics list | grep dead-letter

# Check message age
gcloud monitoring metrics list --filter="resource.type=pubsub_subscription"
```

**Solutions:**
```python
# 1. Implement proper error handling
import json
from google.cloud import pubsub_v1

def process_message_safely(message):
    try:
        data = json.loads(message.data.decode('utf-8'))
        process_data(data)
        message.ack()
    except ValueError as e:
        logger.error(f"Invalid JSON in message: {e}")
        message.ack()  # Don't retry invalid JSON
    except Exception as e:
        logger.error(f"Processing error: {e}")
        message.nack()  # Retry later

# 2. Configure appropriate timeouts
subscriber_options = pubsub_v1.types.FlowControlSettings(
    max_messages=100,
    max_bytes=1024*1024*10  # 10MB
)
```

### 📊 **Report Generator Issues**

#### Issue: PDF Generation Failures
**Symptoms:**
- "WeasyPrint error" in logs
- Empty or corrupted PDF files
- Font rendering issues

**Diagnosis:**
```bash
# Check report generation logs
gcloud logs read "resource.labels.service_name=nba-reportgen AND textPayload=~'PDF|WeasyPrint'" --limit=10

# Test PDF generation locally
docker run -it nba-reportgen bash
python -c "import weasyprint; print(weasyprint.VERSION)"
```

**Solutions:**
```dockerfile
# 1. Fix font issues in Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    fonts-dejavu-core \
    fontconfig \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Add font configuration
RUN fc-cache -fv
```

```python
# 3. Handle PDF generation errors gracefully
def generate_pdf_report(html_content, output_path):
    try:
        import weasyprint
        pdf = weasyprint.HTML(string=html_content).write_pdf()
        with open(output_path, 'wb') as f:
            f.write(pdf)
        return True
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        # Fallback to HTML report
        with open(output_path.replace('.pdf', '.html'), 'w') as f:
            f.write(html_content)
        return False
```

## Container and Deployment Issues

### 🐳 **Container Build Failures**

#### Issue: Docker Build Timeouts
**Symptoms:**
- Cloud Build jobs timing out
- "Step timeout" errors
- Large image build times

**Diagnosis:**
```bash
# Check build logs
gcloud builds log BUILD_ID

# Check build configuration
cat docker/cloudbuild.yaml | grep timeout
```

**Solutions:**
```yaml
# 1. Optimize build steps in cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '--cache-from', 'gcr.io/$PROJECT_ID/nba-base:latest', ...]
    
# 2. Use build caching
options:
  machineType: 'E2_HIGHCPU_8'
  substitution_option: 'ALLOW_LOOSE'
  
timeout: '3600s'  # Increase timeout
```

```dockerfile
# 3. Optimize Dockerfile layers
# Use .dockerignore to exclude unnecessary files
# Multi-stage builds to reduce final image size
FROM python:3.11-slim as builder
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
```

#### Issue: Image Size Too Large
**Symptoms:**
- Slow container startup
- High storage costs
- Long image pull times

**Diagnosis:**
```bash
# Check image sizes
gcloud container images list-tags gcr.io/PROJECT_ID/nba-scrapers --format="table(digest,timestamp,tags,SIZE)"

# Analyze image layers
docker image inspect gcr.io/PROJECT_ID/nba-scrapers:latest
```

**Solutions:**
```dockerfile
# 1. Use distroless or alpine base images
FROM gcr.io/distroless/python3-debian11

# 2. Multi-stage builds
FROM python:3.11-slim as builder
RUN pip install --user dependencies

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local

# 3. Remove unnecessary packages
RUN apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*
```

### ☁️ **Cloud Run Deployment Issues**

#### Issue: Service Deployment Failures
**Symptoms:**
- "Service deployment failed" errors
- New revisions not receiving traffic
- Health check failures

**Diagnosis:**
```bash
# Check deployment status
gcloud run revisions list --service=nba-scraper-events --region=us-central1

# Check revision details
gcloud run revisions describe REVISION_NAME --region=us-central1

# Check traffic allocation
gcloud run services describe nba-scraper-events --region=us-central1 --format="yaml" | grep -A 10 traffic
```

**Solutions:**
```bash
# 1. Gradual traffic migration
gcloud run services update-traffic nba-scraper-events \
  --to-revisions=NEW_REVISION=50,OLD_REVISION=50 \
  --region=us-central1

# 2. Rollback if needed
gcloud run services update-traffic nba-scraper-events \
  --to-revisions=OLD_REVISION=100 \
  --region=us-central1

# 3. Check health endpoint
curl -f https://SERVICE_URL/health
```

#### Issue: Cold Start Performance
**Symptoms:**
- First request takes >10 seconds
- Timeout errors on initial requests
- Poor user experience

**Diagnosis:**
```bash
# Check cold start metrics
gcloud monitoring metrics list --filter="resource.type=cloud_run_revision" | grep startup

# Check container resource allocation
gcloud run services describe nba-scraper-events --region=us-central1 --format="yaml" | grep -A 5 resources
```

**Solutions:**
```python
# 1. Optimize application startup
import os
if os.getenv('EAGER_LOAD'):
    # Pre-load heavy dependencies
    import pandas as pd
    import numpy as np
    # Pre-connect to external services
    health_check()

# 2. Use minimum instances for critical services
```

```bash
gcloud run services update nba-scraper-events \
  --min-instances=1 \
  --region=us-central1
```

## Data and Storage Issues

### 🗄️ **Cloud Storage Issues**

#### Issue: File Upload/Download Failures
**Symptoms:**
- "Permission denied" errors
- "Object not found" errors
- Slow upload/download times

**Diagnosis:**
```bash
# Check bucket permissions
gsutil iam get gs://nba-data-raw

# Test access with service account
gcloud auth activate-service-account --key-file=service-account.json
gsutil ls gs://nba-data-raw/

# Check object metadata
gsutil stat gs://nba-data-raw/events/2025/01/15/abc123.json
```

**Solutions:**
```bash
# 1. Fix bucket permissions
gsutil iam ch serviceAccount:nba-scraper-sa@PROJECT_ID.iam.gserviceaccount.com:objectAdmin gs://nba-data-raw

# 2. Create bucket if missing
gsutil mb -p PROJECT_ID -c STANDARD -l us-central1 gs://nba-data-raw

# 3. Set lifecycle policies
gsutil lifecycle set lifecycle.json gs://nba-data-raw
```

```python
# 4. Implement retry logic for storage operations
from google.cloud import storage
from google.api_core import exceptions
import time

def upload_with_retry(bucket, blob_name, data, max_retries=3):
    for attempt in range(max_retries):
        try:
            blob = bucket.blob(blob_name)
            blob.upload_from_string(data)
            return True
        except exceptions.ServiceUnavailable:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
```

### 🗃️ **BigQuery Issues**

#### Issue: Query Timeouts
**Symptoms:**
- "Query timeout" errors
- Slow dashboard loading
- High BigQuery costs

**Diagnosis:**
```bash
# Check query performance
bq query --use_legacy_sql=false --dry_run "SELECT * FROM nba_analytics.events LIMIT 10"

# Check table stats
bq show --schema nba_analytics.events
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_analytics.events"
```

**Solutions:**
```sql
-- 1. Optimize queries with partitioning
CREATE TABLE nba_analytics.events_partitioned
PARTITION BY DATE(game_date)
AS SELECT * FROM nba_analytics.events;

-- 2. Use clustering for frequently filtered columns
CREATE TABLE nba_analytics.player_stats_clustered
PARTITION BY DATE(game_date)
CLUSTER BY player_id, team_id
AS SELECT * FROM nba_analytics.player_stats;

-- 3. Limit query scope
SELECT player_id, points, rebounds, assists
FROM nba_analytics.player_stats
WHERE DATE(game_date) = '2025-01-15'  -- Use partition filter
  AND player_id = 'specific_player'    -- Use cluster filter
```

## Network and Connectivity Issues

### 🌐 **External API Issues**

#### Issue: DNS Resolution Failures
**Symptoms:**
- "Name or service not known" errors
- Intermittent API failures
- Connection timeouts

**Diagnosis:**
```bash
# Test DNS from Cloud Run
gcloud run services replace --region=us-central1 test-service.yaml

# Check from container
docker run --rm nba-scrapers nslookup api.the-odds-api.com
```

**Solutions:**
```python
# 1. Implement DNS caching
import socket
socket.getaddrinfo.cache_clear = lambda: None  # Disable cache clearing

# 2. Use IP addresses if DNS is unreliable
BACKUP_ENDPOINTS = {
    'odds_api': 'https://123.456.789.101/v4/',
    'ball_dont_lie': 'https://987.654.321.102/api/'
}

# 3. Implement circuit breaker for external APIs
from scrapers.utils.circuit_breaker import APICircuitBreaker

odds_api_breaker = APICircuitBreaker(failure_threshold=5, timeout=300)
```

#### Issue: SSL/TLS Certificate Errors
**Symptoms:**
- "SSL certificate verify failed" errors
- "CERTIFICATE_VERIFY_FAILED" exceptions
- HTTPS connection failures

**Solutions:**
```python
# 1. Update CA certificates in container
# Add to Dockerfile:
RUN apt-get update && apt-get install -y ca-certificates

# 2. Handle SSL errors gracefully
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    method_whitelist=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# 3. Fallback to HTTP if HTTPS fails (only for non-sensitive data)
def try_both_protocols(url):
    try:
        return session.get(f"https://{url}")
    except requests.exceptions.SSLError:
        logger.warning(f"HTTPS failed for {url}, trying HTTP")
        return session.get(f"http://{url}")
```

## Monitoring and Alerting Issues

### 📊 **Missing Metrics**

#### Issue: No Custom Metrics Appearing
**Symptoms:**
- Dashboard shows no data
- Alerts not firing
- Missing business metrics

**Diagnosis:**
```bash
# Check if metrics are being sent
gcloud logging read "jsonPayload.message=~'SCRAPER_STATS.*'" --limit=5

# Check metric descriptors
gcloud monitoring metrics-descriptors list --filter="metric.type=custom.googleapis.com/nba/*"
```

**Solutions:**
```python
# 1. Ensure proper metric creation
from google.cloud import monitoring_v3

def create_custom_metric(metric_name, metric_type='GAUGE'):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{PROJECT_ID}"
    
    descriptor = monitoring_v3.MetricDescriptor(
        type=f"custom.googleapis.com/nba/{metric_name}",
        metric_kind=monitoring_v3.MetricDescriptor.MetricKind.GAUGE,
        value_type=monitoring_v3.MetricDescriptor.ValueType.INT64,
        description=f"NBA platform {metric_name} metric"
    )
    
    client.create_metric_descriptor(name=project_name, metric_descriptor=descriptor)

# 2. Send metrics consistently
def send_metric(metric_name, value, labels=None):
    if labels is None:
        labels = {}
    
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{PROJECT_ID}"
    
    series = monitoring_v3.TimeSeries(
        metric=monitoring_v3.Metric(
            type=f"custom.googleapis.com/nba/{metric_name}",
            labels=labels
        ),
        resource=monitoring_v3.MonitoredResource(
            type='global',
            labels={'project_id': PROJECT_ID}
        ),
        points=[monitoring_v3.Point(
            interval=monitoring_v3.TimeInterval(
                end_time={"seconds": int(time.time())}
            ),
            value=monitoring_v3.TypedValue(int64_value=value)
        )]
    )
    
    client.create_time_series(name=project_name, time_series=[series])
```

## Emergency Procedures

### 🚨 **Service Outage Response**

#### 1. **Immediate Assessment**
```bash
# Quick health check all services
./bin/emergency_health_check.sh

# Check error rates
gcloud logs read "resource.type=cloud_run_revision AND severity=ERROR" --limit=50 --format="table(timestamp,severity,resource.labels.service_name,textPayload)"
```

#### 2. **Rollback Procedure**
```bash
# List recent revisions
gcloud run revisions list --service=nba-scraper-events --region=us-central1

# Rollback to last known good revision
gcloud run services update-traffic nba-scraper-events \
  --to-revisions=LAST_GOOD_REVISION=100 \
  --region=us-central1

# Verify rollback
curl -f https://SERVICE_URL/health
```

#### 3. **Emergency Scaling**
```bash
# Scale down if resource issues
gcloud run services update nba-scraper-events \
  --max-instances=1 \
  --region=us-central1

# Scale up if high demand
gcloud run services update nba-scraper-events \
  --max-instances=50 \
  --region=us-central1
```

### 🔧 **Data Recovery Procedures**

#### Missing Data Recovery
```bash
# 1. Check Cloud Storage for raw data
gsutil ls -la gs://nba-data-raw/events/2025/01/15/

# 2. Reprocess from raw data
python -m processors.events_processor --reprocess-date 2025-01-15

# 3. Regenerate reports if needed
python -m reportgen.player_reports --regenerate-date 2025-01-15
```

#### BigQuery Data Corruption
```sql
-- 1. Check data integrity
SELECT DATE(game_date), COUNT(*) as record_count
FROM nba_analytics.events
WHERE DATE(game_date) >= '2025-01-15'
GROUP BY DATE(game_date)
ORDER BY DATE(game_date);

-- 2. Restore from backup
CREATE TABLE nba_analytics.events_backup_20250115
AS SELECT * FROM nba_analytics.events
WHERE DATE(game_date) = '2025-01-15';

-- 3. Delete corrupted data and reload
DELETE FROM nba_analytics.events WHERE DATE(game_date) = '2025-01-15';
-- Then reprocess from raw data
```

---

**Quick Reference Commands:**
```bash
# Service health
./bin/check_service_health.sh

# View recent errors  
gcloud logs read "severity=ERROR" --limit=20

# Rollback service
gcloud run services update-traffic SERVICE --to-revisions=OLD_REVISION=100

# Scale service
gcloud run services update SERVICE --max-instances=10

# Test endpoint
curl -f https://SERVICE_URL/health
```
