# Pub/Sub Reliability Fixes

**Created:** 2026-02-03
**Priority:** P1 - Affects prediction throughput
**Status:** ✅ Fixes Applied

## Applied Fixes (Session 101)

| Fix | Command/Change | Status |
|-----|----------------|--------|
| minScale=1 | `gcloud run services update prediction-worker --min-instances=1` | ✅ Applied |
| Retry policy | `--max-delivery-attempts=15 --min-retry-delay=10s --max-retry-delay=600s` | ✅ Applied |
| Rate limiting | Added `time.sleep(0.1)` in coordinator | ✅ Deployed |

## Additional Finding: Uptime Check Auth

The "not authenticated" errors in logs are from **Cloud Monitoring Uptime Checks**, NOT Pub/Sub.
Two uptime checks call `/health/deep` without auth → 403 errors.

**Fix (P2):** Update uptime checks to use authenticated requests

---

## Executive Summary

Intermittent authentication errors during prediction batches are caused by:
1. **Worker scales to zero** - Cold starts cause auth token delays
2. **No rate limiting** - 154 messages hit workers simultaneously
3. **Weak retry policy** - Only 5 attempts, no exponential backoff

---

## Root Cause Analysis

### Problem 1: Worker Scales to Zero

**Current Config:**
```yaml
autoscaling.knative.dev/maxScale: '10'
# minScale not set (defaults to 0)
```

**Impact:**
- When no requests for ~15 min, all instances terminate
- First request triggers cold start (3-5 seconds)
- During cold start, OIDC token validation can fail
- Multiple simultaneous cold starts cause auth failures

### Problem 2: No Rate Limiting on Publish

**Current Behavior (`coordinator.py:2273-2306`):**
```python
for request_data in requests:  # 154 messages
    publish_with_retry(publisher, topic_path, message_bytes, player_lookup)
    # No delay between publishes!
```

**Impact:**
- All 154 messages published in ~2 seconds
- Pub/Sub delivers all simultaneously
- Workers overwhelmed, BigQuery rate limits hit
- Cascading failures cause auth errors

### Problem 3: Weak Pub/Sub Retry Policy

**Current Config:**
```yaml
deadLetterPolicy:
  maxDeliveryAttempts: 5  # Too few
# No retryPolicy configured - uses defaults
```

**Impact:**
- Only 5 retry attempts before DLQ
- Default backoff may not be optimal
- Transient failures go to DLQ too quickly

---

## Recommended Fixes

### Fix 1: Set minScale=1 on Worker (RECOMMENDED)

**Command:**
```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --min-instances=1
```

**Cost Impact:** ~$30-50/month for one always-on instance
**Benefit:** Eliminates cold start auth failures

### Fix 2: Add Rate Limiting to Coordinator

**Code Change in `predictions/coordinator/coordinator.py` around line 2299:**

```python
# Add after imports
import time

# In publish_prediction_requests function, add delay:
PUBLISH_RATE_LIMIT = 0.1  # 10 messages per second

for request_data in requests:
    # ... existing code ...

    if publish_with_retry(publisher, topic_path, message_bytes, player_lookup):
        published_count += 1

        # Rate limit: 10 messages/second
        time.sleep(PUBLISH_RATE_LIMIT)

        if published_count % 50 == 0:
            logger.info(f"Published {published_count}/{len(requests)} requests")
```

**Impact:** 154 messages spread over ~15 seconds instead of ~2 seconds
**Trade-off:** Batch start takes longer but completes reliably

### Fix 3: Configure Pub/Sub Retry Policy

**Command:**
```bash
gcloud pubsub subscriptions update prediction-request-prod \
  --dead-letter-topic=projects/nba-props-platform/topics/prediction-request-dlq \
  --max-delivery-attempts=15 \
  --min-retry-delay=10s \
  --max-retry-delay=600s
```

**Changes:**
- `max-delivery-attempts`: 5 → 15
- `min-retry-delay`: 10 seconds (vs default ~1s)
- `max-retry-delay`: 600 seconds (10 min max backoff)

---

## Implementation Priority

| Fix | Effort | Impact | Recommendation |
|-----|--------|--------|----------------|
| minScale=1 | 1 command | High | **Do first** |
| Retry policy | 1 command | Medium | Do second |
| Rate limiting | Code change | Medium | Do third |

### Quick Fix (Do Now)

```bash
# 1. Set minScale=1 to avoid cold starts
gcloud run services update prediction-worker \
  --region=us-west2 \
  --min-instances=1

# 2. Improve retry policy
gcloud pubsub subscriptions update prediction-request-prod \
  --max-delivery-attempts=15 \
  --min-retry-delay=10s \
  --max-retry-delay=600s
```

---

## Verification

After applying fixes:

```bash
# 1. Verify minScale
gcloud run services describe prediction-worker --region=us-west2 \
  --format='value(spec.template.metadata.annotations.autoscaling.knative.dev/minScale)'
# Should return: 1

# 2. Verify retry policy
gcloud pubsub subscriptions describe prediction-request-prod \
  --format='yaml(retryPolicy,deadLetterPolicy)'
# Should show new retry settings

# 3. Test with small batch
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-03", "require_real_lines": true}'

# 4. Check for auth errors (should be none)
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"not authenticated"' \
  --limit=5 --freshness=10m
```

---

## Monitoring

Add these checks to daily validation:

```sql
-- Check DLQ message count (should be 0 for recent dates)
-- TODO: Add Pub/Sub metrics to monitoring dashboard
```

---

## Related Files

- `predictions/coordinator/coordinator.py` - Rate limiting change
- `predictions/worker/worker.py` - No changes needed
- Cloud Run service: `prediction-worker`
- Pub/Sub subscription: `prediction-request-prod`
