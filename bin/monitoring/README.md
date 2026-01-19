# Monitoring Setup

## Alert Policies

Configure these alerts in Cloud Console:

1. **Health Check Failures**
   - Metric: `run.googleapis.com/request_count`
   - Filter: `response_code_class="5xx" AND path="/ready"`
   - Threshold: >5 errors in 5 minutes
   - Notification: Slack + Email

2. **Deployment Failures**
   - Metric: `run.googleapis.com/request_count`
   - Filter: `response_code_class="5xx"`
   - Threshold: >10 errors in 1 minute (spike detection)
   - Notification: Slack + Email

3. **Error Rate**
   - Metric: `logging.googleapis.com/log_entry_count`
   - Filter: `severity>=ERROR`
   - Threshold: >5 errors in 5 minutes
   - Notification: Slack

## Dashboards

Create dashboard with:
- Health check success rate by service
- Deployment frequency
- Error rate trends
- Response time p50/p95/p99

## Commands

```bash
# List existing alert policies
gcloud alpha monitoring policies list --project=nba-props-platform

# Create notification channel
gcloud alpha monitoring channels create \
  --display-name="Slack Alerts" \
  --type=slack \
  --project=nba-props-platform

# Get notification channel ID
gcloud alpha monitoring channels list --project=nba-props-platform
```
