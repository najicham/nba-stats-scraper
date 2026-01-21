# Robustness Improvements Runbook

**Date**: 2026-01-20
**Purpose**: Operational guide for improved error handling and monitoring
**Status**: ✅ Active

---

## Overview

This runbook documents the robustness improvements implemented on 2026-01-20 to reduce daily breakages and improve system observability. These changes focus on preventing silent failures and providing better alerting when issues occur.

---

## Improvements Implemented

### 1. Slack Alerts for Consistency Mismatches ✅

**Problem**: Dual-write consistency mismatches were logged but not alerted, causing silent failures during Week 1 migration.

**Solution**: Added Slack integration to send immediate alerts to #nba-alerts channel when mismatches are detected.

**File**: `predictions/coordinator/batch_state_manager.py:533-565`

**Alert Format**:
```
🚨 Dual-Write Consistency Mismatch

Batch: batch_2026-01-20_1234567890
Array Count: 120
Subcollection Count: 118
Difference: 2

This indicates a problem with the Week 1 dual-write migration. Investigate immediately.
```

**Configuration Required**:
```bash
export SLACK_WEBHOOK_URL_WARNING="<webhook-url-for-nba-alerts-channel>"
```

**Troubleshooting**:
- Check Cloud Logging for detailed error traces
- Verify both array and subcollection writes completed
- Review batch_state_manager logs for transaction failures

---

### 2. BigQuery Insert for Unresolved MLB Players ✅

**Problem**: Unresolved MLB players were logged but not persisted, causing data loss for review and resolution.

**Solution**: Implemented BigQuery insert to `mlb_reference.unresolved_players` table for tracking.

**File**: `predictions/coordinator/shared/utils/mlb_player_registry/reader.py:320-356`

**Table Schema**:
```sql
CREATE TABLE mlb_reference.unresolved_players (
  player_lookup STRING NOT NULL,
  player_type STRING NOT NULL,
  source STRING NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  occurrence_count INT64 NOT NULL,
  reported_at TIMESTAMP NOT NULL
)
```

**Monitoring**:
```sql
-- Check unresolved players in last 7 days
SELECT
  player_lookup,
  player_type,
  source,
  COUNT(*) as reports,
  MAX(occurrence_count) as max_occurrences
FROM `mlb_reference.unresolved_players`
WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY player_lookup, player_type, source
ORDER BY max_occurrences DESC
LIMIT 20
```

**Troubleshooting**:
- If inserts fail, errors are logged but execution continues
- Unresolved players are still logged for manual review
- Check BigQuery table permissions if inserts consistently fail

---

### 3. Standardized Logging (Print to Logger Conversion) ✅

**Problem**: Print statements bypassed logging framework, making it hard to filter and correlate logs in Cloud Logging.

**Solution**: Converted all print() statements to logger calls with appropriate levels.

**File**: `predictions/coordinator/batch_staging_writer.py` (15 print statements converted)

**Changes**:
- `print(f"✅ ...")` → `logger.info(f"✅ ...")`
- `print(f"⚠️ ...")` → `logger.warning(f"⚠️ ...")`
- `print(f"❌ ...")` → `logger.error(f"❌ ...")`

**Benefits**:
- All logs now go through structured logging
- Can filter by severity in Cloud Logging
- Better correlation with trace IDs
- Consistent log format

**Cloud Logging Queries**:
```
# Find consolidation errors
resource.type="cloud_run_revision"
resource.labels.service_name="prediction-coordinator"
severity>=ERROR
textPayload=~"consolidation"

# Track MERGE operations
resource.type="cloud_run_revision"
resource.labels.service_name="prediction-coordinator"
textPayload=~"MERGE complete"
```

---

### 4. AlertManager Integration for Pub/Sub Failures ✅

**Problem**: Pub/Sub publish failures were logged but not alerted, making it hard to detect infrastructure issues.

**Solution**: Integrated rate-limited AlertManager for publish failures.

**File**: `predictions/coordinator/shared/publishers/unified_pubsub_publisher.py:300-345`

**Features**:
- Rate-limited alerts (max 5 per hour per error type)
- Deduplication (same error signature)
- Rich context in alert messages

**Alert Format**:
```
Title: Pub/Sub Publish Failure: NbacGamesProcessor

Processor: NbacGamesProcessor
Topic: nba-phase2-raw-complete
Error: TimeoutError: Connection timeout
Game Date: 2026-01-20
Correlation ID: abc-123-xyz

Note: Downstream orchestration will use scheduler backup.
This is not critical but indicates a potential infrastructure issue.
```

**Configuration**:
```bash
# Rate limiting configuration
export NOTIFICATION_RATE_LIMIT_PER_HOUR=5
export NOTIFICATION_COOLDOWN_MINUTES=60
export NOTIFICATION_AGGREGATE_THRESHOLD=3
export NOTIFICATION_RATE_LIMITING_ENABLED=true
```

**Troubleshooting**:
- Check if Pub/Sub topic exists and has correct permissions
- Verify network connectivity from Cloud Run
- Review Pub/Sub quotas and limits
- Check AlertManager logs for rate limiting status

---

## Common Failure Scenarios

### Scenario 1: Consistency Mismatch Detected

**Symptoms**:
- Slack alert: "🚨 Dual-Write Consistency Mismatch"
- Cloud Logging WARNING with "CONSISTENCY MISMATCH"

**Investigation Steps**:
1. Check the batch_id from alert
2. Query Firestore for that batch document
3. Compare array length vs. subcollection count:
   ```python
   # In Cloud Shell or local
   from google.cloud import firestore
   db = firestore.Client(project='nba-props-platform')
   batch_doc = db.collection('prediction_batches').document(batch_id).get()
   array_count = len(batch_doc.to_dict().get('completed_players', []))

   # Query subcollection
   completions = db.collection('prediction_batches').document(batch_id).collection('completions').stream()
   subcoll_count = len(list(completions))

   print(f"Array: {array_count}, Subcollection: {subcoll_count}")
   ```

4. Check for transaction failures in logs
5. If systematic (10+ mismatches), consider rollback:
   ```bash
   gcloud run services update prediction-coordinator \
     --region us-west2 \
     --update-env-vars ENABLE_SUBCOLLECTION_COMPLETIONS=false
   ```

**Root Causes**:
- Firestore transaction timeouts
- Network issues during writes
- Race conditions in completion tracking
- Code bugs in dual-write logic

---

### Scenario 2: Pub/Sub Publish Failures

**Symptoms**:
- AlertManager email: "Pub/Sub Publish Failure"
- Cloud Logging WARNING: "Pub/Sub publishing failed"

**Investigation Steps**:
1. Check Pub/Sub topic status:
   ```bash
   gcloud pubsub topics describe <topic-name> --project nba-props-platform
   ```

2. Verify topic permissions:
   ```bash
   gcloud pubsub topics get-iam-policy <topic-name> --project nba-props-platform
   ```

3. Check for quota issues:
   ```bash
   gcloud alpha monitoring metrics-scopes list --project nba-props-platform
   # Look for Pub/Sub quota metrics
   ```

4. Review Cloud Run logs for network errors

**Mitigation**:
- Downstream orchestration uses scheduler backup (no immediate action needed)
- If persistent, check infrastructure issues
- Consider increasing Pub/Sub quotas if at limits

**Root Causes**:
- Network timeouts
- Pub/Sub API issues
- Quota exhaustion
- Permission changes

---

### Scenario 3: Unresolved MLB Players

**Symptoms**:
- Cloud Logging WARNING: "Unresolved MLB players"
- BigQuery table has new entries

**Investigation Steps**:
1. Query unresolved players:
   ```sql
   SELECT * FROM `mlb_reference.unresolved_players`
   WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
   ORDER BY occurrence_count DESC
   ```

2. Check if players exist in registry:
   ```sql
   SELECT * FROM `mlb_reference.mlb_player_registry`
   WHERE player_lookup = '<player_lookup>'
   ```

3. If missing, add to registry manually or via admin tool

**Resolution**:
- Add missing players to MLB registry
- Rerun affected predictions if needed
- Update player aliases if name variations

**Root Causes**:
- New players not in registry
- Name variations (nicknames, full names)
- Typos in source data
- Registry data staleness

---

### Scenario 4: Consolidation MERGE Returns 0 Rows

**Symptoms**:
- Cloud Logging ERROR: "⚠️ MERGE returned 0 rows"
- Staging tables not cleaned up

**Investigation Steps**:
1. Check staging tables:
   ```sql
   SELECT table_name, row_count
   FROM `nba_staging.__TABLES_SUMMARY__`
   WHERE table_name LIKE '%<batch_id>%'
   ```

2. Verify staging data exists:
   ```sql
   SELECT COUNT(*) FROM `nba_staging.<staging_table_name>`
   ```

3. Check final table for duplicates:
   ```sql
   SELECT business_key, COUNT(*) as duplicates
   FROM `nba_predictions.player_prop_predictions`
   WHERE game_date = '<game_date>'
   GROUP BY business_key
   HAVING duplicates > 1
   ```

**Resolution**:
- If staging data exists, investigate MERGE query logic
- If data already in final table, duplicates may have caused 0 insert
- Manually clean up staging tables after investigation
- Check distributed lock logs for race conditions

**Root Causes**:
- Duplicate business keys (lock failure)
- Staging data already merged
- MERGE query logic issues
- BigQuery transaction conflicts

---

## Monitoring Commands

### Check Recent Consistency Mismatches
```bash
gcloud logging read "severity=WARNING 'CONSISTENCY MISMATCH'" \
  --limit 50 --freshness=24h --format json | jq '.[] | {timestamp: .timestamp, message: .textPayload}'
```

### Check Pub/Sub Failures
```bash
gcloud logging read "severity=WARNING 'Pub/Sub publishing failed'" \
  --limit 50 --freshness=24h --format json
```

### Check Unresolved MLB Players
```sql
SELECT
  player_lookup,
  player_type,
  source,
  MAX(reported_at) as last_seen,
  SUM(occurrence_count) as total_occurrences
FROM `mlb_reference.unresolved_players`
WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY player_lookup, player_type, source
HAVING total_occurrences > 10
ORDER BY total_occurrences DESC
```

### Check Consolidation Errors
```bash
gcloud logging read \
  "resource.labels.service_name=prediction-coordinator severity>=ERROR 'consolidation'" \
  --limit 50 --freshness=24h
```

---

## Configuration Reference

### Environment Variables

**Slack Alerting**:
```bash
SLACK_WEBHOOK_URL_WARNING="<webhook-url>"  # For #nba-alerts channel
```

**AlertManager Rate Limiting**:
```bash
NOTIFICATION_RATE_LIMIT_PER_HOUR=5         # Max alerts per hour
NOTIFICATION_COOLDOWN_MINUTES=60           # Reset period
NOTIFICATION_AGGREGATE_THRESHOLD=3         # Summary threshold
NOTIFICATION_RATE_LIMITING_ENABLED=true    # Enable/disable
```

**Week 1 Dual-Write**:
```bash
ENABLE_SUBCOLLECTION_COMPLETIONS=true      # Enable dual-write
DUAL_WRITE_MODE=true                       # Write to both
USE_SUBCOLLECTION_READS=false              # Still read from array
```

---

## Testing Procedures

### Test Slack Alerts
```python
# From Cloud Shell or local
import os
from orchestration.cloud_functions.self_heal.shared.utils.slack_channels import send_to_slack

webhook = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
send_to_slack(
    webhook_url=webhook,
    text="🧪 Test alert from robustness improvements",
    username="Prediction Coordinator",
    icon_emoji=":test_tube:"
)
```

### Test AlertManager
```python
from shared.alerts import get_alert_manager

alert_mgr = get_alert_manager()
alert_mgr.send_alert(
    severity='info',
    title='Test Alert',
    message='Testing AlertManager integration',
    category='test_alert'
)
```

---

## Rollback Procedures

### Disable Slack Alerts
```bash
# Unset environment variable
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --remove-env-vars SLACK_WEBHOOK_URL_WARNING
```

### Disable BigQuery Inserts for Unresolved Players
```python
# Edit reader.py and comment out the BigQuery insert block
# Lines 330-350 in mlb_player_registry/reader.py
# Keep the logging - only disable BigQuery writes
```

### Revert to Print Statements (Not Recommended)
```bash
# Roll back to previous git commit
git revert <commit-hash>
```

---

## Related Documentation

- [Week 1 Deployment Handoff](../09-handoff/2026-01-21-WEEK-1-DEPLOYMENT-HANDOFF.md)
- [ArrayUnion to Subcollection Guide](../10-week-1/implementation-guides/02-arrayunion-to-subcollection.md)
- [AlertManager Documentation](../../shared/alerts/README.md)
- [Slack Channels Guide](../../orchestration/cloud_functions/self_heal/shared/utils/slack_channels.py)

---

## Support Contacts

- **Slack Channels**:
  - #nba-alerts - System warnings and errors
  - #app-error-alerts - Critical failures
  - #daily-orchestration - Health summaries

- **Cloud Logging**: https://console.cloud.google.com/logs/query?project=nba-props-platform

- **AlertManager Logs**: Check Cloud Run logs for prediction-coordinator service

---

**Last Updated**: 2026-01-20
**Maintained By**: Claude Code
**Review Schedule**: After Week 1 migration complete (Feb 5+)
