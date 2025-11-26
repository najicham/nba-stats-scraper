# Phase 1 Orchestration - Deployment Guide
## From Local Testing to Production

**Status:** All local tests passing ✅  
**Version:** 2.2.2 (Orchestration-enabled)  
**Date:** November 11, 2025

---

## 📋 Pre-Deployment Checklist

Before deploying, ensure you have:

- ✅ Flask service v2.2.2 with orchestration endpoints
- ✅ Updated Dockerfile with orchestration & config directories
- ✅ All 7 local endpoint tests passing
- ✅ BigQuery tables created (nba_orchestration dataset)
- ✅ workflows.yaml configured with 7 workflows

---

## 🚀 Step 1: Update Local Files (5 minutes)

Replace your local files with the fixed versions:

```bash
# Navigate to project root
cd ~/code/nba-stats-scraper

# Backup current files
cp scrapers/main_scraper_service.py scrapers/main_scraper_service.py.backup
cp scrapers/Dockerfile scrapers/Dockerfile.backup

# Copy fixed files from downloads
cp ~/Downloads/main_scraper_service.py scrapers/
cp ~/Downloads/Dockerfile scrapers/

# Make test script executable
cp ~/Downloads/test_orchestration_endpoints.sh .
chmod +x test_orchestration_endpoints.sh
```

---

## 🧪 Step 2: Test Locally with Fixed Code (10 minutes)

### 2.1 Restart Flask Service

```bash
# Stop current Flask process (Ctrl+C in running terminal)

# Start with new code
python -m scrapers.main_scraper_service --port 8080
```

### 2.2 Run Comprehensive Test Suite

In another terminal:

```bash
# Run all endpoint tests
./test_orchestration_endpoints.sh

# Expected: All 7 tests should pass
```

### 2.3 Manual Verification (if test script has issues)

```bash
# Test 1: Health - Should show version 2.2.2
curl -s http://localhost:8080/health | jq '.version, .components.orchestration'

# Test 2: Evaluate workflows
curl -s -X POST http://localhost:8080/evaluate | jq '.status, .workflows_evaluated'

# Test 3: Cleanup processor
curl -s -X POST http://localhost:8080/cleanup -H "Content-Type: application/json" -d '{}' | jq '.status'

# Test 4: Trigger workflow (should now work!)
curl -s -X POST http://localhost:8080/trigger-workflow \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "morning_operations"}' | jq
```

**All tests must pass before proceeding to deployment!**

---

## 🐳 Step 3: Build Docker Image Locally (Optional, 5 minutes)

Test Docker build before deploying to Cloud Run:

```bash
cd scrapers/

# Build image
docker build -t nba-scrapers:v2.2.2 .

# Test locally with Docker
docker run -p 8080:8080 \
  -e GCP_PROJECT_ID=nba-props-platform \
  nba-scrapers:v2.2.2

# In another terminal, test health
curl http://localhost:8080/health | jq
```

**If Docker build fails, STOP and debug before Cloud Run deployment.**

---

## ☁️ Step 4: Deploy to Cloud Run (15 minutes)

### 4.1 Deploy Using Existing Script

```bash
# Navigate to project root
cd ~/code/nba-stats-scraper

# Ensure .env file has all required variables
cat .env | grep -E 'BREVO|EMAIL'

# Deploy (this uses your existing deploy_scrapers_simple.sh)
./deploy_scrapers_simple.sh
```

### 4.2 Verify Deployment

The script will:
1. Copy Dockerfile to root
2. Deploy to Cloud Run
3. Run health check
4. Show service URL

**Expected output:**
```
✅ Deployment completed successfully!
🔗 Service URL: https://nba-scrapers-xxxxx.run.app
📊 Available scrapers: 33
```

### 4.3 Test Production Endpoints

```bash
# Set your Cloud Run URL
export SERVICE_URL="https://nba-scrapers-xxxxx.run.app"

# Run test suite against production
./test_orchestration_endpoints.sh $SERVICE_URL

# Or manually test
curl $SERVICE_URL/health | jq '.components.orchestration'
curl -X POST $SERVICE_URL/evaluate | jq '.decisions | length'
```

**All 7 tests should pass in production!**

---

## ⏰ Step 5: Create Cloud Scheduler Jobs (15 minutes)

### 5.1 Get Service Account and URL

```bash
# Get Cloud Run service URL
SERVICE_URL=$(gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format="value(status.url)")

# Service account (already exists)
SERVICE_ACCOUNT="nba-scrapers@nba-props-platform.iam.gserviceaccount.com"

echo "Service URL: $SERVICE_URL"
echo "Service Account: $SERVICE_ACCOUNT"
```

### 5.2 Create Scheduler Jobs

**Job 1: Master Controller (Hourly)**

Evaluates all workflows and logs decisions.

```bash
gcloud scheduler jobs create http master-controller-hourly \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/evaluate" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --description="Evaluate all workflows hourly and log decisions"
```

**Job 2: Cleanup Processor (Every 15 minutes)**

Detects and fixes missing scraper data.

```bash
gcloud scheduler jobs create http cleanup-processor-15min \
  --location=us-central1 \
  --schedule="*/15 * * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/cleanup" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{}' \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --description="Check for missing scraper files and republish"
```

**Job 3: Daily Schedule Lock (5 AM ET)**

Generates expected daily schedule for monitoring.

```bash
gcloud scheduler jobs create http daily-schedule-lock \
  --location=us-central1 \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/generate-daily-schedule" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{}' \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --description="Generate daily expected schedule at 5 AM ET (10 UTC)"
```

### 5.3 Verify Scheduler Jobs

```bash
# List all scheduler jobs
gcloud scheduler jobs list --location=us-central1

# Expected jobs:
# - master-controller-hourly (every hour)
# - cleanup-processor-15min (every 15 minutes)
# - daily-schedule-lock (daily at 5 AM ET)
```

### 5.4 Test Manual Execution

```bash
# Test master controller
gcloud scheduler jobs run master-controller-hourly --location=us-central1

# Wait a few seconds, then check BigQuery
bq query --use_legacy_sql=false "
SELECT 
  decision_time,
  workflow_name,
  action,
  reason
FROM \`nba-props-platform.nba_orchestration.workflow_decisions\`
ORDER BY decision_time DESC
LIMIT 5
"

# Test cleanup processor
gcloud scheduler jobs run cleanup-processor-15min --location=us-central1

# Test schedule generator
gcloud scheduler jobs run daily-schedule-lock --location=us-central1
```

---

## 🧪 Step 6: End-to-End Validation (30 minutes)

### 6.1 Monitor BigQuery Tables

Check data is being written:

```sql
-- Check workflow decisions (should update hourly)
SELECT 
  DATE(decision_time) as date,
  COUNT(*) as decisions,
  COUNT(DISTINCT workflow_name) as workflows
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time) = CURRENT_DATE()
GROUP BY date;

-- Check cleanup operations (should update every 15 min)
SELECT 
  DATE(operation_time) as date,
  COUNT(*) as operations,
  SUM(files_checked) as total_files_checked,
  SUM(missing_files_found) as total_missing
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(operation_time) = CURRENT_DATE()
GROUP BY date;

-- Check daily schedule (should have today's entry)
SELECT 
  schedule_date,
  games_count,
  first_game_time,
  last_game_time
FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE schedule_date = CURRENT_DATE()
ORDER BY created_at DESC
LIMIT 1;
```

### 6.2 Monitor Cloud Logging

```bash
# View recent logs from Cloud Run
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-scrapers \
  AND severity>=INFO" \
  --limit=50 \
  --format=json

# Filter for orchestration logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-scrapers \
  AND (textPayload=~'Master Controller' OR textPayload=~'cleanup processor')" \
  --limit=20 \
  --format=json
```

### 6.3 Verify Workflow Execution

Wait for scheduled execution (on the hour), then check:

```sql
-- Check if scrapers are being executed by workflows
SELECT 
  DATE(triggered_at) as date,
  workflow,
  COUNT(*) as executions,
  COUNT(DISTINCT scraper_name) as unique_scrapers,
  COUNTIF(status = 'success') as successful,
  COUNTIF(status = 'failed') as failed
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) = CURRENT_DATE()
GROUP BY date, workflow
ORDER BY date DESC, executions DESC;
```

### 6.4 24-Hour Monitoring Plan

Check these metrics over the first 24 hours:

**Hour 1-3:**
- ✅ Master controller running every hour
- ✅ Cleanup processor running every 15 minutes
- ✅ No errors in Cloud Logging
- ✅ BigQuery tables updating

**Hour 4-8:**
- ✅ Workflow decisions logged correctly
- ✅ Morning operations running if games scheduled
- ✅ Betting lines workflow executing
- ✅ Email alerts working (if configured)

**Hour 8-24:**
- ✅ Post-game workflows running after games
- ✅ All expected scrapers executing
- ✅ No missing data detected by cleanup
- ✅ System stable under normal operations

---

## 🚨 Troubleshooting

### Issue: Docker build fails with "orchestration not found"

**Cause:** Dockerfile not updated with orchestration directories  
**Fix:**
```bash
# Verify Dockerfile has these lines:
grep -A 2 "Copy orchestration" scrapers/Dockerfile

# Should see:
# COPY orchestration/ ./orchestration/
# COPY config/ ./config/
```

### Issue: Cloud Run endpoint returns 500 errors

**Cause:** Missing environment variables or IAM permissions  
**Fix:**
```bash
# Check Cloud Run environment variables
gcloud run services describe nba-scrapers --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Should include: GCP_PROJECT_ID

# Check service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:nba-scrapers@nba-props-platform.iam.gserviceaccount.com"
```

### Issue: Scheduler jobs fail with 403 Forbidden

**Cause:** OIDC authentication issue  
**Fix:**
```bash
# Verify service account has Cloud Run Invoker role
gcloud run services add-iam-policy-binding nba-scrapers \
  --region=us-west2 \
  --member="serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

### Issue: Workflow trigger says "No scrapers defined"

**Cause:** workflows.yaml structure mismatch  
**Fix:** Scrapers should be at `execution_plan.scrapers` as strings:
```yaml
workflow_name:
  execution_plan:
    scrapers:
      - scraper_name_1
      - scraper_name_2
```

### Issue: BigQuery writes failing

**Cause:** Service account missing BigQuery permissions  
**Fix:**
```bash
# Grant BigQuery Data Editor role
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

---

## 📊 Success Metrics

Phase 1 orchestration is successfully deployed when:

- ✅ All 7 Flask endpoints return 200 OK
- ✅ Master controller runs hourly without errors
- ✅ Cleanup processor runs every 15 minutes
- ✅ Daily schedule generates at 5 AM ET
- ✅ Workflow decisions logged to BigQuery
- ✅ Scrapers executing based on workflow decisions
- ✅ No errors in Cloud Logging for 24 hours
- ✅ All BigQuery tables updating correctly

---

## 🎯 What's Next

After successful deployment:

1. **Monitor for 24-48 hours** to ensure stability
2. **Tune workflow schedules** based on actual game times
3. **Add email alerting** for failed workflow executions
4. **Create monitoring dashboards** for orchestration metrics
5. **Document operational procedures** for workflow management

---

## 📝 Quick Reference Commands

```bash
# Check deployment status
gcloud run services describe nba-scrapers --region=us-west2

# View recent logs
gcloud logging read "resource.labels.service_name=nba-scrapers" --limit=20

# Test health endpoint
curl https://nba-scrapers-xxxxx.run.app/health | jq

# Manually trigger workflow evaluation
curl -X POST https://nba-scrapers-xxxxx.run.app/evaluate

# Run scheduler job manually
gcloud scheduler jobs run master-controller-hourly --location=us-central1

# Query workflow decisions
bq query --use_legacy_sql=false "SELECT * FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` ORDER BY decision_time DESC LIMIT 10"
```

---

**Deployment Guide Version:** 1.0  
**Last Updated:** November 11, 2025  
**Next Review:** After 24-hour monitoring period
