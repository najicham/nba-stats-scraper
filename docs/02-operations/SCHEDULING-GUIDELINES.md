# Cloud Scheduler Guidelines

**Last Updated:** 2026-01-18
**Status:** Production Standard
**Scope:** All Cloud Scheduler jobs in NBA Props Platform

---

## 🎯 Purpose

This document establishes scheduling best practices to prevent:
- **Service conflicts** (multiple jobs calling same service simultaneously)
- **Resource contention** (overwhelming Cloud Run instances)
- **Data race conditions** (concurrent operations on same data)
- **503 errors** (service unavailable due to capacity)

---

## ⚠️ Critical Rule: Respect Data Pipeline Dependencies

### The Golden Rule

**Phase N must complete BEFORE Phase N+1 begins**

```
Phase 1 (Scrapers) → Phase 2 (Raw) → Phase 3 (Analytics) → Phase 4 (Precompute) → Phase 5 (Predictions) → Phase 6 (Export)
```

**Minimum Time Between Phases:** 30 minutes

**Why:** Each phase depends on the previous phase's output. Starting too early causes:
- Missing data
- Auto-heal triggers
- Duplicate processing
- Service 503 errors

---

## 📋 Current Production Schedule (as of 2026-01-18)

### Morning Pipeline (Yesterday's Games)

| Time (ET) | Time (UTC) | Job Name | Service | Purpose |
|-----------|------------|----------|---------|---------|
| 6:30 AM | 11:30 | `daily-yesterday-analytics` | nba-phase3-analytics | Process yesterday's boxscores |
| **7:00 AM** | **12:00** | `grading-morning` | phase5b-grading | Grade yesterday's predictions |
| 6:00 AM | 11:00 | `overnight-phase4` | nba-phase4-precompute | Precompute features |

**Key Fix (Session 98):** `grading-morning` moved from 6:30 AM to 7:00 AM to avoid conflict with `daily-yesterday-analytics`

### Same-Day Pipeline

| Time (ET) | Time (UTC) | Job Name | Service | Purpose |
|-----------|------------|----------|---------|---------|
| 10:30 AM | 15:30 | `same-day-phase3` | nba-phase3-analytics | Process today's games |
| 11:00 AM | 16:00 | `grading-daily` | phase5b-grading | Main daily grading |
| 11:00 AM | 16:00 | `same-day-phase4` | nba-phase4-precompute | Same-day features |
| 5:00 PM | 22:00 | `same-day-phase3-tomorrow` | nba-phase3-analytics | Tomorrow's games |
| 5:30 PM | 22:30 | `same-day-phase4-tomorrow` | nba-phase4-precompute | Tomorrow's features |

### Monitoring & Alerts

| Time (ET) | Time (UTC) | Job Name | Purpose |
|-----------|------------|----------|---------|
| Every 15 min (10 PM - 2 AM) | 03:00-07:00 | `grading-readiness-check` | Check if grading can run |
| 2:30 AM | 07:30 | `grading-latenight` | Grade late games/OT |
| 5:00 AM | 10:00 | `grading-delay-alert-job` | Alert on grading delays |
| 3:30 PM | 20:30 | `nba-grading-alerts-daily` | Daily grading summary |

### Phase 6 (Export)

| Time (ET) | Time (UTC) | Job Name | Purpose |
|-----------|------------|----------|---------|
| 12:00 AM | 05:00 | `phase6-daily-results` | Export daily results |
| 1:00 AM (Sun) | 06:00 | `phase6-player-profiles` | Weekly player updates |
| 8:00 AM | 13:00 | `phase6-tonight-picks` | Tonight's recommendations |
| 1-6 PM (hourly) | 18:00-23:00 | `phase6-hourly-trends` | Hourly trend updates |

---

## 🚨 Conflict Prevention Checklist

Before creating or modifying a Cloud Scheduler job:

### 1. Check for Time Conflicts

```bash
# List all jobs at a specific time (example: 11:30 UTC)
gcloud scheduler jobs list --location us-west2 --format="table(name,schedule,timeZone)" | \
  awk '{print $2}' | grep "30 6"  # 6:30 AM in any timezone
```

### 2. Identify Service Dependencies

**Question:** Does this job depend on another service's output?

- If **YES**: Schedule at least 30 minutes AFTER the upstream service
- If **NO**: Proceed with caution, may still share resources

### 3. Check Service Capacity

**Question:** What Cloud Run service will this job call?

```bash
# Check service capacity
gcloud run services describe SERVICE_NAME --region us-west2 \
  --format="value(spec.template.spec.containerConcurrency,spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"
```

**Formula:** Max Capacity = `containerConcurrency` × `maxScale`

**Example:**
- Phase 3: 10 concurrency × 10 instances = 100 max requests
- If scheduling 3 jobs at same time, each gets ~33 requests max
- Risk: One large job could starve the others → 503 errors

### 4. Test Before Deploying

```bash
# Manually trigger job to test
gcloud scheduler jobs run JOB_NAME --location us-west2

# Monitor logs for errors
gcloud functions logs read FUNCTION_NAME --region us-west2 --limit 50

# Or for Cloud Run
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="SERVICE_NAME"' \
  --limit 50 --freshness=10m
```

---

## 📐 Scheduling Patterns

### Pattern 1: Sequential Pipeline (RECOMMENDED)

**Use when:** Jobs have strict dependencies

```
6:00 AM - Phase 3 starts
6:30 AM - Phase 3 completes (avg 15-20 min)
7:00 AM - Phase 5 (Grading) starts ← Safe!
```

**Buffer:** 30 minutes minimum

### Pattern 2: Parallel Processing

**Use when:** Jobs are completely independent

```
6:00 AM - Export Job A (Cloud Run Service X)
6:00 AM - Export Job B (Cloud Run Service Y)
```

**Requirement:** Different Cloud Run services

### Pattern 3: Staggered Batch

**Use when:** Multiple jobs target same service

```
10:00 AM - Job 1
10:15 AM - Job 2
10:30 AM - Job 3
```

**Buffer:** 15 minutes minimum

---

## 🔧 Timezone Best Practices

### Standard: America/New_York

**Why:** NBA schedule operates on Eastern Time

**All jobs should use:** `--time-zone="America/New_York"`

**Conversion Reference:**

| ET | UTC (Winter) | UTC (Summer/DST) |
|----|--------------|------------------|
| 12:00 AM | 05:00 | 04:00 |
| 6:00 AM | 11:00 | 10:00 |
| 12:00 PM | 17:00 | 16:00 |
| 6:00 PM | 23:00 | 22:00 |

**DST Transitions:**
- Spring forward: Second Sunday in March (2:00 AM → 3:00 AM)
- Fall back: First Sunday in November (2:00 AM → 1:00 AM)

**Important:** Cloud Scheduler handles DST automatically when using named timezones

---

## 🛠️ Creating a New Scheduled Job

### Template

```bash
gcloud scheduler jobs create http JOB_NAME \
  --location us-west2 \
  --schedule="CRON_EXPRESSION" \
  --time-zone="America/New_York" \
  --uri="https://SERVICE_URL/endpoint" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"key":"value"}' \
  --oidc-service-account-email="SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com" \
  --oidc-token-audience="https://SERVICE_URL" \
  --description="Clear description of what this job does and when it runs"
```

### For Pub/Sub Jobs

```bash
gcloud scheduler jobs create pubsub JOB_NAME \
  --location us-west2 \
  --schedule="CRON_EXPRESSION" \
  --time-zone="America/New_York" \
  --topic=TOPIC_NAME \
  --message-body='{"key":"value"}' \
  --description="Clear description"
```

### Cron Expression Examples

```bash
# Every day at 6:30 AM ET
"30 6 * * *"

# Every 15 minutes between 10 PM and 2 AM ET
"*/15 22-23,0-2 * * *"

# Every Sunday at 1:00 AM ET
"0 1 * * 0"

# First day of every month at midnight
"0 0 1 * *"

# Every 30 minutes
"*/30 * * * *"
```

**Tool:** https://crontab.guru/ (for validation)

---

## ⚡ Common Anti-Patterns (AVOID)

### ❌ Anti-Pattern 1: Simultaneous Dependencies

```
6:30 AM - Phase 3 Analytics (generates data)
6:30 AM - Grading (needs Phase 3 data)
```

**Problem:** Grading finds no data, triggers auto-heal, Phase 3 returns 503

**Fix:** Stagger by 30 minutes

---

### ❌ Anti-Pattern 2: No Buffer Time

```
6:00 AM - Phase 3 starts (takes 20 minutes)
6:15 AM - Phase 5 starts (needs Phase 3 data)
```

**Problem:** Phase 3 not done yet, Phase 5 fails or triggers redundant Phase 3

**Fix:** Wait 30 minutes, not 15

---

### ❌ Anti-Pattern 3: Hardcoded Times in Different Timezones

```
Job A: 11:30 UTC
Job B: 6:30 America/New_York
Job C: 8:30 America/Los_Angeles
```

**Problem:** Hard to see conflicts, DST breaks things

**Fix:** Standardize on America/New_York

---

### ❌ Anti-Pattern 4: No Description

```bash
gcloud scheduler jobs create http my-job --schedule="0 6 * * *" ...
# No --description provided
```

**Problem:** 6 months later, no one knows what this does

**Fix:** Always add meaningful description

---

## 📊 Monitoring Scheduled Jobs

### Check Job Status

```bash
# List all jobs with their state
gcloud scheduler jobs list --location us-west2 \
  --format="table(name,schedule,state,lastAttemptTime)"

# Get specific job details
gcloud scheduler jobs describe JOB_NAME --location us-west2
```

### Check Recent Executions

```bash
# View job execution history (Cloud Logging)
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="JOB_NAME"' \
  --limit 50 --format=json

# Check for failures
gcloud logging read 'resource.type="cloud_scheduler_job" AND severity>=ERROR' \
  --limit 20 --freshness=7d
```

### Set Up Alerts

```bash
# Alert on scheduler job failures
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Scheduler Job Failures" \
  --condition-display-name="Job failed" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=300s \
  --condition-filter='resource.type="cloud_scheduler_job" AND severity="ERROR"'
```

---

## 🔄 Updating Existing Jobs

### Change Schedule

```bash
gcloud scheduler jobs update http JOB_NAME \
  --location us-west2 \
  --schedule="NEW_CRON_EXPRESSION"
```

### Change Description

```bash
gcloud scheduler jobs update http JOB_NAME \
  --location us-west2 \
  --description="Updated description with new details"
```

### Pause/Resume Job

```bash
# Pause
gcloud scheduler jobs pause JOB_NAME --location us-west2

# Resume
gcloud scheduler jobs resume JOB_NAME --location us-west2
```

---

## 📝 Change Log Process

When modifying a scheduled job:

1. **Document the change** in this file under "Change History"
2. **Update the schedule table** above
3. **Test the change** with manual trigger
4. **Monitor** for 3 days to ensure no issues
5. **Notify team** in Slack #engineering channel

### Change History

| Date | Job Name | Change | Reason | Session |
|------|----------|--------|--------|---------|
| 2026-01-18 | grading-morning | Schedule: 6:30 AM → 7:00 AM ET | Fix conflict with daily-yesterday-analytics causing 503 errors | Session 98 |

---

## 🚨 Incident Response

### Symptom: Job Not Running

**Check:**
```bash
# Is job enabled?
gcloud scheduler jobs describe JOB_NAME --location us-west2 --format="value(state)"

# When was last successful run?
gcloud scheduler jobs describe JOB_NAME --location us-west2 --format="value(lastAttemptTime)"
```

**Fix:**
```bash
# Resume if paused
gcloud scheduler jobs resume JOB_NAME --location us-west2

# Manual trigger to test
gcloud scheduler jobs run JOB_NAME --location us-west2
```

---

### Symptom: 503 Errors in Logs

**Root Causes:**
1. **Timing conflict** - Two jobs calling same service
2. **Capacity exceeded** - Too many concurrent requests
3. **Cold start timeout** - Service starting up

**Investigation:**
```bash
# Check what else ran at same time
gcloud logging read 'timestamp>="TIMESTAMP" AND timestamp<="TIMESTAMP"' \
  --format="table(timestamp,resource.labels.service_name)"

# Check service capacity
gcloud run services describe SERVICE_NAME --region us-west2
```

**Fix:**
- Stagger conflicting jobs by 30 minutes
- Increase service max instances (if needed)
- Add CPU boost to reduce cold starts

---

## 📚 Additional Resources

**Cloud Scheduler Documentation:**
- https://cloud.google.com/scheduler/docs

**Cron Expression Validator:**
- https://crontab.guru/

**Project Docs:**
- Phase Pipeline Overview: `/docs/02-architecture/PIPELINE-PHASES.md`
- Cloud Run Services: `/docs/03-infrastructure/CLOUD-RUN-SERVICES.md`
- Incident Runbooks: `/docs/02-operations/runbooks/`

**Related Investigations:**
- Session 98 Phase 3 Investigation: `/docs/09-handoff/SESSION-98-PHASE3-INVESTIGATION.md`

---

## ✅ Pre-Deployment Checklist

Before deploying a new or modified scheduled job:

- [ ] Checked for time conflicts with existing jobs
- [ ] Verified service dependencies (Phase N before Phase N+1)
- [ ] Calculated service capacity requirements
- [ ] Set timezone to `America/New_York`
- [ ] Added clear, descriptive job name and description
- [ ] Tested with manual trigger
- [ ] Monitored logs for errors
- [ ] Documented change in this file's Change History
- [ ] Notified team in Slack

---

**Document Owner:** Engineering Team
**Review Frequency:** Quarterly or after incidents
**Last Reviewed:** 2026-01-18 (Session 98)
