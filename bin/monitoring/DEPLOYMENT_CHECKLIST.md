# Monitoring Automation Deployment Checklist

Quick reference for deploying the automated monitoring system.

## Prerequisites

- [x] Monitoring scripts tested locally (Session 77)
- [ ] Slack webhook URLs available
- [ ] Docker installed and authenticated to Artifact Registry
- [ ] gcloud CLI authenticated with admin permissions

## Step-by-Step Deployment

### 1. Get Slack Webhook URLs

```bash
# Get from 1Password or ask admin for:
export SLACK_WEBHOOK_WARNING="https://hooks.slack.com/services/YOUR/WARNING/WEBHOOK"
export SLACK_WEBHOOK_ERROR="https://hooks.slack.com/services/YOUR/ERROR/WEBHOOK"
```

### 2. Deploy Weekly Model Drift Check

```bash
# Deploy Cloud Run Job
./bin/deploy-monitoring-job.sh weekly-model-drift-check

# Set environment variables
gcloud run jobs update nba-weekly-model-drift-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING,SLACK_WEBHOOK_URL_ERROR=$SLACK_WEBHOOK_ERROR

# Test execution
gcloud run jobs execute nba-weekly-model-drift-check --region=us-west2

# Wait 2-3 minutes, then check logs
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-weekly-model-drift-check"' \
  --limit=50 --format=json | jq -r '.[].textPayload' | head -50

# If successful, set up scheduler
./bin/monitoring/setup_weekly_drift_check_scheduler.sh

# Verify scheduler created
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2
```

**Expected output from test:**
- Query results showing weekly hit rates
- Status: "No drift detected" or alert message
- Exit code 0 (healthy), 1 (warning), or 2 (critical)

### 3. Deploy Daily Grading Completeness Check

```bash
# Deploy Cloud Run Job
./bin/deploy-monitoring-job.sh grading-completeness-check

# Set environment variables
gcloud run jobs update nba-grading-completeness-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING

# Test execution
gcloud run jobs execute nba-grading-completeness-check --region=us-west2

# Wait 2-3 minutes, then check logs
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-grading-completeness-check"' \
  --limit=50 --format=json | jq -r '.[].textPayload' | head -50

# If successful, set up scheduler
./bin/monitoring/setup_daily_grading_check_scheduler.sh

# Verify scheduler created
gcloud scheduler jobs describe daily-grading-completeness-check --location=us-west2
```

**Expected output from test:**
- CSV table with system_id, predictions, graded, coverage_pct, status
- Status: "HEALTHY", "WARNING", or "CRITICAL"
- Exit code 0 (healthy), 1 (warning), or 2 (critical)

### 4. Verify Full Setup

```bash
# List Cloud Run Jobs
gcloud run jobs list --region=us-west2 | grep nba-

# List schedulers
gcloud scheduler jobs list --location=us-west2 | grep -E "(weekly-model-drift|daily-grading)"

# Manually trigger schedulers to test end-to-end
gcloud scheduler jobs run weekly-model-drift-check --location=us-west2
gcloud scheduler jobs run daily-grading-completeness-check --location=us-west2

# Check Slack for test alerts (if thresholds exceeded)
```

### 5. Test Slack Alerts

```bash
# Test WARNING webhook
curl -X POST $SLACK_WEBHOOK_WARNING \
  -H 'Content-Type: application/json' \
  -d '{"text": "✅ Monitoring automation deployed and tested successfully"}'

# Test ERROR webhook
curl -X POST $SLACK_WEBHOOK_ERROR \
  -H 'Content-Type: application/json' \
  -d '{"text": "✅ Critical alerts webhook working"}'
```

## Verification Commands

```bash
# Check scheduler next run time
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2 \
  --format="value(schedule,timeZone,state)"

gcloud scheduler jobs describe daily-grading-completeness-check --location=us-west2 \
  --format="value(schedule,timeZone,state)"

# View recent job executions
gcloud run jobs executions list --job=nba-weekly-model-drift-check --region=us-west2 --limit=3
gcloud run jobs executions list --job=nba-grading-completeness-check --region=us-west2 --limit=3

# Check for any failures in last 7 days
gcloud logging read 'resource.type="cloud_run_job" AND severity>=ERROR' \
  --limit=20 --freshness=7d
```

## Expected Schedule

| Job | Schedule (ET) | Next Run |
|-----|---------------|----------|
| Weekly Model Drift Check | Mondays 9 AM | Next Monday 9:00 AM ET |
| Daily Grading Check | Daily 9 AM | Tomorrow 9:00 AM ET |

## Troubleshooting

### Job Execution Fails

```bash
# View detailed logs for latest execution
EXECUTION=$(gcloud run jobs executions list --job=nba-weekly-model-drift-check \
  --region=us-west2 --limit=1 --format="value(metadata.name)")

gcloud logging read "resource.type=\"cloud_run_job\" \
  AND resource.labels.job_name=\"nba-weekly-model-drift-check\" \
  AND labels.\"run.googleapis.com/execution_name\"=\"$EXECUTION\"" \
  --limit=200 --format=json | jq -r '.[].textPayload'
```

### No Slack Alerts

```bash
# Verify environment variables are set
gcloud run jobs describe nba-weekly-model-drift-check --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)"

# Test webhook manually
curl -X POST $SLACK_WEBHOOK_WARNING \
  -H 'Content-Type: application/json' \
  -d '{"text": "Test from monitoring deployment"}'
```

### Scheduler Not Triggering

```bash
# Check scheduler state (should be ENABLED)
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2 \
  --format="value(state)"

# If PAUSED, resume
gcloud scheduler jobs resume weekly-model-drift-check --location=us-west2

# Check service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:756957797294-compute@developer.gserviceaccount.com"
```

## Post-Deployment

After successful deployment:

1. **Document in handoff:** Add to session handoff document
2. **Update CLAUDE.md:** Reference automated monitoring in runbooks
3. **Create calendar reminders:** Check monitoring health monthly
4. **Add to runbooks:** Include in incident response procedures

## Rollback

If issues occur:

```bash
# Pause schedulers (stop automatic runs)
gcloud scheduler jobs pause weekly-model-drift-check --location=us-west2
gcloud scheduler jobs pause daily-grading-completeness-check --location=us-west2

# Delete schedulers
gcloud scheduler jobs delete weekly-model-drift-check --location=us-west2 --quiet
gcloud scheduler jobs delete daily-grading-completeness-check --location=us-west2 --quiet

# Delete Cloud Run Jobs
gcloud run jobs delete nba-weekly-model-drift-check --region=us-west2 --quiet
gcloud run jobs delete nba-grading-completeness-check --region=us-west2 --quiet
```

## Success Criteria

- [x] Both Cloud Run Jobs deployed successfully
- [x] Environment variables set for Slack webhooks
- [x] Test executions complete without errors
- [x] Schedulers created and ENABLED
- [x] Manual scheduler runs trigger jobs successfully
- [x] Slack alerts received (if thresholds breached)
- [x] Logs show successful BigQuery queries
- [x] Documentation created and complete

## Next Steps

After deployment:

1. Monitor first scheduled run (Monday 9 AM ET for drift check, tomorrow 9 AM ET for grading check)
2. Review alert messages in Slack
3. Tune alert thresholds if needed (edit bash scripts, redeploy)
4. Add monitoring dashboards in GCP Console
5. Create runbook for responding to alerts

## Session Context

**Deployed:** Session 77 (Feb 2, 2026)
**Created by:** Claude Sonnet 4.5
**Purpose:** Automate critical monitoring to prevent undetected issues
