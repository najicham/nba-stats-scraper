# Slack Webhook Configuration Guide

**Created:** 2026-01-24
**Issue Found:** Session 122 Morning Checkup
**Status:** Documentation only (ops task)

---

## Issue

Cloud Functions like `daily-health-check` are skipping Slack notifications because `SLACK_WEBHOOK_URL` is not configured.

Log message observed:
```
SLACK_WEBHOOK_URL not configured, skipping notification
```

---

## Environment Variables

The notification system supports these environment variables:

| Variable | Purpose |
|----------|---------|
| `SLACK_WEBHOOK_URL` | Default webhook for all notification levels |
| `SLACK_WEBHOOK_URL_INFO` | Webhook for INFO level notifications |
| `SLACK_WEBHOOK_URL_WARNING` | Webhook for WARNING level notifications |
| `SLACK_WEBHOOK_URL_ERROR` | Webhook for ERROR level notifications |
| `SLACK_WEBHOOK_URL_CRITICAL` | Webhook for CRITICAL level notifications |

If level-specific webhooks are not set, the system falls back to `SLACK_WEBHOOK_URL`.

---

## How to Configure

### 1. Create Slack Webhook

1. Go to your Slack workspace
2. Create an incoming webhook app or use existing one
3. Generate webhook URL for desired channel(s)

### 2. Set Environment Variables in Cloud Functions

For each Cloud Function that needs Slack notifications:

```bash
# Update a specific function
gcloud functions deploy daily-health-check \
  --update-env-vars SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ \
  --region=us-west2

# Or update multiple functions
for fn in daily-health-check daily-health-summary grading-readiness-monitor; do
  gcloud functions deploy $fn \
    --update-env-vars SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ \
    --region=us-west2
done
```

### 3. Verify Configuration

After deployment, trigger the function and check logs:
```bash
gcloud functions logs read daily-health-check --limit=10 --region=us-west2
```

You should no longer see "SLACK_WEBHOOK_URL not configured" messages.

---

## Cloud Functions That Need Slack Webhooks

Based on code grep, these functions use SLACK_WEBHOOK_URL:

| Function | Region | Purpose |
|----------|--------|---------|
| daily-health-check | us-west2 | Daily system health summary |
| daily-health-summary | us-west2 | Health summary notifications |
| prediction-health-alert | us-west2 | Prediction system alerts |
| phase2-to-phase3 | us-west2 | Pipeline phase transition alerts |
| phase3-to-phase4 | us-west1/2 | Pipeline phase transition alerts |
| phase4-to-phase5 | us-west1/2 | Pipeline phase transition alerts |
| firestore-cleanup | us-west2 | Cleanup operation alerts |

---

## Related Files

- `shared/utils/notification_system.py` - Main notification implementation
- `shared/utils/slack_retry.py` - Slack retry logic with circuit breaker
- `shared/utils/processor_alerting.py` - Processor-specific alerting

---

## Notes

- Slack notifications are protected by circuit breaker (added 2026-01-23)
- If Slack is unavailable, the system auto-recovers after timeout
- This is an ops/deployment task, not a code fix
