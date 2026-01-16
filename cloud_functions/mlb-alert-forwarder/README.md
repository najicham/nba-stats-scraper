# MLB Alert Forwarder Cloud Function

Forwards MLB monitoring alerts from Pub/Sub to Slack with severity-based routing.

## Overview

This Cloud Function subscribes to the `mlb-monitoring-alerts` Pub/Sub topic and forwards alerts to Slack. It routes alerts to different Slack channels based on severity:

- **CRITICAL/ERROR**: `slack-webhook-monitoring-error` → Critical alerts channel
- **WARNING**: `slack-webhook-monitoring-warning` → Warning alerts channel
- **INFO**: `slack-webhook-default` → General monitoring channel

## Alert Format

Alerts published to the Pub/Sub topic should have this JSON structure:

```json
{
  "severity": "warning",
  "title": "MLB Gap Detection Alert",
  "message": "Found 3 data gaps in yesterday's pipeline run",
  "context": {
    "date": "2025-08-15",
    "gaps_found": 3,
    "missing_games": ["NYY vs BOS", "LAD vs SF"],
    "pipeline_stage": "analytics"
  },
  "timestamp": "2025-08-15T12:34:56Z"
}
```

### Required Fields
- `severity`: Alert level (critical, error, warning, info)
- `title`: Short alert title

### Optional Fields
- `message`: Detailed alert description
- `context`: Dictionary of additional context (displayed as fields in Slack)
- `timestamp`: ISO 8601 timestamp (defaults to current time)

## Deployment

### Deploy Cloud Function

```bash
cd cloud_functions/mlb-alert-forwarder

gcloud functions deploy mlb-alert-forwarder \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=mlb_alert_forwarder \
  --trigger-topic=mlb-monitoring-alerts \
  --service-account=mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com \
  --set-env-vars=GCP_PROJECT=nba-props-platform \
  --timeout=60s \
  --memory=256Mi \
  --max-instances=10 \
  --project=nba-props-platform
```

### Grant Permissions

The Cloud Function service account needs:
- Secret Manager Secret Accessor (to read Slack webhooks)
- Pub/Sub Subscriber (automatically granted by Cloud Functions)

```bash
# Grant Secret Manager access
gcloud secrets add-iam-policy-binding slack-webhook-default \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding slack-webhook-monitoring-error \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding slack-webhook-monitoring-warning \
  --member="serviceAccount:mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## Testing

### Publish Test Alert

```bash
# Test warning alert
gcloud pubsub topics publish mlb-monitoring-alerts \
  --message='{"severity":"warning","title":"Test MLB Alert","message":"This is a test warning alert from MLB monitoring","context":{"test":true,"source":"manual_test"}}'

# Test critical alert
gcloud pubsub topics publish mlb-monitoring-alerts \
  --message='{"severity":"critical","title":"Critical: Pipeline Failure","message":"MLB analytics pipeline has failed","context":{"date":"2025-08-15","failed_jobs":5}}'
```

### View Logs

```bash
# Stream logs
gcloud functions logs read mlb-alert-forwarder \
  --region=us-west2 \
  --limit=50 \
  --gen2

# View in Cloud Console
https://console.cloud.google.com/functions/details/us-west2/mlb-alert-forwarder?project=nba-props-platform
```

## Monitoring

### Metrics
- **Invocations**: Number of alerts processed
- **Execution time**: Time to forward each alert
- **Error rate**: Failed alert deliveries

### Alerts
If the Cloud Function itself fails:
1. Check Cloud Function logs for errors
2. Verify Slack webhook secrets are accessible
3. Test Pub/Sub topic manually
4. Check service account permissions

## Integration with MLB Monitoring

MLB monitoring jobs can publish alerts in two ways:

### 1. Via AlertManager (Current)
The existing `AlertManager` class sends alerts directly to Slack:
```python
from shared.alerts.alert_manager import get_alert_manager

alert_mgr = get_alert_manager()
alert_mgr.send_alert(
    severity='warning',
    title='Gap Detected',
    message='Found 3 gaps in analytics',
    category='gap_detection'
)
```

### 2. Via Pub/Sub (New - Optional)
For centralized alert routing, publish to Pub/Sub:
```python
from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('nba-props-platform', 'mlb-monitoring-alerts')

alert = {
    'severity': 'warning',
    'title': 'Gap Detected',
    'message': 'Found 3 gaps in analytics',
    'context': {'gaps': 3}
}

publisher.publish(topic_path, json.dumps(alert).encode('utf-8'))
```

## Cost

**Estimated monthly cost** (April-October MLB season):
- ~5,000 alerts/month during active monitoring
- Cloud Function: $0.40/million invocations
- **Total: < $0.01/month**

## Troubleshooting

### Alert not appearing in Slack
1. Check Cloud Function logs: `gcloud functions logs read mlb-alert-forwarder --region=us-west2 --gen2`
2. Verify Pub/Sub message format is correct JSON
3. Test Slack webhook directly: `curl -X POST <webhook_url> -d '{"text":"test"}'`
4. Check Secret Manager contains valid webhook URLs

### Permission errors
1. Verify service account has Secret Manager access
2. Check Cloud Function is using correct service account
3. Ensure secrets exist and are accessible

### Rate limiting
If too many alerts:
1. Review AlertManager rate limiting settings
2. Consider batching alerts
3. Adjust monitoring schedules to reduce alert frequency
