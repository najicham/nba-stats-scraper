# Pub/Sub Schema Management & Error Prevention

**File:** `docs/infrastructure/02-pubsub-schema-management.md`
**Created:** 2025-11-14 17:21 PST
**Last Updated:** 2025-11-15 (moved from orchestration/ to infrastructure/)
**Purpose:** Prevent schema mismatch errors between scrapers and processors
**Status:** Current

---

## What Happened Today (Nov 14, 2025)

### The Problem

**Timeline:**
1. **Nov 13 ~11 AM ET**: Scrapers published Pub/Sub messages WITHOUT the `name` field
2. **Nov 13 ~11 AM ET**: Processors tried to process them, failed: "Missing required field: 'name'"
3. **Nov 13-14**: Messages retried, moved to DLQ, retried again...
4. **Nov 14 ~7:20 PM ET**: Old error emails finally sent (24 hours later!)
5. **Nov 14 ~7:13 PM ET**: Fixed scraper code deployed (now includes `name` field)

**User Impact:**
- Received dozens of error emails from YESTERDAY'S failures
- Confusing because errors were old, not current
- Made system appear broken when it was actually fixed

### Root Cause

**Schema mismatch between producers and consumers:**
- **Scrapers (producers)** sent: `scraper_name`
- **Processors (consumers)** expected: `name`
- No validation caught this before deployment
- Old messages persisted in queues even after fix deployed

---

## Prevention Strategies

### 1. Schema Validation in Scrapers (CRITICAL)

**Add validation before publishing:**

```python
# In scrapers/utils/pubsub_utils.py

def validate_message_schema(message_data: dict) -> bool:
    """Validate message has all required fields before publishing."""
    required_fields = [
        'name',           # Processors require this!
        'scraper_name',   # Backwards compatibility
        'execution_id',
        'status',
        'timestamp'
    ]

    missing_fields = [f for f in required_fields if f not in message_data]

    if missing_fields:
        logger.error(f"Message missing required fields: {missing_fields}")
        logger.error(f"Message data: {message_data}")
        raise ValueError(f"Cannot publish message missing fields: {missing_fields}")

    return True

def publish_scraper_complete_event(...):
    # Build message
    message_data = {...}

    # VALIDATE BEFORE PUBLISHING
    validate_message_schema(message_data)

    # Publish
    publisher.publish(...)
```

**Why:** Fail fast locally rather than discovering issues in production

---

### 2. Integration Tests for Pub/Sub Messages

**Add test to verify message format:**

```python
# tests/integration/test_pubsub_schema.py

def test_scraper_complete_message_schema():
    """Verify scraper-complete messages have all required fields."""
    from scrapers.utils.pubsub_utils import publish_scraper_complete_event

    # Capture published message
    with mock_pubsub() as pubsub:
        publish_scraper_complete_event(
            scraper_name="test_scraper",
            execution_id="test-123",
            status="success",
            ...
        )

        # Get published message
        messages = pubsub.get_published_messages('nba-scraper-complete')
        assert len(messages) == 1

        message_data = json.loads(messages[0].data)

        # Verify ALL required fields present
        assert 'name' in message_data, "Missing 'name' field (processors require this!)"
        assert 'scraper_name' in message_data
        assert 'execution_id' in message_data
        assert 'status' in message_data
        assert 'timestamp' in message_data

        # Verify name matches scraper_name
        assert message_data['name'] == message_data['scraper_name']
```

**Why:** Catch schema changes before deployment

---

### 3. Pre-Deployment Checklist

**Before deploying scrapers:**

1. ✅ Run integration tests including Pub/Sub schema tests
2. ✅ Deploy to staging environment first
3. ✅ Verify one scraper execution end-to-end in staging
4. ✅ Check processor logs for schema errors in staging
5. ✅ THEN deploy to production

**Script this:**
```bash
#!/bin/bash
# bin/scrapers/deploy/pre_deployment_checks.sh

echo "Running pre-deployment checks..."

# 1. Unit tests
pytest tests/unit/scrapers/ -v || exit 1

# 2. Integration tests (including Pub/Sub)
pytest tests/integration/ -v || exit 1

# 3. Schema validation
python -m scrapers.utils.validate_pubsub_schema || exit 1

echo "✅ All checks passed! Safe to deploy."
```

---

### 4. Monitoring & Alerting

**Set up alerts for schema errors:**

**Grafana Alert: Pub/Sub Schema Errors**
```sql
SELECT COUNT(*) as schema_errors
FROM `nba-props-platform.nba_logs.processor_errors`
WHERE error_message LIKE '%Missing required field%'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
HAVING schema_errors > 0
```

**Alert condition:** schema_errors > 0
**Alert channel:** Email + Slack
**Message:** "🚨 CRITICAL: Pub/Sub schema mismatch detected! Check scrapers/processors deployment."

**Why:** Catch schema issues immediately, not 24 hours later

---

### 5. DLQ Management

**Automatic DLQ purging after deployments:**

```bash
#!/bin/bash
# bin/pubsub/purge_dlq_after_deployment.sh

echo "Purging DLQ to prevent old error emails..."

# Purge messages older than current deployment
DEPLOYMENT_TIME=$(date -u --iso-8601=seconds)

gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub \
  --time="$DEPLOYMENT_TIME"

echo "✅ DLQ purged. Old messages will not retry."
```

**Run after every scraper deployment:**
```bash
# In bin/scrapers/deploy/deploy_scrapers_simple.sh

# After successful deployment
./bin/pubsub/purge_dlq_after_deployment.sh
```

**Why:** Prevent old malformed messages from retrying after fix is deployed

---

### 6. Schema Documentation

**Document the contract:**

Create `docs/pubsub/scraper-complete-message-schema.md`:

```markdown
# Scraper-Complete Message Schema

## Required Fields

| Field | Type | Required By | Description |
|-------|------|-------------|-------------|
| `name` | string | Processors | Scraper identifier (REQUIRED!) |
| `scraper_name` | string | Logging | Same as `name` (backwards compatibility) |
| `execution_id` | string | Both | Unique execution ID |
| `status` | string | Both | success/no_data/failed |
| `timestamp` | ISO8601 | Both | Execution timestamp |
| `gcs_path` | string? | Processors | Output file path (null if no_data) |
| `record_count` | int | Analytics | Number of records processed |
| `duration_seconds` | float | Analytics | Execution duration |
| `workflow` | string | Orchestration | Parent workflow name |
| `error_message` | string? | Debugging | Error details if failed |
| `metadata` | object? | Debugging | Additional context |

## Example Message

\`\`\`json
{
  "name": "bdl_active_players_scraper",
  "scraper_name": "bdl_active_players_scraper",
  "execution_id": "a1b2c3d4",
  "status": "success",
  "gcs_path": "gs://bucket/data/file.json",
  "record_count": 450,
  "duration_seconds": 3.5,
  "timestamp": "2025-11-14T23:30:00Z",
  "workflow": "morning_operations",
  "error_message": null,
  "metadata": {
    "scraper_class": "BdlActivePlayersScraper",
    "opts": {...}
  }
}
\`\`\`

## Breaking Changes

⚠️ **NEVER remove or rename required fields!**

If you must change schema:
1. Add NEW field alongside OLD field
2. Deploy scrapers (producers send both fields)
3. Deploy processors (consumers use new field, ignore old)
4. Wait 7 days for all queued messages to clear
5. Remove old field from scrapers

## Version History

- **v2 (2025-11-14)**: Added `name` field (processors require this)
- **v1 (2025-11-01)**: Initial schema with `scraper_name`
```

**Why:** Single source of truth prevents misunderstandings

---

## Quick Reference: Preventing Future Issues

### Before Every Deployment

```bash
# 1. Run schema validation
pytest tests/integration/test_pubsub_schema.py -v

# 2. Check for breaking changes
git diff HEAD~1 -- scrapers/utils/pubsub_utils.py

# 3. Deploy to staging first
./bin/scrapers/deploy/deploy_scrapers_simple.sh --env=staging

# 4. Verify in staging
./bin/pubsub/verify_staging_pubsub.sh

# 5. Deploy to production
./bin/scrapers/deploy/deploy_scrapers_simple.sh --env=production

# 6. Purge DLQ (prevent old errors)
./bin/pubsub/purge_dlq_after_deployment.sh
```

### After Deployment

```bash
# 1. Monitor for 10 minutes
watch -n 30 './bin/orchestration/quick_health_check.sh'

# 2. Check for schema errors
gcloud logging read "Missing required field" --limit=10 --freshness=10m

# 3. Verify DLQ is empty
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

---

## What To Do If You Get Old Error Emails

**Symptoms:**
- Error emails with timestamps from hours/days ago
- "Missing required field: 'name'" errors
- Multiple emails for same error

**Diagnosis:**
```bash
# Check if errors are old vs new
bq query "
SELECT
  DATE(triggered_at) as date,
  COUNT(*) as error_count
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE status = 'failed'
  AND error_message LIKE '%Missing required field%'
GROUP BY date
ORDER BY date DESC
LIMIT 7
"

# If errors are from previous days → old messages
# If errors are from today → real problem!
```

**Solution:**
```bash
# Purge DLQ to stop old error emails
gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub \
  --time=$(date -u -d '1 hour ago' --iso-8601=seconds)

# Verify DLQ is now empty
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub
```

**Prevention:**
- Add DLQ purging to deployment script (see above)
- Set up monitoring to catch issues immediately

---

## Related Documentation

- **Pub/Sub Architecture**: `docs/pubsub/architecture.md`
- **Error Notifications**: `docs/orchestration/enhanced-error-notifications-summary.md`
- **Deployment Plan**: `DEPLOYMENT_PLAN.md`
- **Orchestration Health**: `bin/orchestration/quick_health_check.sh`

---

**Last Updated:** 2025-11-14
**Incident:** Old error emails from schema mismatch
**Status:** Resolved - DLQ purged, fix deployed, prevention documented
