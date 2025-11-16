# Pub/Sub Integration Verification Guide

**File:** `docs/infrastructure/01-pubsub-integration-verification.md`
**Created:** 2025-11-14 17:44 PST
**Last Updated:** 2025-11-15 (moved from orchestration/ to infrastructure/)
**Purpose:** Guide for verifying and testing Phase 1 → Phase 2 Pub/Sub integration
**Status:** Phase 2 integration is DEPLOYED and WORKING (verified Nov 14-15, 2025)

---

## Table of Contents

1. [Current Status](#current-status)
2. [How Pub/Sub Integration Works](#how-pubsub-integration-works)
3. [Verification Commands](#verification-commands)
4. [Testing the Integration](#testing-the-integration)
5. [Debugging Issues](#debugging-issues)
6. [Known Patterns & Gotchas](#known-patterns--gotchas)
7. [Next Steps](#next-steps)

---

## Current Status

### ✅ What's Working (Verified Nov 14, 2025)

**Deployment Status:**
- **Scrapers:** `nba-scrapers-00081-twl` (deployed with Pub/Sub code)
- **Processors:** `nba-processors-00034-t88` (deployed with message handling)
- **Pub/Sub Topic:** `nba-scraper-complete` (ACTIVE)
- **Pub/Sub Subscription:** `nba-processors-sub` (ACTIVE, push to processors)

**Evidence of Working Integration:**
```bash
# Scrapers publishing events (past hour):
2025-11-15T01:08:36Z - INFO: ✅ Phase 2 notified via Pub/Sub (message_id: 16921384163928312)
2025-11-15T01:08:07Z - INFO: ✅ Published Pub/Sub event: bdl_active_players_scraper (status=no_data)

# Processors receiving events (past hour):
2025-11-15T01:08:36Z - INFO: Processing Scraper Completion message from: nbac_schedule_api
2025-11-15T01:08:07Z - INFO: Processing Scraper Completion message from: bdl_active_players_scraper
```

**Current Behavior:**
- All scrapers publishing events (both `success` and `no_data`)
- Processors receiving and handling events correctly
- `no_data` events are being skipped (expected - no files to process)
- End-to-end flow with actual data not yet verified (waiting for game day)

### ⏳ What Needs Verification

- **End-to-end with real data:** Need to verify processors actually load data to BigQuery when scrapers find data
- **All scraper types:** Verify every scraper class publishes events correctly
- **Error handling:** Verify failed scrapers also publish failure events
- **Phase 3 trigger:** Confirm Phase 2 processors trigger Phase 3 analytics processors

---

## How Pub/Sub Integration Works

### Architecture Overview

```
Phase 1 (Scrapers)
    ↓ GCS file written
    ↓ Pub/Sub event published
Phase 2 (Processors)
    ↓ Process GCS file → BigQuery raw tables
    ↓ Pub/Sub event published
Phase 3 (Analytics)
    ↓ Generate summaries → BigQuery analytics tables
```

### Code Locations

**1. Scraper Publishing Code**

File: `scrapers/scraper_base.py`

```python
# Line 308: Success case
self._publish_completion_event_to_pubsub()

# Line 363: Failure case
self._publish_failed_event_to_pubsub(e)
```

**Publishing methods (lines 650-737):**
```python
def _publish_completion_event_to_pubsub(self):
    """
    Publish scraper completion event to Pub/Sub for Phase 2 processors.
    Never fails the scraper - logs errors but continues.
    """
    from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

    publisher = ScraperPubSubPublisher()
    status, record_count = self._determine_execution_status()

    message_id = publisher.publish_completion_event(
        scraper_name=self._get_scraper_name(),
        execution_id=self.run_id,
        status=status,  # 'success' | 'no_data' | 'failed'
        gcs_path=self.opts.get('gcs_output_path'),
        record_count=record_count,
        duration_seconds=self.stats.get('total_runtime', 0),
        workflow=self.opts.get('workflow', 'MANUAL'),
        error_message=None,
        metadata={...}
    )
```

**2. Pub/Sub Publisher Utility**

File: `scrapers/utils/pubsub_utils.py`

```python
class ScraperPubSubPublisher:
    """Publishes scraper completion events to Pub/Sub."""

    def publish_completion_event(self, scraper_name, execution_id, status, ...):
        """
        Publish event to nba-scraper-complete topic.

        Message format:
        {
            "name": "nbac_injury_report",          # Required by processors
            "scraper_name": "nbac_injury_report",  # Backwards compatibility
            "execution_id": "a1b2c3d4",
            "status": "success",  # or "no_data" or "failed"
            "gcs_path": "gs://bucket/path/file.json",
            "record_count": 450,
            "duration_seconds": 3.5,
            "timestamp": "2025-11-14T23:30:00Z",
            "workflow": "morning_operations",
            "error_message": null,
            "metadata": {...}
        }
        """
```

**3. Processor Message Handling**

File: `processors/phase2_raw/main_processor_service.py` (likely)

```python
def process_scraper_complete_message(message_data):
    """
    Handle scraper completion event from Pub/Sub.

    1. Extract scraper_name and gcs_path from message
    2. If status='no_data' or no gcs_path → skip processing
    3. If status='success' → download GCS file and load to BigQuery
    4. Publish Phase 3 event if successful
    """
```

### Message Flow

**1. Scraper completes successfully:**
```
ScraperBase.run()
  → export_data() [writes to GCS]
  → _log_execution_to_bigquery() [logs to scraper_execution_log]
  → _publish_completion_event_to_pubsub() [publishes to Pub/Sub]
  → Returns to caller
```

**2. Pub/Sub delivers message:**
```
Pub/Sub Topic: nba-scraper-complete
  → Push Subscription: nba-processors-sub
  → POST to https://nba-processors-f7p3g7f6ya-wl.a.run.app/process
  → Processor receives message
```

**3. Processor handles message:**
```
Processor receives POST
  → Parse message_data
  → Check status field
  → If status='success' AND gcs_path exists:
      → Download file from GCS
      → Load to BigQuery raw table
      → Publish Phase 3 event
  → If status='no_data' OR no gcs_path:
      → Log and skip
  → Return 200 OK to Pub/Sub
```

---

## Verification Commands

### 1. Check If Scrapers Are Publishing

**Real-time monitoring (live tail):**
```bash
# Watch for Pub/Sub publishing events (run in separate terminal)
gcloud logging tail "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\""

# Then trigger a scraper manually to see if it publishes
```

**Recent publishing activity:**
```bash
# Check last 20 Pub/Sub events from scrapers
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\"" \
  --limit=20 \
  --format="table(timestamp,textPayload)" \
  --freshness=1h

# Expected output:
# 2025-11-15T01:08:36Z  INFO: ✅ Phase 2 notified via Pub/Sub (message_id: 16921384163928312)
# 2025-11-15T01:08:07Z  INFO: ✅ Phase 2 notified via Pub/Sub (message_id: 16921443968387856)
```

**Check specific scraper:**
```bash
# Example: Check if nbac_injury_report publishes events
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"nbac_injury_report\"" \
  --limit=10 \
  --format=json \
  --freshness=1d | jq '.[] | select(.textPayload | contains("Phase 2 notified"))'
```

**Verify publishing works for ALL scrapers:**
```bash
# Get list of scrapers that published in last 24 hours
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"Published Pub/Sub event\"" \
  --limit=500 \
  --format=json \
  --freshness=1d \
  | jq -r '.[] | .textPayload' \
  | grep -oP '(?<=event: )[^ ]+' \
  | sort -u

# Compare with orchestration log to see which scrapers ran
bq query --use_legacy_sql=false "
SELECT DISTINCT scraper_name
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at) = CURRENT_DATE('America/New_York')
ORDER BY scraper_name
"
```

### 2. Check If Processors Are Receiving

**Real-time monitoring:**
```bash
# Watch for incoming messages to processors
gcloud logging tail "resource.labels.service_name=nba-processors AND textPayload:\"Processing Scraper Completion\""
```

**Recent processing activity:**
```bash
# Check last 20 messages received by processors
gcloud logging read \
  "resource.labels.service_name=nba-processors AND textPayload:\"Processing Scraper Completion\"" \
  --limit=20 \
  --format="table(timestamp,textPayload)" \
  --freshness=1h

# Expected output:
# 2025-11-15T01:08:36Z  INFO: Processing Scraper Completion message from: nbac_schedule_api
# 2025-11-15T01:08:07Z  INFO: Processing Scraper Completion message from: bdl_active_players_scraper
```

**Check if processors are actually loading data:**
```bash
# Look for "Successfully loaded" messages (means data made it to BigQuery)
gcloud logging read \
  "resource.labels.service_name=nba-processors AND textPayload:\"Successfully loaded\"" \
  --limit=20 \
  --format="table(timestamp,textPayload)" \
  --freshness=1d

# If empty, processors are only getting no_data events (expected during offseason)
```

**Check for processor errors:**
```bash
# Look for any errors in processor logs
gcloud logging read \
  "resource.labels.service_name=nba-processors AND severity>=ERROR" \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)" \
  --freshness=1d
```

### 3. Check Pub/Sub Infrastructure

**Check topic status:**
```bash
# Verify topic exists and is active
gcloud pubsub topics describe nba-scraper-complete --format=json

# Expected output includes:
# "name": "projects/nba-props-platform/topics/nba-scraper-complete"
# "messageRetentionDuration": "86400s"
```

**Check subscription status:**
```bash
# Verify subscription is active and connected
gcloud pubsub subscriptions describe nba-processors-sub --format=json

# Key fields to check:
# "state": "ACTIVE"
# "pushConfig.pushEndpoint": "https://nba-processors-f7p3g7f6ya-wl.a.run.app/process"
# "topic": "projects/nba-props-platform/topics/nba-scraper-complete"
# "deadLetterPolicy.deadLetterTopic": "projects/nba-props-platform/topics/nba-scraper-complete-dlq"
```

**Check Dead Letter Queue:**
```bash
# Check if any messages failed and moved to DLQ
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub --format=json

# Look for:
# "numUndeliveredMessages": 0  # Should be 0 if everything working

# If numUndeliveredMessages > 0, check what failed:
gcloud logging read \
  "resource.labels.service_name=nba-processors AND severity>=ERROR" \
  --limit=50 \
  --freshness=7d
```

### 4. Check Deployment Revisions

**Verify scrapers have Pub/Sub code:**
```bash
# Check current scraper revision
gcloud run services describe nba-scrapers --platform=managed \
  --format="value(status.latestCreatedRevisionName,metadata.creationTimestamp)"

# Expected: nba-scrapers-00081-twl or later (deployed 2025-07-21 or later)
# Pub/Sub code was added in revision 00073 (Nov 13, 2025)
```

**Verify processors are deployed:**
```bash
# Check current processor revision
gcloud run services list --format="table(metadata.name,status.latestCreatedRevisionName,status.url)"

# Expected to see:
# nba-processors            nba-processors-00034-t88 or later
# nba-analytics-processors  nba-analytics-processors-00004-wp9 or later
```

---

## Testing the Integration

### Test 1: Manual Scraper Execution

**Trigger a single scraper and verify Pub/Sub flow:**

```bash
# 1. Start watching processor logs in one terminal
gcloud logging tail "resource.labels.service_name=nba-processors"

# 2. In another terminal, trigger a scraper via orchestration endpoint
# (Use a scraper that's likely to find data)
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/GetNbaComScheduleApi \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "basketball",
    "season": "2025",
    "group": "prod"
  }'

# 3. Watch for sequence:
# - Scraper logs: "✅ Phase 2 notified via Pub/Sub (message_id: ...)"
# - Processor logs: "Processing Scraper Completion message from: nbac_schedule_api"
# - Processor logs: "Successfully loaded X rows to BigQuery" (if data found)
```

**Verify the event was logged:**
```bash
# Check scraper execution log
bq query --use_legacy_sql=false "
SELECT execution_id, scraper_name, status, gcs_path, data_summary
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE scraper_name = 'nbac_schedule_api'
ORDER BY triggered_at DESC
LIMIT 1
"

# If status='success', should have gcs_path populated
# If status='no_data', gcs_path will be NULL (expected)
```

### Test 2: Verify Message Format

**Capture and inspect a Pub/Sub message:**

```bash
# Get recent scraper execution
RUN_ID=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT execution_id FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
   ORDER BY triggered_at DESC LIMIT 1" | tail -n 1)

# Find the corresponding Pub/Sub log
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"$RUN_ID\"" \
  --limit=5 \
  --format=json \
  | jq '.[] | select(.textPayload | contains("Published Pub/Sub event"))'
```

**Verify message includes required fields:**

Required fields per `docs/orchestration/pubsub-schema-management-2025-11-14.md`:
- ✅ `name` (processors require this!)
- ✅ `scraper_name` (backwards compatibility)
- ✅ `execution_id`
- ✅ `status` (success/no_data/failed)
- ✅ `timestamp`
- ✅ `gcs_path` (if status=success)
- ✅ `record_count`
- ✅ `duration_seconds`
- ✅ `workflow`

### Test 3: Test Failure Handling

**Trigger a scraper with invalid parameters to test failure path:**

```bash
# 1. Start watching logs
gcloud logging tail "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\""

# 2. Trigger scraper with bad params (will fail)
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/GetNbaComScheduleApi \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "basketball",
    "season": "invalid",
    "group": "prod"
  }'

# 3. Verify you see:
# - Scraper logs: "✅ Phase 2 notified of failure (message_id: ...)"
# - Processor logs: "Processing Scraper Completion message from: nbac_schedule_api"
# - Processor logs: "Skipping processing for nbac_schedule_api (status=failed)"
```

**Check failed execution was logged:**
```bash
bq query --use_legacy_sql=false "
SELECT execution_id, scraper_name, status, error_type, error_message
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE scraper_name = 'nbac_schedule_api'
  AND status = 'failed'
ORDER BY triggered_at DESC
LIMIT 1
"
```

### Test 4: End-to-End Data Flow (Game Day)

**When games are happening, verify complete flow:**

```bash
# 1. Check orchestration schedule
bq query --use_legacy_sql=false "
SELECT workflow_name, expected_run_time, status
FROM \`nba-props-platform.nba_orchestration.daily_expected_schedule\`
WHERE game_date = CURRENT_DATE('America/New_York')
ORDER BY expected_run_time
LIMIT 10
"

# 2. Wait for a workflow that should find data (e.g., betting_lines around game time)

# 3. Check scraper found data
bq query --use_legacy_sql=false "
SELECT scraper_name, status, data_summary
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at) = CURRENT_DATE('America/New_York')
  AND status = 'success'
  AND JSON_EXTRACT_SCALAR(data_summary, '$.record_count') != '0'
ORDER BY triggered_at DESC
LIMIT 10
"

# 4. Verify processors loaded the data
gcloud logging read \
  "resource.labels.service_name=nba-processors AND textPayload:\"Successfully loaded\"" \
  --limit=10 \
  --freshness=1h

# 5. Verify data landed in BigQuery raw tables
bq query --use_legacy_sql=false "
SELECT COUNT(*) as row_count, MAX(created_at) as latest_load
FROM \`nba-props-platform.nba_raw.oddsapi_events\`
WHERE DATE(created_at) = CURRENT_DATE()
"
```

---

## Debugging Issues

### Issue 1: Scrapers Not Publishing

**Symptoms:**
- No "Phase 2 notified" logs in scraper output
- Processors not receiving any messages

**Diagnosis:**
```bash
# 1. Check if google-cloud-pubsub is installed
gcloud run services describe nba-scrapers --platform=managed \
  --format=json | jq '.spec.template.spec.containers[0].image'

# 2. Check for ImportError in logs
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"google-cloud-pubsub\"" \
  --limit=10 \
  --freshness=1d

# 3. Check if scraper_base.py has publishing code
grep -n "_publish_completion_event_to_pubsub" scrapers/scraper_base.py
# Should show lines 308, 650

# 4. Verify scraper revision is recent
gcloud run services describe nba-scrapers --platform=managed \
  --format="value(status.latestCreatedRevisionName)"
# Should be 00081-twl or later
```

**Fix:**
```bash
# If old revision, redeploy scrapers
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

### Issue 2: Processors Not Receiving Messages

**Symptoms:**
- Scrapers publishing events (see message_ids in logs)
- Processors not logging "Processing Scraper Completion message"

**Diagnosis:**
```bash
# 1. Check subscription is ACTIVE and pointing to correct endpoint
gcloud pubsub subscriptions describe nba-processors-sub --format=json

# Verify:
# - "state": "ACTIVE"
# - "pushConfig.pushEndpoint": "https://nba-processors-f7p3g7f6ya-wl.a.run.app/process"

# 2. Check for delivery errors
gcloud logging read \
  "resource.type=pubsub_subscription AND resource.labels.subscription_id=nba-processors-sub" \
  --limit=20 \
  --freshness=1h

# 3. Check processor service is running
gcloud run services describe nba-processors --platform=managed \
  --format="value(status.conditions[0].status,status.conditions[0].message)"

# Should be: True, ""
```

**Fix:**
```bash
# If subscription pointing to wrong endpoint
gcloud pubsub subscriptions update nba-processors-sub \
  --push-endpoint=https://nba-processors-f7p3g7f6ya-wl.a.run.app/process

# If processor service is down, check logs and redeploy
./bin/processors/deploy/deploy_processors.sh
```

### Issue 3: Messages Going to Dead Letter Queue

**Symptoms:**
- Messages published but not processed
- numUndeliveredMessages > 0 in DLQ subscription

**Diagnosis:**
```bash
# 1. Check DLQ message count
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# If > 0, check why messages failed
gcloud logging read \
  "resource.labels.service_name=nba-processors AND severity>=ERROR" \
  --limit=50 \
  --freshness=7d \
  | grep -i "missing required field\|error"
```

**Common causes:**
1. **Schema mismatch:** Processor expects field that scraper didn't send
   - See `docs/orchestration/pubsub-schema-management-2025-11-14.md` for schema
   - Verify scraper sends `name` field (required by processors)

2. **Processor error:** Bug in processor code
   - Check processor logs for stack traces
   - Fix bug and redeploy processors

3. **Old malformed messages:** From before schema fix
   - Purge DLQ after fixing issue (see below)

**Fix:**
```bash
# Purge DLQ to stop old error emails
gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub \
  --time=$(date -u -d '1 hour ago' --iso-8601=seconds)

# Verify DLQ is now empty
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
# Should be: 0
```

### Issue 4: No Data Being Loaded to BigQuery

**Symptoms:**
- Scrapers publishing events with status=success
- Processors receiving messages
- No "Successfully loaded" logs
- BigQuery tables not updating

**Diagnosis:**
```bash
# 1. Check if processor is skipping due to no_data
gcloud logging read \
  "resource.labels.service_name=nba-processors AND textPayload:\"Skipping processing\"" \
  --limit=20 \
  --freshness=1h

# If you see "status=no_data", scrapers aren't finding data (expected during offseason)

# 2. Check if GCS files exist
gsutil ls gs://nba-scraper-data/$(date +%Y/%m/%d)/ | head -20

# 3. Check for processor errors during BigQuery load
gcloud logging read \
  "resource.labels.service_name=nba-processors AND (textPayload:\"BigQuery\" OR textPayload:\"load\")" \
  --limit=20 \
  --freshness=1h
```

**Fix:**
- If status=no_data during offseason: This is expected, wait for games to resume
- If GCS files missing: Check scraper export configuration
- If BigQuery errors: Check processor logs for schema mismatches, fix and redeploy

---

## Known Patterns & Gotchas

### Pattern 1: "no_data" is Success, Not Failure

**Understanding the 3-status system:**

```python
# Status values in scraper_execution_log:
# - 'success' = Scraper ran AND found new data (record_count > 0)
# - 'no_data' = Scraper ran successfully BUT found no new data (record_count = 0)
# - 'failed' = Scraper encountered an error

# IMPORTANT: Both 'success' and 'no_data' mean the scraper worked correctly!
```

**Why you see lots of "no_data":**
- During offseason: No games = no betting lines = no injury reports = no_data
- Hourly checks: Scraper runs every hour but data only updates once/day = 23 no_data, 1 success
- Discovery mode: Controller keeps trying hourly until first success, then stops

**What to look for:**
```bash
# This is GOOD (scraper working, just no new data):
INFO: Skipping processing for nbac_injury_report (status=no_data)

# This is BAD (scraper broken):
ERROR: Scraper failed: nbac_injury_report
```

### Pattern 2: Silent Failures Won't Break Scrapers

**Pub/Sub publishing failures are caught and logged, but don't fail the scraper:**

```python
# From scraper_base.py:650-700
def _publish_completion_event_to_pubsub(self):
    try:
        # ... publishing logic ...
    except ImportError as e:
        # google-cloud-pubsub not installed - log warning
        logger.warning(f"Pub/Sub not available: {e}")
    except Exception as e:
        # Don't fail the scraper if Pub/Sub publishing fails
        logger.error(f"Failed to publish Pub/Sub event: {e}")
        sentry_sdk.capture_exception(e)
```

**Why:** Scraper's primary job is collecting data. If Pub/Sub fails, data still saved to GCS and logged to BigQuery.

**Detection:**
```bash
# Look for publishing warnings
gcloud logging read \
  "resource.labels.service_name=nba-scrapers AND textPayload:\"Failed to publish\"" \
  --limit=20 \
  --freshness=1d
```

### Pattern 3: Push vs Pull Subscriptions

**nba-processors-sub is a PUSH subscription:**
- Pub/Sub automatically POSTs messages to processor endpoint
- Can't manually pull messages with `gcloud pubsub subscriptions pull`
- Must monitor processor logs to see incoming messages

**If you try to pull:**
```bash
$ gcloud pubsub subscriptions pull nba-processors-sub --limit=5
ERROR: This method is not supported for this subscription type.
```

**Why:** Push subscriptions are for real-time processing. Pull subscriptions are for batch processing.

### Pattern 4: Message IDs for Correlation

**Every Pub/Sub message gets a unique message_id:**

```bash
# Scraper log:
INFO: ✅ Published Pub/Sub event: nbac_injury_report (message_id=16921384163928312)

# Processor log (same message):
INFO: Processing Scraper Completion message from: nbac_injury_report
```

**Use for debugging:**
```bash
# Find scraper and processor logs for same message
MESSAGE_ID="16921384163928312"

# Scraper side
gcloud logging read "resource.labels.service_name=nba-scrapers AND textPayload:\"$MESSAGE_ID\"" --limit=5

# Processor side
gcloud logging read "resource.labels.service_name=nba-processors AND timestamp>\"2025-11-15T01:08:00Z\" AND timestamp<\"2025-11-15T01:09:00Z\"" --limit=5
```

### Pattern 5: DLQ Retries After Deployments

**Dead Letter Queue behavior:**
- Messages retry up to 5 times over ~24 hours
- Old broken messages can send error emails long after fix deployed

**Symptom:**
```
# You fix a bug and deploy at 2 PM
# At 2 AM next day, you get error emails from YESTERDAY'S failures
# (Old messages finally gave up after 5th retry)
```

**Prevention:**
```bash
# Always purge DLQ after fixing schema/processor bugs
gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub \
  --time=$(date -u --iso-8601=seconds)
```

See `docs/orchestration/pubsub-schema-management-2025-11-14.md` for full prevention guide.

---

## Next Steps

### Immediate Actions (Next Chat Session)

1. **Verify all scraper types publish events:**
   ```bash
   # Get list of all scraper classes
   find scrapers -name "*.py" -exec grep -l "class Get" {} \; | head -20

   # Cross-reference with scrapers that published events
   # (See "Verify publishing works for ALL scrapers" command above)
   ```

2. **Test end-to-end flow with real data:**
   - Wait for game day (next NBA games)
   - Monitor betting_lines workflow execution
   - Verify data flows: Scraper → Pub/Sub → Processor → BigQuery
   - Check Phase 3 analytics processors are also triggered

3. **Document missing pieces:**
   - Phase 2 → Phase 3 Pub/Sub handoff (do processors publish events?)
   - Phase 3 analytics processor deployment status
   - Complete event schema for all phases

### Long-term Improvements

1. **Add schema validation tests:**
   - Create integration test that verifies published messages match schema
   - See `docs/orchestration/pubsub-schema-management-2025-11-14.md` for examples

2. **Set up Grafana alerts:**
   - Alert if scraper publishes but processor doesn't receive within 1 minute
   - Alert if DLQ message count > 0
   - Alert if schema errors detected

3. **Create deployment checklist:**
   - Pre-deployment: Run integration tests including Pub/Sub schema tests
   - Post-deployment: Verify publishing, check DLQ, purge old messages

4. **Add smoke tests:**
   - After scraper deployment: Trigger one scraper, verify Pub/Sub event
   - After processor deployment: Send test message, verify processing

---

## Quick Reference Commands

**Daily health check:**
```bash
# Are scrapers publishing?
gcloud logging read "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\"" --limit=5 --freshness=1h

# Are processors receiving?
gcloud logging read "resource.labels.service_name=nba-processors AND textPayload:\"Processing Scraper Completion\"" --limit=5 --freshness=1h

# Any errors?
gcloud logging read "resource.labels.service_name=nba-processors AND severity>=ERROR" --limit=5 --freshness=1h

# DLQ empty?
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub --format="value(numUndeliveredMessages)"
```

**Test single scraper:**
```bash
# Trigger scraper
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/GetNbaComScheduleApi \
  -H "Content-Type: application/json" \
  -d '{"sport": "basketball", "season": "2025", "group": "prod"}'

# Watch for Pub/Sub event
gcloud logging tail "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\""

# Watch for processor receiving
gcloud logging tail "resource.labels.service_name=nba-processors AND textPayload:\"Processing\""
```

**Purge DLQ after deployment:**
```bash
gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub --time=$(date -u --iso-8601=seconds)
```

---

## Related Documentation

- **Pub/Sub Schema:** `docs/orchestration/pubsub-schema-management-2025-11-14.md`
- **Phase 1 Orchestration:** `bin/orchestration/README.md`
- **Monitoring:** `docs/orchestration/grafana-monitoring-guide.md`
- **Error Notifications:** `docs/orchestration/enhanced-error-notifications-summary.md`
- **Scraper Parameters:** `docs/scrapers/parameter-formats-reference.md`

---

**Last Updated:** 2025-11-14
**Verified Working:** Yes (as of Nov 14, 2025)
**Next Verification:** Game day to test with real data
**Contact:** See scraper_execution_log for execution details
