# Pipeline Health Monitor Cloud Function

Real-time pipeline health monitoring function that runs every 30 minutes during NBA game hours.

## Purpose

Monitors Phase 3, 4, and 5 pipeline processors and sends Slack alerts when success rates drop below 90%.

## Deployment

```bash
cd infrastructure/cloud-functions/pipeline-health-monitor

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

## Configuration

- **Region**: us-west2
- **Runtime**: Python 3.11
- **Memory**: 256Mi
- **Timeout**: 120 seconds
- **Slack Webhook**: `slack-webhook-monitoring-error` (GCP Secret)

## Scheduler

Triggered by Cloud Scheduler job `pipeline-health-monitor-job`:
- Schedule: `*/30 22-23,0-6 * * *` (every 30 minutes)
- Active hours: 5 PM - 1 AM ET (22:00-06:00 UTC)

## Testing

```bash
# Direct invocation
curl https://pipeline-health-monitor-f7p3g7f6ya-wl.a.run.app

# View logs
gcloud functions logs read pipeline-health-monitor --region=us-west2 --limit=20 --gen2
```

## Documentation

See [docs/02-operations/realtime-health-alerting.md](../../../docs/02-operations/realtime-health-alerting.md) for full operational guide.
