# Automated Monitoring - Quick Reference

## Deployment (One-Time Setup)

```bash
# 1. Deploy Cloud Run Jobs
./bin/deploy-monitoring-job.sh weekly-model-drift-check
./bin/deploy-monitoring-job.sh grading-completeness-check

# 2. Set Slack webhooks (get from admin/1Password)
export SLACK_WEBHOOK_WARNING="https://hooks.slack.com/services/YOUR/WARNING/WEBHOOK"
export SLACK_WEBHOOK_ERROR="https://hooks.slack.com/services/YOUR/ERROR/WEBHOOK"

gcloud run jobs update nba-weekly-model-drift-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING,SLACK_WEBHOOK_URL_ERROR=$SLACK_WEBHOOK_ERROR

gcloud run jobs update nba-grading-completeness-check --region=us-west2 \
  --set-env-vars=SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_WARNING

# 3. Create schedulers
./bin/monitoring/setup_weekly_drift_check_scheduler.sh
./bin/monitoring/setup_daily_grading_check_scheduler.sh

# 4. Test
gcloud scheduler jobs run weekly-model-drift-check --location=us-west2
gcloud scheduler jobs run daily-grading-completeness-check --location=us-west2
```

## Daily Operations

### Run Locally
```bash
./bin/monitoring/weekly_model_drift_check.sh
./bin/monitoring/check_grading_completeness.sh
```

### Check Status
```bash
# List schedulers
gcloud scheduler jobs list --location=us-west2 | grep -E "(drift|grading)"

# View recent executions
gcloud run jobs executions list --job=nba-weekly-model-drift-check --region=us-west2 --limit=5
gcloud run jobs executions list --job=nba-grading-completeness-check --region=us-west2 --limit=5
```

### View Logs
```bash
# Last 50 log entries
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-weekly-model-drift-check"' --limit=50

gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-grading-completeness-check"' --limit=50
```

## Troubleshooting

### No Slack Alerts
```bash
# Check env vars
gcloud run jobs describe nba-weekly-model-drift-check --region=us-west2 --format="yaml(spec.template.spec.containers[0].env)"

# Test webhook
curl -X POST $SLACK_WEBHOOK_WARNING -H 'Content-Type: application/json' -d '{"text": "test"}'
```

### Job Fails
```bash
# View error logs
gcloud logging read 'resource.type="cloud_run_job" AND severity>=ERROR' --limit=20 --freshness=1d
```

### Scheduler Not Triggering
```bash
# Check state (should be ENABLED)
gcloud scheduler jobs describe weekly-model-drift-check --location=us-west2 --format="value(state)"

# Resume if paused
gcloud scheduler jobs resume weekly-model-drift-check --location=us-west2
```

## Updating

### Update Monitoring Logic
```bash
# 1. Edit script
vim bin/monitoring/weekly_model_drift_check.sh

# 2. Redeploy
./bin/deploy-monitoring-job.sh weekly-model-drift-check

# 3. Test
gcloud run jobs execute nba-weekly-model-drift-check --region=us-west2
```

### Change Schedule
```bash
# Update cron schedule
gcloud scheduler jobs update http weekly-model-drift-check \
  --location=us-west2 \
  --schedule="0 10 * * 1"  # Change to 10 AM ET
```

## Alert Thresholds

### Weekly Drift Check
- WARNING: Hit rate < 60% for 2+ weeks
- CRITICAL: Hit rate < 55% for 2+ weeks

### Daily Grading Check
- WARNING: Coverage 50-79%
- CRITICAL: Coverage < 50%

## Schedules

| Job | Schedule | Next Run |
|-----|----------|----------|
| Weekly Drift | Mondays 9 AM ET | Next Monday |
| Daily Grading | Daily 9 AM ET | Tomorrow |

## Documentation

- Full guide: `AUTOMATED_MONITORING_SETUP.md`
- Deployment steps: `DEPLOYMENT_CHECKLIST.md`
- Overview: `README.md`
