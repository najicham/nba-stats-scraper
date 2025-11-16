# NBA Props Orchestration - How It All Works

**File:** `docs/orchestration/01-how-it-works.md`
**Created:** 2025-11-11 20:02 PST
**Last Updated:** 2025-11-15 10:52 PST (reorganization)
**Purpose:** Simple explanation of orchestration deployment and operation
**Status:** Current

---

## 🎯 The Big Picture (Simple Version)

You have **ONE Flask app** that does everything:

```
scrapers/main_scraper_service.py
  ├── Scraper endpoints (26+)
  │   ├── /scraper/bdl-boxscores
  │   ├── /scraper/oddsa-events
  │   └── ... etc
  │
  └── Orchestration endpoints (NEW!)
      ├── /health
      ├── /evaluate-workflows      ← Master Controller
      ├── /generate-daily-schedule ← Schedule Locker
      └── /run-cleanup             ← Cleanup Processor
```

**Already Deployed:**
- Service name: `nba-scrapers`
- Has: All 26+ scraper endpoints
- Missing: Cloud Scheduler jobs to call orchestration endpoints

**What We Need to Add:**
- 3 Cloud Scheduler jobs that call the orchestration endpoints
- That's it!

---

## 🏗️ Current Architecture

### What You Have Now:

```
Cloud Run Service: nba-scrapers
  ↓ (deployed via deploy_scrapers_simple.sh)
Flask App: main_scraper_service.py
  ↓
Endpoints:
  ✅ /scraper/* endpoints working
  ✅ /evaluate-workflows exists (tested locally)
  ✅ /generate-daily-schedule exists (tested locally)
  ✅ /run-cleanup exists (tested locally)
```

### What's Missing:

```
❌ Cloud Scheduler Job #1: Daily Schedule Locker
   Trigger: /generate-daily-schedule at 5 AM ET

❌ Cloud Scheduler Job #2: Master Controller
   Trigger: /evaluate-workflows every hour 6 AM-11 PM ET

❌ Cloud Scheduler Job #3: Cleanup Processor
   Trigger: /run-cleanup every 15 minutes
```

---

## 🚀 Tomorrow's Deployment Plan

### Step 1: Verify Current Deployment (5 minutes)

**Check if orchestration endpoints exist:**

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format="value(status.url)")

echo "Service URL: ${SERVICE_URL}"

# Test health endpoint (should work)
curl -s "${SERVICE_URL}/health" | jq '.'

# Test orchestration endpoints (should return JSON or error)
curl -s -X POST "${SERVICE_URL}/generate-daily-schedule" | jq '.'
```

**Expected Results:**
- ✅ `/health` returns JSON with status
- ⚠️ `/generate-daily-schedule` might work OR return error (either is fine - we just need it to exist!)

---

### Step 2: Create Cloud Scheduler Jobs (10 minutes)

**Simple script to add scheduler jobs:**

```bash
#!/bin/bash
# add_scheduler_jobs.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="nba-scrapers"

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --region=${REGION} \
  --format="value(status.url)")

echo "Adding scheduler jobs for: ${SERVICE_URL}"

# Create service account if needed
gcloud iam service-accounts create scheduler-orchestration \
  --display-name="Cloud Scheduler - Orchestration" \
  --project=${PROJECT_ID} 2>/dev/null || true

# Grant invoker permission
gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
  --member="serviceAccount:scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region=${REGION}

# Job 1: Schedule Locker (5 AM ET = 10 AM UTC)
gcloud scheduler jobs create http daily-schedule-locker \
  --location=${REGION} \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/generate-daily-schedule" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
  2>/dev/null || echo "Job exists, updating..."

gcloud scheduler jobs update http daily-schedule-locker \
  --location=${REGION} \
  --schedule="0 10 * * *" \
  --uri="${SERVICE_URL}/generate-daily-schedule" \
  2>/dev/null || true

# Job 2: Master Controller (Hourly 6 AM-11 PM ET)
gcloud scheduler jobs create http master-controller-hourly \
  --location=${REGION} \
  --schedule="0 6-23 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/evaluate-workflows" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
  2>/dev/null || echo "Job exists, updating..."

gcloud scheduler jobs update http master-controller-hourly \
  --location=${REGION} \
  --schedule="0 6-23 * * *" \
  --uri="${SERVICE_URL}/evaluate-workflows" \
  2>/dev/null || true

# Job 3: Cleanup (Every 15 min)
gcloud scheduler jobs create http cleanup-processor \
  --location=${REGION} \
  --schedule="*/15 * * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/run-cleanup" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
  2>/dev/null || echo "Job exists, updating..."

gcloud scheduler jobs update http cleanup-processor \
  --location=${REGION} \
  --schedule="*/15 * * * *" \
  --uri="${SERVICE_URL}/run-cleanup" \
  2>/dev/null || true

echo "✅ Scheduler jobs created!"
gcloud scheduler jobs list --location=${REGION}
```

---

### Step 3: Monitor First Runs (Throughout day)

**Tomorrow (Nov 12) Timeline:**

```
5:00 AM ET - Schedule Locker runs
  ↓ Check BigQuery
  ↓ Query: SELECT * FROM nba_orchestration.daily_expected_schedule 
           WHERE date = '2025-11-12'

6:00 AM ET - Master Controller first run
  ↓ Check BigQuery
  ↓ Query: SELECT * FROM nba_orchestration.workflow_decisions 
           WHERE DATE(decision_time) = '2025-11-12'

Every 15 min - Cleanup Processor
  ↓ Check BigQuery
  ↓ Query: SELECT * FROM nba_orchestration.cleanup_operations 
           WHERE DATE(cleanup_time) = '2025-11-12'
```

---

## 📊 Monitoring Gameplan

### Hour 1 (5-6 AM ET): Schedule Generation

**What to Check:**
```sql
-- Did schedule locker run?
SELECT 
  date,
  workflow_name,
  expected_run_time,
  reason
FROM `nba-props-platform.nba_orchestration.daily_expected_schedule`
WHERE date = CURRENT_DATE('America/New_York')
ORDER BY expected_run_time;
```

**Expected:** 5-10 records (one per workflow)

**If Empty:** Check Cloud Scheduler logs:
```bash
gcloud logging read \
  "resource.type=cloud_scheduler_job AND resource.labels.job_id=daily-schedule-locker" \
  --limit=10 \
  --format=json
```

---

### Hour 2 (6-7 AM ET): First Controller Run

**What to Check:**
```sql
-- Did master controller evaluate workflows?
SELECT 
  decision_time,
  workflow_name,
  action,
  reason
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY decision_time DESC;
```

**Expected:** 5-10 records showing RUN, SKIP, or ABORT

**If Empty:** Check Cloud Run logs:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" \
  --limit=50 \
  --format=json
```

---

### Hour 3 (7-8 AM ET): Cleanup Verification

**What to Check:**
```sql
-- Did cleanup processor run?
SELECT 
  cleanup_time,
  files_checked,
  missing_files_found,
  files_republished
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE DATE(cleanup_time, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY cleanup_time DESC
LIMIT 10;
```

**Expected:** Records every 15 minutes

---

### Hour 4-8 (8 AM - 12 PM): Pattern Verification

**What to Check:**

1. **Hourly Controller Runs:**
```sql
SELECT 
  EXTRACT(HOUR FROM decision_time AT TIME ZONE 'America/New_York') as hour_et,
  COUNT(*) as evaluation_count
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY hour_et
ORDER BY hour_et;
```

**Expected:** 1+ evaluation per hour from 6 AM onwards

2. **Workflow Actions:**
```sql
SELECT 
  workflow_name,
  action,
  COUNT(*) as count
FROM `nba-props-platform.nba_orchestration.workflow_decisions`
WHERE DATE(decision_time, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY workflow_name, action
ORDER BY workflow_name, action;
```

**Expected:** Mix of RUN, SKIP, and maybe ABORT actions

---

## 🚨 Troubleshooting Guide

### Issue: Schedule locker didn't run at 5 AM

**Check:**
```bash
# 1. Does job exist?
gcloud scheduler jobs describe daily-schedule-locker --location=us-west2

# 2. Check execution history
gcloud logging read \
  "resource.type=cloud_scheduler_job AND resource.labels.job_id=daily-schedule-locker" \
  --limit=5
```

**Fix:**
```bash
# Manually trigger to test
gcloud scheduler jobs run daily-schedule-locker --location=us-west2
```

---

### Issue: Master controller not evaluating

**Check:**
```bash
# 1. Does job exist?
gcloud scheduler jobs describe master-controller-hourly --location=us-west2

# 2. Check Cloud Run logs for errors
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND severity>=ERROR" \
  --limit=20
```

**Fix:**
```bash
# Manually trigger to test
gcloud scheduler jobs run master-controller-hourly --location=us-west2
```

---

### Issue: Errors in Cloud Run logs

**Common Errors:**

**Error:** "Table not found: nba_raw.bdl_box_scores"
- ✅ **EXPECTED** - Phase 2 tables don't exist yet
- ✅ Master controller handles gracefully
- ✅ No action needed

**Error:** "Missing required option [season]"
- ✅ **EXPECTED** - Some scrapers need parameters (Week 2 work)
- ✅ Orchestration logs the failure
- ✅ No action needed now

**Error:** "Failed to insert rows into BigQuery"
- ❌ **UNEXPECTED** - Should be fixed now
- Check datetime serialization
- Review scraper_base.py fixes

---

## 📋 Day 1 Success Criteria

### ✅ Minimum Success (Day 1):

- [ ] Schedule locker ran at 5 AM ET
- [ ] Daily schedule has 5+ records in BigQuery
- [ ] Master controller ran at 6 AM, 7 AM, 8 AM
- [ ] Workflow decisions logged to BigQuery
- [ ] Cleanup processor ran every 15 minutes
- [ ] No critical errors in Cloud Run logs

### 🎯 Full Success (Day 1):

- [ ] All minimum success criteria met
- [ ] Can query BigQuery and see all 3 tables populated
- [ ] Scheduler jobs listed in Cloud Scheduler
- [ ] Manual trigger of each job works
- [ ] Understand the data in each BigQuery table

---

## 🗂️ About Dockerfiles

### Your Current Setup:

```
docker/
├── base.Dockerfile           ← Base image for all services
├── processor.Dockerfile      ← Phase 2-4 processors
├── predictions-*.Dockerfile  ← Phase 5
└── ... (other services)

scrapers/
└── Dockerfile                ← Scraper service (has orchestration too!)
```

### Recommendation: Keep It Simple

**Option 1: Use Existing (Simplest)**
- Keep using `scrapers/Dockerfile`
- It already includes orchestration code
- Just add Cloud Scheduler jobs
- ✅ **RECOMMENDED FOR NOW**

**Option 2: Separate Later (Future)**
- Create `docker/orchestration.Dockerfile`
- Split scraper and orchestration services
- More complex, but cleaner architecture
- Do this in Week 3+ when system is proven

### For Tomorrow:

**Do:** Add scheduler jobs to existing `nba-scrapers` service  
**Don't:** Create new Dockerfiles or services  
**Why:** Simplest path to working system

---

## 📅 Week 1 Schedule

### Day 1 (Tomorrow - Nov 12):

**Morning:**
- [ ] 9:00 AM: Add Cloud Scheduler jobs
- [ ] 9:15 AM: Manually trigger schedule locker to test
- [ ] 9:30 AM: Manually trigger master controller to test
- [ ] 10:00 AM: Check BigQuery for data

**Afternoon:**
- [ ] 1:00 PM: Review logs from morning runs
- [ ] 2:00 PM: Document any errors
- [ ] 3:00 PM: Verify cleanup processor running every 15 min

**Evening:**
- [ ] 6:00 PM: Check full day of workflow decisions
- [ ] 7:00 PM: Write summary of Day 1

---

### Day 2-3 (Nov 13-14):

**Goals:**
- [ ] Verify consistent schedule generation at 5 AM
- [ ] Verify hourly controller runs 6 AM - 11 PM
- [ ] Identify any patterns in errors
- [ ] Document actual vs expected behavior

---

### Day 4-5 (Nov 15-16):

**Goals:**
- [ ] Set up basic Grafana dashboard
- [ ] Create first monitoring query
- [ ] Test manual workflow triggering
- [ ] Plan Week 2 improvements

---

## 🎯 Success Metrics

### Day 1:
- ✅ 3 scheduler jobs created
- ✅ At least 1 successful run of each
- ✅ Data in all 3 BigQuery tables

### Week 1:
- ✅ 7 consecutive days of schedule generation
- ✅ Hourly controller runs (6 AM - 11 PM)
- ✅ <10 critical errors total
- ✅ Basic Grafana dashboard working

### Week 2:
- ✅ Tune alert thresholds
- ✅ Document decision patterns
- ✅ Plan scraper parameter passing
- ✅ Prepare for Phase 2 deployment

---

## 📚 Quick Reference

**Service Info:**
- Name: `nba-scrapers`
- Region: `us-west2`
- Endpoints: `/health`, `/evaluate-workflows`, `/generate-daily-schedule`, `/run-cleanup`

**Scheduler Jobs:**
- `daily-schedule-locker`: 5 AM ET
- `master-controller-hourly`: 6-11 PM ET
- `cleanup-processor`: Every 15 min

**BigQuery Tables:**
- `nba_orchestration.daily_expected_schedule`
- `nba_orchestration.workflow_decisions`
- `nba_orchestration.cleanup_operations`
- `nba_orchestration.scraper_execution_log`

**Key Commands:**
```bash
# List scheduler jobs
gcloud scheduler jobs list --location=us-west2

# Manually trigger
gcloud scheduler jobs run JOB_NAME --location=us-west2

# View logs
gcloud logging read "resource.type=cloud_run_revision" --limit=50

# Check service
gcloud run services describe nba-scrapers --region=us-west2
```

---

**Document Version:** 1.0  
**Status:** Ready for Tomorrow's Deployment  
**Next Update:** After Day 1 (Nov 12 evening)
