# MLB Monitoring - Slack Alerts Setup

**Status**: ✅ Deployed and Active
**Deployment Date**: 2026-01-16
**Region**: us-west2

---

## Overview

MLB monitoring system uses two methods for delivering alerts to Slack:

1. **Direct Slack Integration** (Primary): Monitoring jobs send alerts directly to Slack via webhooks
2. **Pub/Sub Integration** (Secondary): Centralized alert routing through Pub/Sub topic → Cloud Function → Slack

Both systems are active and can be used independently or together.

---

## Architecture

```
MLB Monitoring Jobs (Cloud Run)
    │
    ├──> AlertManager (direct) ──> Slack Webhook ──> Slack
    │
    └──> Pub/Sub Topic ──> Cloud Function ──> Slack Webhook ──> Slack
         (mlb-monitoring-alerts)   (mlb-alert-forwarder)
```

### Components

1. **Pub/Sub Topic**: `mlb-monitoring-alerts`
   - Centralized alert queue
   - Allows decoupling alert generation from delivery
   - Enables alert filtering, batching, and routing

2. **Cloud Function**: `mlb-alert-forwarder`
   - Runtime: Python 3.11
   - Trigger: Pub/Sub topic messages
   - Memory: 256Mi
   - Timeout: 60s
   - Region: us-west2

3. **Slack Webhooks** (in Secret Manager):
   - `slack-webhook-default` → General monitoring channel
   - `slack-webhook-monitoring-warning` → Warnings channel
   - `slack-webhook-monitoring-error` → Critical alerts channel

4. **Service Account**: `mlb-monitoring-sa@nba-props-platform.iam.gserviceaccount.com`
   - Permissions: BigQuery access, Secret Manager access, Pub/Sub publisher

---

## Alert Severity Routing

Alerts are routed to different Slack channels based on severity:

| Severity | Secret Name | Typical Use | Response Time |
|----------|-------------|-------------|---------------|
| **CRITICAL** | `slack-webhook-monitoring-error` | Pipeline failures, 0% coverage | 5 minutes |
| **ERROR** | `slack-webhook-monitoring-error` | Job failures, data quality issues | 1 hour |
| **WARNING** | `slack-webhook-monitoring-warning` | Low coverage, stale data | Next business day |
| **INFO** | `slack-webhook-default` | Daily summaries, status updates | No action needed |

---

## Usage

### Method 1: Direct Slack (via AlertManager)

This is the primary method used by MLB monitoring jobs:

```python
from shared.alerts.alert_manager import get_alert_manager

alert_mgr = get_alert_manager()

# Send alert
alert_mgr.send_alert(
    severity='warning',
    title='Gap Detection Alert',
    message='Found 3 data gaps in analytics pipeline',
    category='gap_detection',
    context={
        'date': '2025-08-15',
        'gaps_found': 3,
        'missing_games': ['NYY vs BOS', 'LAD vs SF', 'CHC vs STL']
    }
)
```

**Pros**:
- Simple and direct
- Built-in rate limiting
- Automatic backfill mode suppression
- No additional infrastructure needed

**Cons**:
- Each job needs Slack webhook access
- Less flexible for routing/filtering

### Method 2: Pub/Sub (via Cloud Function)

For centralized alert management:

```python
from google.cloud import pubsub_v1
import json

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('nba-props-platform', 'mlb-monitoring-alerts')

alert = {
    'severity': 'warning',
    'title': 'Gap Detection Alert',
    'message': 'Found 3 data gaps in analytics pipeline',
    'context': {
        'date': '2025-08-15',
        'gaps_found': 3,
        'missing_games': ['NYY vs BOS', 'LAD vs SF', 'CHC vs STL']
    },
    'timestamp': datetime.utcnow().isoformat()
}

publisher.publish(
    topic_path,
    data=json.dumps(alert).encode('utf-8')
)
```

**Pros**:
- Centralized alert routing
- Easy to add new destinations (email, PagerDuty, etc.)
- Can filter/batch alerts in Cloud Function
- Decouples alert generation from delivery

**Cons**:
- Slightly more complex
- Additional GCP component to maintain

---

## Alert Format

Alerts should follow this JSON structure:

```json
{
  "severity": "warning",
  "title": "Short Alert Title",
  "message": "Detailed description of the issue",
  "context": {
    "key1": "value1",
    "key2": "value2",
    "date": "2025-08-15"
  },
  "timestamp": "2025-08-15T12:34:56Z"
}
```

### Required Fields
- **severity**: `critical`, `error`, `warning`, or `info`
- **title**: Short, descriptive title (used as Slack header)

### Optional Fields
- **message**: Detailed description
- **context**: Dictionary of additional context (displayed as fields in Slack)
- **timestamp**: ISO 8601 timestamp (defaults to current time)

---

## Testing

### Test from Command Line

```bash
# Test INFO alert
gcloud pubsub topics publish mlb-monitoring-alerts \
  --message='{"severity":"info","title":"Test Info Alert","message":"This is a test info message","context":{"test":true}}' \
  --project=nba-props-platform

# Test WARNING alert
gcloud pubsub topics publish mlb-monitoring-alerts \
  --message='{"severity":"warning","title":"Test Warning Alert","message":"This is a test warning message","context":{"test":true,"alert_type":"warning"}}' \
  --project=nba-props-platform

# Test CRITICAL alert
gcloud pubsub topics publish mlb-monitoring-alerts \
  --message='{"severity":"critical","title":"Test Critical Alert","message":"This is a test critical alert","context":{"test":true,"pipeline":"analytics","status":"failed"}}' \
  --project=nba-props-platform
```

### Test from Python

```python
from google.cloud import pubsub_v1
import json
from datetime import datetime

def test_slack_alert():
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path('nba-props-platform', 'mlb-monitoring-alerts')

    test_alert = {
        'severity': 'warning',
        'title': 'MLB Monitoring Test',
        'message': 'Test alert from Python script',
        'context': {
            'test': True,
            'source': 'python_test',
            'timestamp': datetime.utcnow().isoformat()
        }
    }

    future = publisher.publish(
        topic_path,
        data=json.dumps(test_alert).encode('utf-8')
    )

    message_id = future.result()
    print(f"Published message ID: {message_id}")

if __name__ == '__main__':
    test_slack_alert()
```

### Verify Alert Delivery

1. **Check Cloud Function Logs**:
```bash
gcloud functions logs read mlb-alert-forwarder \
  --region=us-west2 \
  --gen2 \
  --limit=50 \
  --project=nba-props-platform
```

2. **Check Slack**: Alert should appear in the appropriate channel within seconds

3. **Check Pub/Sub Metrics**:
```bash
# View topic metrics in Cloud Console
open "https://console.cloud.google.com/cloudpubsub/topic/detail/mlb-monitoring-alerts?project=nba-props-platform"
```

---

## Monitoring the Alert System

### Cloud Function Metrics

Monitor the alert forwarder function:
- **Invocations**: Should match alert volume
- **Error rate**: Should be near 0%
- **Execution time**: Typically < 1 second
- **Active instances**: Usually 0-1 (scales automatically)

```bash
# View function metrics
gcloud functions describe mlb-alert-forwarder \
  --region=us-west2 \
  --gen2 \
  --project=nba-props-platform
```

### Pub/Sub Metrics

Monitor the topic and subscription:
- **Messages published**: Total alerts sent
- **Messages delivered**: Should equal published (no backlog)
- **Oldest unacked message age**: Should be near 0 (no delays)

```bash
# View subscription metrics
gcloud pubsub subscriptions describe eventarc-us-west2-mlb-alert-forwarder-093229-sub-103 \
  --project=nba-props-platform
```

### Common Issues

**Issue**: Alerts not appearing in Slack
- Check Cloud Function logs for errors
- Verify Slack webhook secrets are valid
- Test webhook directly: `curl -X POST <webhook_url> -d '{"text":"test"}'`
- Ensure service account has Secret Manager access

**Issue**: Delays in alert delivery
- Check Pub/Sub subscription backlog
- Verify Cloud Function is not rate-limited
- Check Slack API rate limits

**Issue**: Duplicate alerts
- Review AlertManager rate limiting settings
- Check if multiple systems are sending same alert
- Verify monitoring job schedules don't overlap

---

## Maintenance

### Update Slack Webhooks

```bash
# Update a webhook secret
echo -n "https://hooks.slack.com/services/NEW/WEBHOOK/URL" | \
  gcloud secrets versions add slack-webhook-default \
  --data-file=- \
  --project=nba-props-platform
```

### Update Cloud Function

```bash
cd /home/naji/code/nba-stats-scraper/cloud_functions/mlb-alert-forwarder

# Deploy updated function
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

### View Logs

```bash
# Stream logs in real-time
gcloud functions logs tail mlb-alert-forwarder \
  --region=us-west2 \
  --gen2 \
  --project=nba-props-platform

# View recent logs
gcloud functions logs read mlb-alert-forwarder \
  --region=us-west2 \
  --gen2 \
  --limit=100 \
  --project=nba-props-platform
```

---

## Cost

**Estimated monthly cost** (April-October MLB season):

| Component | Usage | Cost |
|-----------|-------|------|
| Cloud Function Invocations | ~5,000/month | $0.002 |
| Cloud Function Memory | 256Mi × 1s × 5,000 | $0.002 |
| Pub/Sub Messages | 5,000 published + 5,000 delivered | $0.00 (free tier) |
| Secret Manager Access | ~5,000 reads | $0.03 |
| **Total** | | **~$0.04/month** |

Essentially free during MLB season.

---

## Integration with MLB Monitoring Jobs

All 4 MLB monitoring services have AlertManager integrated:

1. **mlb-gap-detection**: Alerts on data gaps
2. **mlb-freshness-checker**: Alerts on stale data
3. **mlb-prediction-coverage**: Alerts on low coverage
4. **mlb-stall-detector**: Alerts on pipeline stalls

Each service can send alerts via:
- Direct Slack (current default)
- Pub/Sub topic (optional, add publisher code)

To add Pub/Sub publishing to a monitoring job:

```python
# Add to monitoring job
from google.cloud import pubsub_v1
import json

# Initialize publisher
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('nba-props-platform', 'mlb-monitoring-alerts')

# Publish alert
alert_data = {
    'severity': 'warning',
    'title': f'{job_name} Alert',
    'message': alert_message,
    'context': context_dict
}

publisher.publish(
    topic_path,
    data=json.dumps(alert_data).encode('utf-8')
)
```

---

## Deployment Status

✅ **Infrastructure**:
- Pub/Sub topic: `mlb-monitoring-alerts` (created)
- Cloud Function: `mlb-alert-forwarder` (deployed)
- Service account: `mlb-monitoring-sa` (configured)

✅ **Permissions**:
- BigQuery: dataViewer, jobUser
- Secret Manager: secretAccessor (3 webhooks)
- Pub/Sub: publisher

✅ **Configuration**:
- Region: us-west2
- Runtime: Python 3.11
- Memory: 256Mi
- Timeout: 60s
- Max instances: 10

✅ **Testing**:
- Test alerts published successfully
- Cloud Function deployed and active
- Logs confirmed function is running

---

## Related Documentation

- **AlertManager Code**: `shared/alerts/alert_manager.py`
- **Cloud Function Code**: `cloud_functions/mlb-alert-forwarder/main.py`
- **Deployment Docs**: `docs/09-handoff/2026-01-16-MLB-MONITORING-DEPLOYMENT-COMPLETE.md`
- **Alerting Runbook**: `docs/runbooks/mlb/alerting-runbook.md`

---

**Last Updated**: 2026-01-16
**Status**: Production Ready
**Next Review**: April 2026 (MLB season start)
