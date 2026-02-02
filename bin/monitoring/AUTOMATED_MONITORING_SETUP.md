# Automated Monitoring Setup

This document explains the automated monitoring system for the NBA Stats Scraper platform.

## Overview

Two critical monitoring checks run automatically on Cloud Scheduler:

| Check | Schedule | Purpose | Alert Level |
|-------|----------|---------|-------------|
| **Weekly Model Drift Check** | Mondays 9 AM ET | Detect model performance degradation | WARNING: <60% hit rate<br>CRITICAL: <55% hit rate |
| **Daily Grading Completeness** | Daily 9 AM ET | Monitor prediction grading pipeline | WARNING: 50-79% coverage<br>CRITICAL: <50% coverage |

## Architecture

```
Cloud Scheduler → Cloud Run Job → BigQuery Query → Slack Alert
     (cron)        (container)      (monitoring)     (webhook)
```

### Components

1. **Monitoring Scripts** (`bin/monitoring/`)
   - `weekly_model_drift_check.sh` - Checks model performance over 4 weeks
   - `check_grading_completeness.sh` - Validates grading pipeline completeness

2. **Dockerfiles** (`deployment/dockerfiles/nba/`)
   - `Dockerfile.weekly-model-drift-check` - Container for drift check
   - `Dockerfile.grading-completeness-check` - Container for grading check

3. **Cloud Run Jobs** (deployed to GCP)
   - `nba-weekly-model-drift-check` - Executes drift monitoring
   - `nba-grading-completeness-check` - Executes grading monitoring

4. **Cloud Scheduler Jobs** (triggers)
   - `weekly-model-drift-check` - Mondays 9 AM ET
   - `daily-grading-completeness-check` - Daily 9 AM ET

## Deployment

### Step 1: Deploy Cloud Run Jobs

Deploy the monitoring jobs using the deployment script:

```bash
# Deploy weekly drift check
./bin/deploy-monitoring-job.sh weekly-model-drift-check

# Deploy daily grading check
./bin/deploy-monitoring-job.sh grading-completeness-check
```

This will:
- Build Docker images from repository root
- Tag with current commit SHA
- Push to Artifact Registry
- Create/update Cloud Run Jobs

### Step 2: Configure Environment Variables

Set Slack webhook URLs for alerts:

```bash
# Weekly drift check (needs both WARNING and ERROR webhooks)
gcloud run jobs update nba-weekly-model-drift-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING,SLACK_WEBHOOK_URL_ERROR=$SLACK_WEBHOOK_ERROR

# Daily grading check (needs WARNING webhook)
gcloud run jobs update nba-grading-completeness-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING
```

**Get webhook URLs from:**
- Slack workspace settings
- 1Password/secrets manager
- Or ask platform admin

### Step 3: Set Up Schedulers

Create Cloud Scheduler jobs to trigger the monitoring:

```bash
# Set up weekly drift check (Mondays 9 AM ET)
./bin/monitoring/setup_weekly_drift_check_scheduler.sh

# Set up daily grading check (Daily 9 AM ET)
./bin/monitoring/setup_daily_grading_check_scheduler.sh
```

This creates scheduler jobs that invoke the Cloud Run Jobs via authenticated HTTP POST.

## Testing

### Test Cloud Run Jobs Directly

Execute jobs manually to verify they work:

```bash
# Test weekly drift check
gcloud run jobs execute nba-weekly-model-drift-check --region=us-west2

# Test grading completeness check
gcloud run jobs execute nba-grading-completeness-check --region=us-west2
```

Watch execution status:

```bash
# List recent executions
gcloud run jobs executions list --job=nba-weekly-model-drift-check --region=us-west2 --limit=5

# View logs from latest execution
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-weekly-model-drift-check"' \
  --limit=50 --format=json
```

### Test Cloud Scheduler Jobs

Trigger schedulers manually (without waiting for schedule):

```bash
# Test weekly drift check scheduler
gcloud scheduler jobs run weekly-model-drift-check --location=us-west2

# Test daily grading check scheduler
gcloud scheduler jobs run daily-grading-completeness-check --location=us-west2
```

### Verify Slack Alerts

Test Slack webhook connectivity:

```bash
# Test warning webhook
curl -X POST $SLACK_WEBHOOK_WARNING \
  -H 'Content-Type: application/json' \
  -d '{"text": "Test alert from monitoring setup"}'

# Test error webhook (for drift check)
curl -X POST $SLACK_WEBHOOK_ERROR \
  -H 'Content-Type: application/json' \
  -d '{"text": "Test critical alert from monitoring setup"}'
```

## Monitoring the Monitors

### Check Scheduler Status

```bash
# List all scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep -E "(weekly-model-drift|daily-grading)"

# View specific scheduler
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2
gcloud scheduler jobs describe daily-grading-completeness-check --location=us-west2
```

### View Execution History

```bash
# Weekly drift check executions
gcloud run jobs executions list --job=nba-weekly-model-drift-check --region=us-west2 --limit=10

# Grading completeness executions
gcloud run jobs executions list --job=nba-grading-completeness-check --region=us-west2 --limit=10
```

### Check Logs

```bash
# Recent logs for weekly drift check
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-weekly-model-drift-check"' \
  --limit=50 --freshness=7d

# Recent logs for grading check
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-grading-completeness-check"' \
  --limit=50 --freshness=7d
```

### Check for Failures

```bash
# Failed executions (exit code != 0)
gcloud logging read 'resource.type="cloud_run_job" AND severity>=ERROR' \
  --limit=20 --freshness=7d

# Scheduler invocation failures
gcloud logging read 'resource.type="cloud_scheduler_job" AND severity>=ERROR' \
  --limit=20 --freshness=7d
```

## Alert Thresholds

### Weekly Model Drift Check

Checks model performance over last 4 weeks:

| Metric | WARNING | CRITICAL |
|--------|---------|----------|
| Hit Rate | < 60% for 2+ weeks | < 55% for 2+ weeks |
| Vegas Edge | Negative for 2+ weeks | N/A |

**Actions on Alert:**
- WARNING: Monitor closely, review player tier breakdown
- CRITICAL: Emergency retraining, check data quality

### Daily Grading Completeness Check

Checks grading coverage over last 3 days:

| Coverage | Status | Action |
|----------|--------|--------|
| ≥ 80% | ✅ OK | None |
| 50-79% | 🟡 WARNING | Monitor next run |
| < 50% | 🔴 CRITICAL | Run backfill immediately |

**Grading Backfill Command:**
```bash
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date <date> --end-date <date>
```

## Troubleshooting

### Jobs Not Running on Schedule

**Check scheduler status:**
```bash
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2 --format="value(state)"
```

**Common issues:**
- Scheduler paused: `gcloud scheduler jobs resume <job> --location=us-west2`
- Wrong timezone: Check `--time-zone=America/New_York` in scheduler
- Service account permissions: Verify `756957797294-compute@developer.gserviceaccount.com` has Cloud Run Invoker role

### No Slack Alerts Received

**Check environment variables:**
```bash
gcloud run jobs describe nba-weekly-model-drift-check --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"
```

**Verify webhooks:**
```bash
# Test webhook manually
curl -X POST $SLACK_WEBHOOK_WARNING -H 'Content-Type: application/json' -d '{"text": "test"}'
```

**Common issues:**
- Environment variables not set on Cloud Run Job
- Webhook URL expired/revoked
- Wrong Slack channel permissions

### Job Execution Fails

**View failure logs:**
```bash
# Get latest failed execution
EXECUTION_NAME=$(gcloud run jobs executions list \
  --job=nba-weekly-model-drift-check --region=us-west2 \
  --filter="status.conditions[0].type=Completed AND status.conditions[0].status=False" \
  --limit=1 --format="value(metadata.name)")

# View logs from failed execution
gcloud logging read "resource.type=\"cloud_run_job\" \
  AND resource.labels.job_name=\"nba-weekly-model-drift-check\" \
  AND labels.\"run.googleapis.com/execution_name\"=\"$EXECUTION_NAME\"" \
  --limit=100 --format=json
```

**Common issues:**
- BigQuery permissions: Ensure service account has `roles/bigquery.jobUser`
- BigQuery query timeout: Increase `--task-timeout` on job
- Script error: Check bash script syntax and bq query syntax

### Drift Check Shows False Positives

**Review thresholds:**
- 2 consecutive weeks < 60% hit rate (WARNING)
- 2 consecutive weeks < 55% hit rate (CRITICAL)

**Verify data quality:**
```sql
-- Check if grading is complete for analyzed period
SELECT game_date, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY game_date
ORDER BY game_date DESC
```

**Manual drift analysis:**
```bash
# Run script locally to see detailed output
./bin/monitoring/weekly_model_drift_check.sh
```

## Maintenance

### Updating Monitoring Logic

1. Modify bash script: `bin/monitoring/weekly_model_drift_check.sh` or `check_grading_completeness.sh`
2. Rebuild Docker image: `./bin/deploy-monitoring-job.sh <job-name>`
3. Test manually: `gcloud run jobs execute <job-name> --region=us-west2`
4. Verify next scheduled run

### Changing Schedule

```bash
# Update scheduler job with new cron expression
gcloud scheduler jobs update http weekly-model-drift-check \
  --location=us-west2 \
  --schedule="0 10 * * 1"  # Change to 10 AM ET (15:00 UTC)
```

**Cron syntax (UTC-based, converted from ET):**
- Mondays 9 AM ET = `0 14 * * 1` (14:00 UTC)
- Daily 9 AM ET = `0 14 * * *` (14:00 UTC)
- Daily 6 AM ET = `0 11 * * *` (11:00 UTC)

### Pausing/Resuming Monitoring

```bash
# Pause scheduler (stop automatic runs)
gcloud scheduler jobs pause weekly-model-drift-check --location=us-west2

# Resume scheduler
gcloud scheduler jobs resume weekly-model-drift-check --location=us-west2
```

## Reference

### Files

| Path | Purpose |
|------|---------|
| `bin/monitoring/weekly_model_drift_check.sh` | Bash script for drift detection |
| `bin/monitoring/check_grading_completeness.sh` | Bash script for grading validation |
| `deployment/dockerfiles/nba/Dockerfile.weekly-model-drift-check` | Docker image for drift check |
| `deployment/dockerfiles/nba/Dockerfile.grading-completeness-check` | Docker image for grading check |
| `bin/deploy-monitoring-job.sh` | Deployment script for monitoring jobs |
| `bin/monitoring/setup_weekly_drift_check_scheduler.sh` | Scheduler setup for drift check |
| `bin/monitoring/setup_daily_grading_check_scheduler.sh` | Scheduler setup for grading check |

### GCP Resources

| Resource Type | Name | Purpose |
|---------------|------|---------|
| Cloud Run Job | `nba-weekly-model-drift-check` | Executes weekly drift analysis |
| Cloud Run Job | `nba-grading-completeness-check` | Executes daily grading validation |
| Cloud Scheduler | `weekly-model-drift-check` | Triggers drift check Mondays 9 AM ET |
| Cloud Scheduler | `daily-grading-completeness-check` | Triggers grading check daily 9 AM ET |
| Artifact Registry | `weekly-model-drift-check:*` | Docker images for drift check |
| Artifact Registry | `grading-completeness-check:*` | Docker images for grading check |

### Related Documentation

- Project conventions: `/home/naji/code/nba-stats-scraper/CLAUDE.md`
- Dockerfile organization: `/home/naji/code/nba-stats-scraper/deployment/dockerfiles/README.md`
- Model monitoring: `/home/naji/code/nba-stats-scraper/docs/02-operations/model-monitoring.md`
- Grading pipeline: `/home/naji/code/nba-stats-scraper/docs/03-phases/phase6-grading.md`

## Session Context

**Created:** Session 77 (Feb 2, 2026)

**Why:** Monitoring scripts were created in Session 77 to prevent issues like:
- Session 66: Data leakage in V8 model (undetected for weeks)
- Session 68: Grading backfill falling behind (9K vs 419K records)
- Session 77: Incomplete grading causing false model performance reports

**Design Decision:** Use Cloud Run Jobs (not Cloud Functions) because:
- Scripts need `bq` CLI access (BigQuery command line)
- Better for long-running monitoring queries (10m timeout vs 9m)
- Explicit execution logging and failure tracking
- Container-based (can run bash scripts with Google Cloud SDK)

**Alert Philosophy:**
- WARNING alerts → Monitor closely, review trends
- CRITICAL alerts → Immediate action required, run backfills
- Exit codes used for scheduler retry logic (0=success, 1=warning, 2=critical)
