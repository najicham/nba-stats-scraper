# Real-Time Pipeline Health Alerting

## Overview

Automated real-time monitoring that checks pipeline health every 30 minutes during NBA game hours and sends Slack alerts when success rates drop below 90%.

## Components

### Cloud Function: `pipeline-health-monitor`
- **Region**: us-west2
- **Runtime**: Python 3.11
- **Trigger**: HTTP (unauthenticated)
- **URL**: https://pipeline-health-monitor-f7p3g7f6ya-wl.a.run.app
- **Timeout**: 120 seconds
- **Memory**: 256Mi

### Cloud Scheduler Job: `pipeline-health-monitor-job`
- **Region**: us-west2
- **Schedule**: `*/30 22-23,0-6 * * *` (every 30 minutes)
- **Timezone**: UTC
- **Active Hours**: 5 PM - 1 AM ET (22:00 - 06:00 UTC)
- **State**: ENABLED

## Functionality

### What It Monitors
- Checks the last 2 hours of pipeline events
- Monitors Phase 3, Phase 4, and Phase 5 processors
- Calculates success rate: `completed / (completed + failed) * 100`

### Alert Conditions
Sends Slack alert when **any phase** has:
- Success rate < 90%
- At least one completed or failed event

### Alert Destination
- **Slack Webhook**: `slack-webhook-monitoring-error` (GCP Secret)
- Channel: Monitoring errors channel

## Alert Message Format

```
⚠️ *Pipeline Health Alert* - 2026-01-29 16:30:00 UTC

Success rate dropped below 90.0% threshold:

*Phase 3*
• Success Rate: 75.0%
• Completed: 3
• Failed: 1
• Started: 4

Check logs: https://console.cloud.google.com/logs
```

## Manual Operations

### Test the Health Check
```bash
# Direct function invocation
curl https://pipeline-health-monitor-f7p3g7f6ya-wl.a.run.app

# Expected response (healthy)
{
  "status": "healthy",
  "timestamp": "2026-01-29T16:44:35.849621+00:00",
  "summary": {
    "phase_3": {
      "success_rate": 100.0,
      "completed": 4,
      "failed": 0
    }
  }
}
```

### Manually Trigger Scheduler Job
```bash
gcloud scheduler jobs run pipeline-health-monitor-job --location=us-west2
```

### View Function Logs
```bash
gcloud functions logs read pipeline-health-monitor --region=us-west2 --limit=50 --gen2
```

### View Scheduler Job Status
```bash
gcloud scheduler jobs describe pipeline-health-monitor-job --location=us-west2
```

## Deployment

### Update Cloud Function
```bash
# Edit function code in scratchpad
cd /tmp/claude/-home-naji-code-nba-stats-scraper/89d790f5-a05c-455e-9ada-90d023333a94/scratchpad/health-monitor-function

# Redeploy
gcloud functions deploy pipeline-health-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=check_pipeline_health \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=120s \
  --memory=256Mi \
  --set-env-vars=SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret=slack-webhook-monitoring-error)
```

### Update Scheduler Schedule
```bash
# Change schedule (example: every 15 minutes instead of 30)
gcloud scheduler jobs update http pipeline-health-monitor-job \
  --location=us-west2 \
  --schedule="*/15 22-23,0-6 * * *"
```

### Update Alert Threshold
Edit `main.py` and change:
```python
SUCCESS_THRESHOLD = 90.0  # Change this value
```

Then redeploy the function.

## Troubleshooting

### No Alerts Received
1. Check if scheduler job is running:
   ```bash
   gcloud scheduler jobs describe pipeline-health-monitor-job --location=us-west2
   ```

2. Verify Slack webhook is configured:
   ```bash
   gcloud secrets versions access latest --secret=slack-webhook-monitoring-error
   ```

3. Test function directly:
   ```bash
   curl https://pipeline-health-monitor-f7p3g7f6ya-wl.a.run.app
   ```

### Function Errors
Check logs:
```bash
gcloud functions logs read pipeline-health-monitor --region=us-west2 --limit=20 --gen2
```

### Scheduler Not Triggering
Check last execution:
```bash
gcloud scheduler jobs describe pipeline-health-monitor-job --location=us-west2 \
  --format="value(lastAttemptTime, scheduleTime, status)"
```

### False Positives
If getting alerts during normal operations:
1. Review recent pipeline events:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT phase, event_type, COUNT(*) as count
   FROM \`nba-props-platform.nba_orchestration.pipeline_event_log\`
   WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
     AND phase IN ('phase_3', 'phase_4', 'phase_5')
   GROUP BY 1, 2
   ORDER BY 1, 2
   "
   ```

2. Consider adjusting threshold or monitoring window

## Costs

- **Cloud Function**: ~$0.40/million invocations + compute time
- **Cloud Scheduler**: $0.10/job/month
- **Estimated Monthly Cost**: < $1 (14 invocations/day * 30 days = 420 invocations)

## Monitoring Schedule

The job runs during game hours only:
- **Game Hours**: 5 PM - 1 AM ET
- **UTC Hours**: 22:00 - 06:00 (next day)
- **Frequency**: Every 30 minutes
- **Daily Executions**: ~14 (7 hours × 2 per hour)

## Related Documentation

- [Pipeline Event Log Schema](../../schemas/bigquery/pipeline_event_log.sql)
- [Phase Success Monitor](../../bin/monitoring/phase_success_monitor.py)
- [Notification System](../../shared/utils/notification_system.py)
- [Troubleshooting Matrix](./troubleshooting-matrix.md)
