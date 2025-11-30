# Pub/Sub Operations Guide

**Purpose:** Monitor and manage Pub/Sub messaging infrastructure
**Audience:** Operations, DevOps, On-call
**Created:** 2025-11-29 16:55 PST
**Last Updated:** 2025-11-29 16:55 PST

---

## Quick Reference

### List All Topics

```bash
gcloud pubsub topics list --project=nba-props-platform | grep nba-phase
```

### List All Subscriptions

```bash
gcloud pubsub subscriptions list --project=nba-props-platform
```

### Check Message Backlog

```bash
# Get undelivered message count for a subscription
gcloud pubsub subscriptions describe SUBSCRIPTION_NAME \
  --format="value(numMessagesUndelivered)"
```

---

## Topics Overview

| Topic | Purpose | Publishers | Subscribers |
|-------|---------|------------|-------------|
| `nba-phase1-scrapers-complete` | Scraper done | Scrapers | Phase 2 processors |
| `nba-phase2-raw-complete` | Raw processor done | Phase 2 (21) | Phase 2→3 orchestrator |
| `nba-phase3-trigger` | Start Phase 3 | Phase 2→3 orchestrator | Phase 3 processors (5) |
| `nba-phase3-analytics-complete` | Analytics done | Phase 3 (5) | Phase 3→4 orchestrator |
| `nba-phase4-trigger` | Start Phase 4 | Phase 3→4 orchestrator | Phase 4 processors (5) |
| `nba-phase4-processor-complete` | Phase 4 internal | Phase 4 | Phase 4 coordinator |
| `nba-phase4-precompute-complete` | Phase 4 done | ml_feature_store_v2 | Phase 5 coordinator |
| `nba-phase5-predictions-complete` | Predictions done | Phase 5 coordinator | Monitoring (optional) |

---

## Monitoring

### Daily Health Check

```bash
#!/bin/bash
# Pub/Sub health check

echo "=== Pub/Sub Health Check ==="
echo ""

# List topics
echo "Topics:"
gcloud pubsub topics list --project=nba-props-platform \
  --format="table(name.basename())" | grep nba-phase

# Check subscriptions
echo ""
echo "Subscriptions with backlog:"
for sub in $(gcloud pubsub subscriptions list --format="value(name)"); do
  BACKLOG=$(gcloud pubsub subscriptions describe $sub \
    --format="value(numMessagesUndelivered)" 2>/dev/null)
  if [ -n "$BACKLOG" ] && [ "$BACKLOG" -gt 0 ]; then
    echo "  $(basename $sub): $BACKLOG messages"
  fi
done
echo "  (None if no output above)"
```

### Monitor Message Flow

Watch for messages in real-time:

```bash
# Create a temporary subscription to monitor a topic
gcloud pubsub subscriptions create temp-monitor \
  --topic=nba-phase2-raw-complete \
  --expiration-period=24h

# Pull messages (non-destructive peek)
gcloud pubsub subscriptions pull temp-monitor \
  --limit=10 \
  --auto-ack=false

# Clean up
gcloud pubsub subscriptions delete temp-monitor
```

### Check Dead Letter Queues

If configured, check for failed message delivery:

```bash
# List dead letter topics
gcloud pubsub topics list | grep dlq

# Check dead letter message count
gcloud pubsub subscriptions describe YOUR_DLQ_SUBSCRIPTION \
  --format="value(numMessagesUndelivered)"
```

---

## Common Operations

### Manually Publish Test Message

**Phase 2 completion (trigger orchestrator):**
```bash
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message='{
    "processor_name": "TestProcessor",
    "phase": "phase_2_raw",
    "game_date": "2025-11-29",
    "status": "success",
    "correlation_id": "test-123",
    "record_count": 0,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

**Phase 3 trigger (start analytics):**
```bash
gcloud pubsub topics publish nba-phase3-trigger \
  --message='{
    "game_date": "2025-11-29",
    "correlation_id": "test-123",
    "trigger_source": "manual",
    "triggered_by": "operator",
    "upstream_processors_count": 21,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

**Phase 4 trigger (start precompute):**
```bash
gcloud pubsub topics publish nba-phase4-trigger \
  --message='{
    "game_date": "2025-11-29",
    "correlation_id": "test-123",
    "trigger_source": "manual",
    "triggered_by": "operator",
    "upstream_processors_count": 5,
    "entities_changed": {},
    "is_incremental": false,
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

### Drain Subscription Backlog

If messages are stuck:

```bash
# Seek subscription to end (skip all pending messages)
gcloud pubsub subscriptions seek SUBSCRIPTION_NAME \
  --time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

**Warning:** This discards all pending messages.

### Pause Processing

Detach subscription to pause a processor:

```bash
# Detach (messages will accumulate in topic)
gcloud pubsub subscriptions detach SUBSCRIPTION_NAME

# Re-attach later by re-creating subscription
gcloud pubsub subscriptions create SUBSCRIPTION_NAME \
  --topic=TOPIC_NAME
```

---

## Subscription Management

### View Subscription Details

```bash
gcloud pubsub subscriptions describe SUBSCRIPTION_NAME \
  --format="yaml"
```

Key fields:
- `ackDeadlineSeconds`: Time to acknowledge before redelivery
- `messageRetentionDuration`: How long unacked messages kept
- `expirationPolicy`: When subscription auto-deletes

### Update Subscription Settings

```bash
# Increase ack deadline (default 10s)
gcloud pubsub subscriptions update SUBSCRIPTION_NAME \
  --ack-deadline=60

# Increase retention (default 7 days)
gcloud pubsub subscriptions update SUBSCRIPTION_NAME \
  --message-retention-duration=14d
```

### Create New Subscription

```bash
# Push subscription (for Cloud Functions/Run)
gcloud pubsub subscriptions create new-subscription \
  --topic=nba-phase2-raw-complete \
  --push-endpoint=https://your-service-url.run.app

# Pull subscription (for workers)
gcloud pubsub subscriptions create new-subscription \
  --topic=nba-phase2-raw-complete \
  --ack-deadline=60
```

---

## Troubleshooting

### Issue 1: Messages Not Being Delivered

**Symptoms:**
- Publishers succeed
- Subscribers not receiving messages

**Diagnosis:**
```bash
# Check subscription exists
gcloud pubsub subscriptions list | grep TOPIC_NAME

# Check subscription endpoint
gcloud pubsub subscriptions describe SUBSCRIPTION_NAME \
  --format="value(pushConfig.pushEndpoint)"

# Check for IAM issues
gcloud pubsub topics get-iam-policy TOPIC_NAME
```

**Resolution:**
1. Verify subscription exists and is attached to correct topic
2. Check push endpoint is accessible
3. Verify service account has `pubsub.subscriber` role

### Issue 2: High Message Backlog

**Symptoms:**
- `numMessagesUndelivered` increasing
- Subscribers falling behind

**Diagnosis:**
```bash
# Check backlog
gcloud pubsub subscriptions describe SUBSCRIPTION_NAME \
  --format="value(numMessagesUndelivered)"

# Check subscriber logs for errors
# (depends on subscriber type - Cloud Function, Cloud Run, etc.)
```

**Resolution:**
1. Scale up subscribers (increase max instances)
2. Check for processing errors in subscriber
3. If messages are stale, seek to current time

### Issue 3: Duplicate Messages

**Symptoms:**
- Same message processed multiple times
- Idempotency violations

**Cause:**
- Pub/Sub guarantees at-least-once delivery
- Duplicates can occur if ack not received in time

**Resolution:**
1. Ensure processors are idempotent
2. Increase ack deadline if processing takes long
3. Use message deduplication (check message_id)

### Issue 4: Message Timeout/Redelivery

**Symptoms:**
- Same message keeps reappearing
- Processing succeeds but ack fails

**Diagnosis:**
```bash
# Check ack deadline
gcloud pubsub subscriptions describe SUBSCRIPTION_NAME \
  --format="value(ackDeadlineSeconds)"

# Check subscriber execution time
# Compare with ack deadline
```

**Resolution:**
```bash
# Increase ack deadline
gcloud pubsub subscriptions update SUBSCRIPTION_NAME \
  --ack-deadline=120
```

---

## Topic Management

### Create Topic

```bash
gcloud pubsub topics create new-topic-name
```

### Delete Topic

```bash
# Warning: Also deletes all subscriptions
gcloud pubsub topics delete topic-name
```

### List Topic Subscriptions

```bash
gcloud pubsub topics list-subscriptions TOPIC_NAME
```

### Get Topic IAM Policy

```bash
gcloud pubsub topics get-iam-policy TOPIC_NAME
```

---

## Message Inspection

### View Message Contents

```bash
# Create temporary subscription
gcloud pubsub subscriptions create temp-inspect \
  --topic=nba-phase2-raw-complete \
  --expiration-period=1h

# Pull and inspect (no auto-ack to leave message)
gcloud pubsub subscriptions pull temp-inspect \
  --limit=5 \
  --format="json"

# Clean up
gcloud pubsub subscriptions delete temp-inspect
```

### Decode Base64 Message Data

Messages are base64 encoded. Decode with:

```bash
echo "BASE64_DATA" | base64 -d | jq .
```

Or in Python:
```python
import base64
import json

data = "eyJwcm9jZXNzb3JfbmFtZSI6ICJUZXN0In0="
message = json.loads(base64.b64decode(data))
print(message)
```

---

## Metrics and Logging

### Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `subscription/num_undelivered_messages` | Backlog size | >1000 |
| `subscription/oldest_unacked_message_age` | Oldest message | >300s |
| `topic/send_request_count` | Messages published | - |
| `subscription/pull_request_count` | Messages delivered | - |

### View Metrics

```bash
# Via Cloud Console
https://console.cloud.google.com/monitoring/metrics-explorer?project=nba-props-platform

# Filter: pubsub.googleapis.com/subscription/num_undelivered_messages
```

### Log-Based Alerts

```bash
# Create alert for publish failures
gcloud alpha monitoring policies create \
  --display-name="Pub/Sub Publish Failures" \
  --condition-filter='resource.type="pubsub_topic" AND severity>=ERROR'
```

---

## Cost Optimization

### Message Pricing

| Operation | Price |
|-----------|-------|
| First 10GB/month | Free |
| Additional | $40/TB |

### Reduce Costs

1. **Batch messages** when possible
2. **Filter early** - don't publish unnecessary messages
3. **Cleanup unused** subscriptions
4. **Set expiration** on temporary subscriptions

### View Current Usage

```bash
# Via Billing Console
https://console.cloud.google.com/billing

# Filter by Pub/Sub service
```

---

## Emergency Procedures

### Stop All Processing

```bash
# Detach all subscriptions (messages accumulate but not delivered)
for sub in $(gcloud pubsub subscriptions list --format="value(name)" | grep nba-phase); do
  echo "Detaching $sub"
  gcloud pubsub subscriptions detach $sub
done
```

### Resume Processing

```bash
# Re-create subscriptions (need to know original config)
./bin/pubsub/create_topics.sh  # Usually creates subscriptions too
```

### Purge All Messages

```bash
# Seek to current time (discards all pending)
for sub in $(gcloud pubsub subscriptions list --format="value(name)" | grep nba-phase); do
  echo "Purging $sub"
  gcloud pubsub subscriptions seek $sub --time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
done
```

---

## Related Documentation

- [Pub/Sub Topics Architecture](../01-architecture/orchestration/pubsub-topics.md) - Topic definitions and message formats
- [Orchestrator Monitoring Guide](./orchestrator-monitoring.md) - Orchestrator operations
- [Orchestrators Architecture](../01-architecture/orchestration/orchestrators.md) - How orchestrators use Pub/Sub
- [v1.0 Deployment Guide](../04-deployment/v1.0-deployment-guide.md) - Infrastructure setup

---

**Document Version:** 1.0
**Created:** 2025-11-29 16:55 PST
**Last Updated:** 2025-11-29 16:55 PST
