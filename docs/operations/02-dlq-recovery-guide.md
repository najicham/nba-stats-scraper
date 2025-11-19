# Dead Letter Queue (DLQ) Recovery Guide

**File:** `docs/operations/02-dlq-recovery-guide.md`
**Created:** 2025-11-18 15:15 PST
**Last Updated:** 2025-11-18 15:15 PST
**Purpose:** Handle failed message processing between Phase 1 (scrapers) and Phase 2 (raw processors)
**Status:** Current
**Audience:** On-call engineers, operators

---

## What is the DLQ?

The **Dead Letter Queue** is where Pub/Sub sends messages that failed processing after multiple retry attempts.

### Normal Flow (No Failures)

```
Phase 1: Scraper runs
  ↓ Uploads file to GCS
  ↓ Publishes message to: nba-phase1-scrapers-complete
Phase 2: Processor receives message
  ↓ Reads GCS file
  ↓ Inserts data to BigQuery
  ↓ Returns 200 OK
Pub/Sub: Deletes message ✅
```

### Failure Flow (Phase 2 Errors)

```
Phase 1: Scraper runs & publishes message
  ↓
Phase 2: Processing fails (returns 500 error)
  ↓
Pub/Sub: Retries 5 times with exponential backoff
  ↓
After 5 failed attempts:
  ↓
Pub/Sub: Moves message → nba-phase1-scrapers-complete-dlq
  ↓
Message waits in DLQ for manual intervention ⚠️
```

---

## Key Concepts

### 1. DLQ is a Notification System

The DLQ doesn't require you to "move" messages. It's a notification that something failed.

**Recovery Process:**
1. DLQ message tells you: "Processing failed for injuries on 2025-11-19"
2. You check: Do we have injury data for 2025-11-19 in BigQuery?
3. If YES → Ignore DLQ message (data was processed by later run)
4. If NO → Create NEW message to trigger reprocessing

### 2. GCS Files Still Exist

When processing fails:
- ✅ GCS file was already uploaded by scraper
- ❌ Phase 2 failed to read/process it
- ✅ File still exists in GCS bucket
- 💡 Just need Phase 2 to try again (no need to re-scrape)

### 3. Recovery = Create New Message

You don't "republish" the DLQ message. You:
1. Create a NEW message to `nba-phase1-scrapers-complete`
2. Phase 2 receives it and tries again
3. Separately clean up DLQ messages after verifying data

---

## DLQ Configuration

### Phase 1 → Phase 2 (Raw Processing)

**Subscription:** `nba-phase2-raw-sub`
- **Receives from:** `nba-phase1-scrapers-complete`
- **DLQ Topic:** `nba-phase1-scrapers-complete-dlq`
- **Max Delivery Attempts:** 5
- **Ack Deadline:** 600 seconds (10 minutes)

### Phase 2 → Phase 3 (Analytics)

**Subscription:** `nba-phase3-analytics-sub`
- **Receives from:** `nba-phase2-raw-complete`
- **DLQ Topic:** `nba-phase2-raw-complete-dlq`
- **Max Delivery Attempts:** 5
- **Ack Deadline:** 600 seconds (10 minutes)

---

## Recovery Scripts

All scripts located in: `bin/recovery/`

### 1. View DLQ Messages

```bash
./bin/recovery/view_dlq.sh [max_messages]
```

**What it does:**
- Shows all messages currently in DLQ
- Displays scraper name, GCS path, timestamp
- Does NOT remove messages (safe to run anytime)

**Example Output:**
```
Total messages in DLQ: 3

Scraper: bdl_injuries_scraper
  GCS Path: gs://nba-scraped-data/bdl/2024-25/2025-11-19/injuries.json
  Status: success
  Timestamp: 2025-11-19T00:05:00Z
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scraper: bdl_standings_scraper
  GCS Path: gs://nba-scraped-data/bdl/2024-25/2025-11-18/standings.json
  Status: success
  Timestamp: 2025-11-18T00:05:00Z
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2. Find Data Gaps & Trigger Recovery

```bash
./bin/recovery/find_data_gaps.sh [days] [scraper_type]
```

**Parameters:**
- `days` - Number of days to check (default: 7)
- `scraper_type` - Scraper to check: `bdl_injuries`, `bdl_standings`, `nbac_schedule`

**What it does:**
- Queries BigQuery for each date in the range
- Identifies dates with no data (gaps)
- Offers to create recovery messages for gaps

**Example:**
```bash
# Check last 7 days of injury data
./bin/recovery/find_data_gaps.sh 7 bdl_injuries

# Check last 14 days of standings
./bin/recovery/find_data_gaps.sh 14 bdl_standings
```

**Example Output:**
```
✅ OK: 2025-11-18 (150 rows)
✅ OK: 2025-11-17 (148 rows)
❌ GAP FOUND: 2025-11-16 (no data)
   Trigger recovery for 2025-11-16? (y/n) y
   ✅ Recovery message sent to nba-phase1-scrapers-complete
   Phase 2 will attempt to process: gs://...
✅ OK: 2025-11-15 (152 rows)
```

### 3. Clear DLQ

```bash
./bin/recovery/clear_dlq.sh
```

**What it does:**
- Permanently deletes all messages from DLQ
- Should be run AFTER verifying data coverage is complete

**When to use:**
- After running `find_data_gaps.sh` and confirming no gaps
- After triggering recovery and verifying it succeeded
- When DLQ contains old/obsolete messages

**Warning:** This permanently deletes messages. Only use after confirming data coverage!

---

## Recovery Workflow

### Step 1: Check DLQ

```bash
./bin/recovery/view_dlq.sh
```

Review what failed and when.

### Step 2: Check Data Coverage

```bash
# For each scraper type in DLQ, check gaps
./bin/recovery/find_data_gaps.sh 7 bdl_injuries
./bin/recovery/find_data_gaps.sh 7 bdl_standings
```

This will:
- Show which dates have data ✅
- Show which dates are missing ❌
- Offer to trigger recovery for gaps

### Step 3: Verify Recovery

After triggering recovery, check Phase 2 logs:

```bash
gcloud run services logs read nba-phase2-raw-processors \
  --region=us-west2 \
  --limit=50 \
  --format="table(timestamp,severity,textPayload)"
```

Look for:
- "Processing Scraper Completion message from: ..."
- "Successfully processed X records"
- POST 200 (success)

### Step 4: Clean Up DLQ

After confirming data is complete:

```bash
./bin/recovery/clear_dlq.sh
```

---

## Manual Recovery (Advanced)

If you need to manually create a recovery message:

```bash
# Create message for specific scraper + date
gcloud pubsub topics publish nba-phase1-scrapers-complete \
  --message='{
    "scraper_name": "bdl_injuries_scraper",
    "gcs_path": "gs://nba-scraped-data/bdl/2024-25/2025-11-19/injuries.json",
    "status": "success",
    "timestamp": "2025-11-19T00:05:00Z",
    "recovery": true,
    "execution_id": "manual-recovery-'$(date +%s)'"
  }'
```

---

## Monitoring DLQ Depth

### Check Current DLQ Size

```bash
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

### Set Up Alerts (Recommended)

Create a Cloud Monitoring alert:
- **Metric:** `pubsub.googleapis.com/subscription/num_undelivered_messages`
- **Resource:** `nba-phase1-scrapers-complete-dlq-sub`
- **Condition:** `> 0` for more than 5 minutes
- **Notification:** Email to ops team

---

## Common Scenarios

### Scenario 1: Temporary Phase 2 Outage

**Situation:** Phase 2 service was down for 1 hour

**What Happened:**
- Messages retried 5 times during outage
- All failed and moved to DLQ

**Recovery:**
```bash
# Check what dates are affected
./bin/recovery/view_dlq.sh

# Check if later runs covered the data
./bin/recovery/find_data_gaps.sh 7 bdl_injuries

# If gaps found, trigger recovery
# (Script will offer to create recovery messages)

# After recovery completes, clean DLQ
./bin/recovery/clear_dlq.sh
```

### Scenario 2: Code Bug in Phase 2

**Situation:** Phase 2 had a bug that caused all injuries processing to fail

**What Happened:**
- Multiple days of injuries data in DLQ
- Bug has been fixed

**Recovery:**
```bash
# Check gaps
./bin/recovery/find_data_gaps.sh 14 bdl_injuries

# Trigger recovery for each gap
# (Phase 2 will now process successfully with bug fixed)

# Verify processing succeeded
gcloud run services logs read nba-phase2-raw-processors \
  --region=us-west2 --limit=100

# Clean DLQ
./bin/recovery/clear_dlq.sh
```

### Scenario 3: Corrupted GCS File

**Situation:** One specific file is corrupted and can't be processed

**What Happened:**
- Single message in DLQ for bad file
- Later runs succeeded (different files)

**Recovery:**
```bash
# Check if data exists for that date
./bin/recovery/find_data_gaps.sh 1 bdl_injuries

# If data exists (later run worked)
# Just clean the DLQ - no recovery needed
./bin/recovery/clear_dlq.sh
```

---

## Troubleshooting

### DLQ keeps filling up

**Cause:** Phase 2 has ongoing issues

**Action:**
1. Check Phase 2 logs for errors
2. Fix the underlying issue
3. Then run recovery workflow

### Recovery messages also failing

**Cause:** Issue not resolved yet

**Action:**
1. Check Phase 2 logs for error details
2. Investigate GCS file (does it exist? is it valid?)
3. Fix issue before retrying

### Can't tell what date a message is for

**Action:**
Look at `gcs_path` in DLQ message:
```
gs://nba-scraped-data/bdl/2024-25/2025-11-19/injuries.json
                                    ^^^^^^^^^^^
                                    This is the date
```

---

## Related Documentation

**Monitoring & Alerts:**
- `docs/monitoring/06-alerting-strategy-and-escalation.md` - DLQ alert configuration
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring

**Operations:**
- `docs/operations/01-backfill-operations-guide.md` - Backfill recovery procedures

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub health checks

**Architecture:**
- `docs/architecture/04-event-driven-pipeline-architecture.md` - Event-driven design

**Processors:**
- `docs/processors/01-phase2-operations-guide.md` - Phase 2 operations

---

## Quick Reference

| Task | Command |
|------|---------|
| View DLQ | `./bin/recovery/view_dlq.sh` |
| Find gaps (injuries) | `./bin/recovery/find_data_gaps.sh 7 bdl_injuries` |
| Find gaps (standings) | `./bin/recovery/find_data_gaps.sh 7 bdl_standings` |
| Check DLQ count | `gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub --format="value(numUndeliveredMessages)"` |
| Clear DLQ | `./bin/recovery/clear_dlq.sh` |
| View Phase 2 logs | `gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=50` |
