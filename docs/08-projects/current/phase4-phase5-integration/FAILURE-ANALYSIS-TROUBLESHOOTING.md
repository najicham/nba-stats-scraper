# Failure Analysis & Troubleshooting Guide

**Created:** 2025-11-28 9:08 PM PST
**Last Updated:** 2025-11-28 9:08 PM PST
**Purpose:** Systematic analysis of all failure points and recovery procedures

---

## Table of Contents

1. [Overview](#overview)
2. [Failure Detection Strategy](#failure-detection-strategy)
3. [Phase 1: Scrapers](#phase-1-scrapers)
4. [Phase 2: Raw Processing](#phase-2-raw-processing)
5. [Phase 2→3 Orchestrator](#phase-23-orchestrator)
6. [Phase 3: Analytics](#phase-3-analytics)
7. [Phase 3→4 Orchestrator](#phase-34-orchestrator)
8. [Phase 4: Precompute](#phase-4-precompute)
9. [Phase 4 Internal Orchestrator](#phase-4-internal-orchestrator)
10. [Phase 5: Predictions](#phase-5-predictions)
11. [Cross-Cutting Failures](#cross-cutting-failures)
12. [Recovery Procedures](#recovery-procedures)
13. [Prevention Strategies](#prevention-strategies)

---

## Overview

This document systematically analyzes every failure point in the pipeline, how the system detects and handles failures, what self-heals automatically, and what requires manual intervention.

### Failure Categories

1. **Transient Failures** - Temporary issues that resolve themselves
2. **Retryable Failures** - Can succeed on retry
3. **Permanent Failures** - Require manual intervention
4. **Silent Failures** - System appears healthy but produces bad data

### Self-Healing Levels

- 🟢 **Auto-Heal:** System automatically recovers, no action needed
- 🟡 **Auto-Retry:** System retries automatically, may need monitoring
- 🔴 **Manual:** Requires human intervention

---

## Failure Detection Strategy

### Built-In Detection Mechanisms

1. **processor_run_history table**
   - Every processor logs start and completion
   - Status field: success, partial, failed, skipped
   - Alerts triggered on failed status

2. **Cloud Run health checks**
   - /health endpoints on all services
   - Automatic restarts on crash

3. **Pub/Sub Dead Letter Queues (DLQ)**
   - Failed message delivery → DLQ
   - Can inspect and retry from DLQ

4. **Alert Manager**
   - Monitors processor_run_history
   - Sends Slack/email on failures

5. **Orchestrator State (Firestore)**
   - Tracks phase completion
   - Can detect stuck/incomplete phases

6. **BigQuery Table Metadata**
   - Last modified time
   - Row counts
   - Data freshness checks

---

## Phase 1: Scrapers

### Failure Point 1.1: Scraper API Unavailable

**Scenario:** NBA.com API returns 503, timeout, or rate limit

**Detection:**
- Scraper catches exception
- Logs error with run_history
- Publishes status='failed' to Pub/Sub

**Self-Healing:** 🟡 Auto-Retry
- Cloud Scheduler retries next scheduled run (1-4 hours)
- Most API issues resolve within hours

**Manual Recovery:**
```bash
# Check scraper logs
gcloud run services logs read nba-phase1-scrapers --limit=100

# Manual retry
curl -X POST https://nba-phase1-scrapers.../scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'
```

**Prevention:**
- Implement exponential backoff in scraper
- Add circuit breaker (stop retrying after N failures)
- Cache responses when possible

---

### Failure Point 1.2: Scraper Gets Partial Data

**Scenario:** API returns 200 but missing some games/players

**Detection:**
- Row count validation
- Expected games validation (check against schedule)
- Data completeness checks

**Self-Healing:** 🔴 Manual
- Cannot automatically detect what's missing
- Requires comparison with schedule

**Manual Recovery:**
```bash
# Check what was scraped
bq query "SELECT COUNT(*) FROM nba_raw.bdl_games WHERE game_date = '2025-01-15'"

# Compare with schedule (expected games)
# If mismatch, re-run scraper
```

**Prevention:**
- Add expected row count validation
- Compare with schedule API
- Alert if count < expected

---

### Failure Point 1.3: Scraper Pub/Sub Publish Fails

**Scenario:** Scraper succeeds but can't publish completion event

**Detection:**
- Scraper logs error: "Failed to publish Pub/Sub event"
- Phase 2 never triggers
- Monitoring detects no Phase 2 activity

**Self-Healing:** 🔴 Manual
- Data is saved to GCS, but Phase 2 doesn't know about it
- Manual trigger needed

**Manual Recovery:**
```bash
# Option 1: Re-run scraper (idempotent, will overwrite GCS file)
curl -X POST https://nba-phase1-scrapers.../scrape \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'

# Option 2: Manually trigger Phase 2
curl -X POST https://nba-phase2-raw-processors.../process \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15", "gcs_path": "gs://..."}'
```

**Prevention:**
- Add retry logic to Pub/Sub publishing (3 retries with backoff)
- Log published message ID for verification
- Add dead letter queue for failed publishes

---

### Failure Point 1.4: Scraper Crashes Mid-Execution

**Scenario:** Cloud Run instance killed (OOM, timeout, crash)

**Detection:**
- Cloud Run logs show container exit
- No completion in processor_run_history
- Alert on timeout (>10 minutes for scraper)

**Self-Healing:** 🟡 Auto-Retry
- Cloud Scheduler retries next scheduled run
- Scraper is idempotent (overwrites GCS file)

**Manual Recovery:**
```bash
# Check Cloud Run logs for OOM/crash
gcloud run services logs read nba-phase1-scrapers --limit=50

# If OOM, increase memory allocation
gcloud run services update nba-phase1-scrapers --memory=2Gi

# Manual retry
curl -X POST https://nba-phase1-scrapers.../scrape \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'
```

**Prevention:**
- Set appropriate memory/timeout limits
- Add memory monitoring
- Implement streaming for large datasets
- Add checkpointing for long-running scrapers

---

### Failure Point 1.5: Data Quality Issues

**Scenario:** Scraper succeeds but data is malformed/invalid

**Detection:**
- Phase 2 schema validation fails
- BigQuery rejects data
- Data type mismatches

**Self-Healing:** 🔴 Manual
- Requires fixing scraper logic or data source
- Cannot auto-recover from bad data

**Manual Recovery:**
```bash
# Check Phase 2 error logs
gcloud run services logs read nba-phase2-raw-processors --limit=50

# Identify schema issue
# Fix scraper code
# Re-run scraper with fix
```

**Prevention:**
- Add schema validation in scraper before saving
- Unit tests with real API response examples
- Alert on unexpected data shapes
- Version scraper code with schema

---

## Phase 2: Raw Processing

### Failure Point 2.1: Pub/Sub Message Undeliverable

**Scenario:** Message fails delivery after max retries

**Detection:**
- Message appears in DLQ: `nba-phase1-scrapers-complete-dlq`
- Alert on DLQ message count > 0

**Self-Healing:** 🔴 Manual
- Message stuck in DLQ, won't retry automatically
- Requires investigation and manual retry

**Manual Recovery:**
```bash
# Inspect DLQ messages
gcloud pubsub subscriptions pull nba-phase1-scrapers-complete-dlq-sub \
  --limit=10 --format=json

# Identify issue (bad JSON, missing field, etc.)

# Option 1: Fix issue and republish manually
gcloud pubsub topics publish nba-phase1-scrapers-complete \
  --message='{"scraper": "bdl_games", ...}'

# Option 2: Trigger Phase 2 directly
curl -X POST https://nba-phase2-raw-processors.../process \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'
```

**Prevention:**
- Validate message format before publishing
- Add message schema validation in Phase 2
- Monitor DLQ size with alerts
- Add DLQ processing Cloud Function (auto-retry logic)

---

### Failure Point 2.2: BigQuery Load Fails

**Scenario:** Phase 2 can't write to BigQuery (quota, schema mismatch, permissions)

**Detection:**
- Phase 2 logs error
- processor_run_history shows status='failed'
- Alert triggered

**Self-Healing:** 🟡 Auto-Retry (depends on cause)
- Schema mismatch: 🔴 Manual (fix schema)
- Quota exceeded: 🟢 Auto-Heal (quota resets daily)
- Temporary error: 🟡 Auto-Retry (Pub/Sub redelivery)

**Manual Recovery:**

**If schema mismatch:**
```bash
# Check error
gcloud run services logs read nba-phase2-raw-processors --limit=50

# Update BigQuery schema
bq update nba-props-platform:nba_raw.bdl_games schema.json

# Clear failed run from processor_run_history (so deduplication allows retry)
bq query "DELETE FROM nba_reference.processor_run_history
  WHERE processor_name = 'BdlGamesProcessor'
    AND data_date = '2025-01-15'
    AND status = 'failed'"

# Retry by re-triggering scraper
curl -X POST https://nba-phase1-scrapers.../scrape \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'
```

**If quota exceeded:**
```bash
# Check quota usage
gcloud compute project-info describe --project=nba-props-platform

# Wait for quota reset (midnight PT)
# Or request quota increase

# Retry after quota available
```

**Prevention:**
- Schema evolution strategy (add columns, don't remove)
- Monitor BigQuery quota usage
- Add quota headroom alerts (>80% used)
- Test schema changes in test dataset first

---

### Failure Point 2.3: Change Detection Query Fails

**Scenario:** Hash comparison query times out or fails

**Detection:**
- Phase 2 logs error in change detection
- Falls back to full batch processing
- processor_run_history shows warning

**Self-Healing:** 🟢 Auto-Heal
- Change detection is optional optimization
- Falls back to processing all entities
- Slower but still works

**Manual Recovery:**
- No action needed, system continues
- Investigate query performance issue

**Prevention:**
- Optimize change detection queries
- Add query timeout limits
- Cache previous hashes in memory
- Add query performance monitoring

---

### Failure Point 2.4: Deduplication False Positive

**Scenario:** Deduplication skips processing when it shouldn't

**Detection:**
- Data not updated even though scraper ran
- processor_run_history shows skipped status
- User reports stale data

**Self-Healing:** 🔴 Manual
- Need to clear processor_run_history and re-run

**Manual Recovery:**
```bash
# Check if processor skipped
bq query "SELECT * FROM nba_reference.processor_run_history
  WHERE processor_name = 'BdlGamesProcessor'
    AND data_date = '2025-01-15'
  ORDER BY processed_at DESC LIMIT 1"

# If skipped incorrectly, delete the record
bq query "DELETE FROM nba_reference.processor_run_history
  WHERE processor_name = 'BdlGamesProcessor'
    AND data_date = '2025-01-15'
    AND status = 'success'"

# Re-trigger
curl -X POST https://nba-phase1-scrapers.../scrape \
  -d '{"scraper": "bdl_games", "game_date": "2025-01-15"}'
```

**Prevention:**
- Add force_reprocess flag to override deduplication
- Log clear reason for skipping
- Alert if multiple skips in a row
- Add /reprocess endpoint to force reprocessing

---

## Phase 2→3 Orchestrator

### Failure Point 3.1: Firestore Write Fails

**Scenario:** Orchestrator can't update completion state in Firestore

**Detection:**
- Cloud Function logs error
- Orchestrator state incomplete
- Phase 3 never triggers

**Self-Healing:** 🟡 Auto-Retry
- Pub/Sub redelivers message
- Orchestrator retries Firestore write
- May succeed on retry

**Manual Recovery:**
```bash
# Check Firestore state
# View in Firebase Console: firebase.google.com/project/nba-props-platform

# Check which processors completed
# If some missing, manually update Firestore or re-trigger Phase 2

# Option 1: Manually trigger Phase 3 (bypass orchestrator)
curl -X POST https://nba-phase3-analytics-processors.../process \
  -d '{"analysis_date": "2025-01-15", "source": "manual_recovery"}'

# Option 2: Delete Firestore state and re-trigger Phase 2
# This will cause orchestrator to reprocess
```

**Prevention:**
- Firestore transactions for atomic updates
- Retry logic with exponential backoff
- Monitor Firestore quota and latency
- Add Firestore connection pooling

---

### Failure Point 3.2: Orchestrator Cloud Function Crashes

**Scenario:** Cloud Function instance dies mid-processing

**Detection:**
- Cloud Function logs show crash
- No Phase 3 trigger even though all Phase 2 complete
- Firestore state shows partial completion

**Self-Healing:** 🟡 Auto-Retry
- Pub/Sub redelivers message to new function instance
- Firestore state persists across instances
- May complete on retry

**Manual Recovery:**
```bash
# Check Cloud Function logs
gcloud functions logs read phase2-to-phase3-orchestrator --limit=50

# Check Firestore state
# View completion status for game_date

# If stuck, manually trigger Phase 3
curl -X POST https://nba-phase3-analytics-processors.../process \
  -d '{"analysis_date": "2025-01-15"}'

# Clean up Firestore state for that date
# Delete document: phase2_completion/{game_date}
```

**Prevention:**
- Idempotent orchestrator logic
- State stored in Firestore (persists across crashes)
- Monitor function error rate
- Set appropriate timeout (5 minutes max)

---

### Failure Point 3.3: Orchestrator Gets Duplicate Messages

**Scenario:** Same Phase 2 processor sends completion event twice

**Detection:**
- Orchestrator logs "Already marked complete"
- No negative impact (idempotent)

**Self-Healing:** 🟢 Auto-Heal
- Orchestrator checks if processor already marked complete
- Ignores duplicate
- ACKs message

**Manual Recovery:**
- No action needed

**Prevention:**
- Idempotent orchestrator logic (already implemented)
- Log duplicates for monitoring
- Investigate why duplicates occurring

---

### Failure Point 3.4: Orchestrator Partial State (Missing Processors)

**Scenario:** Some Phase 2 processors never report completion

**Detection:**
- Timeout: If 2 hours pass and not all 21 processors complete
- Manual check: Firestore shows 18/21 processors complete
- Phase 3 never triggers

**Self-Healing:** 🔴 Manual
- Orchestrator waits indefinitely
- Need to identify missing processors and re-run

**Manual Recovery:**
```bash
# Check Firestore state to see which processors completed
# Firebase Console: phase2_completion/{game_date}

# Identify missing processors
# Check processor_run_history for those processors
bq query "SELECT processor_name, status FROM nba_reference.processor_run_history
  WHERE data_date = '2025-01-15' AND phase = 'phase_2_raw'
  ORDER BY processor_name"

# Re-run missing processors
for processor in <missing_list>; do
  curl -X POST https://nba-phase2-raw-processors.../process \
    -d "{\"processor\": \"$processor\", \"game_date\": \"2025-01-15\"}"
done

# Or manually trigger Phase 3 if acceptable to proceed with partial data
curl -X POST https://nba-phase3-analytics-processors.../process \
  -d '{"analysis_date": "2025-01-15", "allow_partial": true}'
```

**Prevention:**
- Add orchestrator timeout (2 hours)
- After timeout, alert with list of missing processors
- Add "proceed with partial" option
- Monitor completion rate (alert if <95%)

---

## Phase 3: Analytics

### Failure Point 4.1: Dependency Check Fails (Missing Upstream Data)

**Scenario:** Phase 3 processor starts but upstream Phase 2 data missing

**Detection:**
- Dependency check query returns 0 rows
- Processor logs "Dependency not met: bdl_player_boxscores"
- Status='failed' with reason

**Self-Healing:** 🟡 Auto-Retry
- Pub/Sub redelivery will retry after upstream completes
- If upstream truly missing, will fail again

**Manual Recovery:**
```bash
# Check which dependency missing
gcloud run services logs read nba-phase3-analytics-processors --limit=50

# Check if upstream data actually exists
bq query "SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores
  WHERE game_date = '2025-01-15'"

# If missing, run Phase 2 processor for that table
curl -X POST https://nba-phase2-raw-processors.../process \
  -d '{"scraper": "bdl_player_boxscores", "game_date": "2025-01-15"}'

# If data exists but query issue, check dependency query logic
# May need to adjust dependency age threshold
```

**Prevention:**
- Dependency checks with reasonable age thresholds (24 hours)
- Log exactly which dependencies missing
- Alert if dependency failures > 3 in a row
- Add /check-dependencies endpoint for testing

---

### Failure Point 4.2: BigQuery Analytics Query Timeout

**Scenario:** Complex analytics query times out (>10 minutes)

**Detection:**
- BigQuery job shows timeout error
- Processor logs "Query timeout"
- Status='failed'

**Self-Healing:** 🔴 Manual
- Query may be inefficient
- Need to optimize or increase timeout

**Manual Recovery:**
```bash
# Check query performance in BigQuery Console
# Identify slow query

# Option 1: Optimize query
# - Add partitioning filter
# - Reduce date range
# - Optimize JOIN order

# Option 2: Increase timeout (if query is legitimately long)
# Update processor timeout in Cloud Run

# Option 3: Break into smaller queries
# Process date ranges in chunks
```

**Prevention:**
- Partition tables by game_date
- Add query timeout monitoring
- Optimize queries before deployment
- Test queries with full dataset in test environment
- Add query cost estimation

---

### Failure Point 4.3: Change Detection Identifies Wrong Entities

**Scenario:** Hash comparison says entity changed when it didn't

**Detection:**
- Unnecessary reprocessing of unchanged entities
- Higher than expected processing time
- Logs show "Processing 100 changed entities" when only 1 actually changed

**Self-Healing:** 🟢 Auto-Heal (but inefficient)
- System still works, just processes more than needed
- No data corruption

**Manual Recovery:**
- Investigate hash computation logic
- Check for non-deterministic fields (timestamps, etc.)

**Prevention:**
- Exclude non-deterministic fields from hash (timestamps, run_id)
- Sort arrays before hashing
- Normalize floating point numbers
- Test hash stability

---

## Phase 3→4 Orchestrator

### Failure Point 5.1: Changed Entities Aggregation Error

**Scenario:** Orchestrator fails to merge entities_changed lists from 5 Phase 3 processors

**Detection:**
- Orchestrator logs error
- Phase 4 receives empty or incomplete entities_changed list
- More entities processed than should be

**Self-Healing:** 🟢 Auto-Heal (falls back to full batch)
- If aggregation fails, publishes is_full_batch=true
- Phase 4 processes all entities
- Less efficient but safe

**Manual Recovery:**
- No action needed if falling back to full batch
- Investigate aggregation logic for future runs

**Prevention:**
- Defensive aggregation (deduplicate, handle nulls)
- Fall back to full batch on error
- Log aggregation results
- Monitor changed entity counts

---

### Failure Point 5.2: Phase 4 Triggered Before All Phase 3 Complete

**Scenario:** Bug in orchestrator triggers Phase 4 prematurely

**Detection:**
- Phase 4 dependency checks fail
- Phase 4 processes with incomplete Phase 3 data
- Data quality issues

**Self-Healing:** 🔴 Manual
- Partial data already processed
- Need to reprocess with complete data

**Manual Recovery:**
```bash
# Check Firestore state - how many Phase 3 processors completed?
# Firebase Console: phase3_completion/{analysis_date}

# If only 3/5, identify missing:
bq query "SELECT processor_name, status FROM nba_reference.processor_run_history
  WHERE data_date = '2025-01-15' AND phase = 'phase_3_analytics'
  ORDER BY processor_name"

# Re-run missing Phase 3 processors
# Then re-run Phase 4 with force_reprocess=true
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15", "force_reprocess": true}'
```

**Prevention:**
- Robust orchestrator completion logic
- Require EXACTLY 5 processors complete (not >=5)
- Add assertions in orchestrator
- Integration test with partial completions

---

## Phase 4: Precompute

### Failure Point 6.1: Level 1 Processor Fails but Level 2 Starts

**Scenario:** Phase 4 internal orchestrator bug allows Level 2 to start before Level 1 completes

**Detection:**
- Level 2 processor fails dependency check
- Logs show "team_defense_zone data missing"
- Data corruption if dependency check bypassed

**Self-Healing:** 🟡 Auto-Retry (if dependency check works)
- Level 2 fails dependency check
- Status='failed'
- Pub/Sub redelivery after Level 1 completes

**Manual Recovery:**
```bash
# Check which Level 1 processors failed
bq query "SELECT processor_name, status
  FROM nba_reference.processor_run_history
  WHERE data_date = '2025-01-15'
    AND processor_name IN ('TeamDefenseZoneProcessor', 'PlayerShotZoneProcessor', 'PlayerDailyCacheProcessor')
  ORDER BY processor_name"

# Re-run failed Level 1 processors
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15", "processors": ["TeamDefenseZoneProcessor"]}'

# Then re-run Level 2 and Level 3
```

**Prevention:**
- Strict dependency enforcement in orchestrator
- Level 2 only triggered when ALL Level 1 complete
- Add assertions: "ALL Level 1 must be complete"
- Integration tests for multi-level orchestration

---

### Failure Point 6.2: ml_feature_store_v2 Fails Partway Through

**Scenario:** ml_feature_store_v2 processes 200/450 players then crashes

**Detection:**
- Processor logs error at player 200
- processor_run_history shows status='partial'
- ml_feature_store_v2 table has only 200 rows for that date

**Self-Healing:** 🔴 Manual (depends on implementation)
- Need idempotent processing or checkpointing
- May need to delete partial data and rerun

**Manual Recovery:**
```bash
# Check row count
bq query "SELECT COUNT(*) FROM nba_precompute.ml_feature_store_v2
  WHERE game_date = '2025-01-15'"

# Option 1: If idempotent, just re-run (will update existing rows)
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15", "processors": ["MLFeatureStoreProcessor"]}'

# Option 2: If not idempotent, delete partial data first
bq query "DELETE FROM nba_precompute.ml_feature_store_v2
  WHERE game_date = '2025-01-15'"

# Then re-run
```

**Prevention:**
- Use MERGE instead of INSERT (idempotent)
- Add checkpointing (save progress every 100 players)
- Process in smaller batches
- Add row count validation at end
- Alert if row count < expected

---

## Phase 4 Internal Orchestrator

### Failure Point 7.1: Firestore State Corrupted

**Scenario:** Firestore document in inconsistent state

**Detection:**
- Orchestrator logs error reading state
- Phase 4 processors stuck waiting
- Firestore shows malformed document

**Self-Healing:** 🔴 Manual
- Need to fix Firestore state manually

**Manual Recovery:**
```bash
# View Firestore state
# Firebase Console: phase4_completion/{analysis_date}

# Option 1: Delete corrupted document
# Firestore Console → Delete document

# Re-trigger Phase 4 from beginning
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15", "force_reprocess": true}'

# Option 2: Manually fix document structure
# Edit in Firestore Console
```

**Prevention:**
- Schema validation in orchestrator
- Defensive reads (handle malformed documents)
- Add Firestore backup/recovery
- Monitor Firestore document sizes

---

## Phase 5: Predictions

### Failure Point 8.1: /trigger Never Receives Message

**Scenario:** Phase 4 publishes completion but Phase 5 /trigger doesn't receive it

**Detection:**
- Phase 4 complete (processor_run_history shows success)
- Phase 5 never starts
- Monitoring shows no /trigger calls

**Self-Healing:** 🟡 Auto-Retry (via backup scheduler)
- Backup scheduler at 6:00 AM PT triggers /start
- /start checks Phase 4 ready and proceeds
- 30 minute delay but recovers automatically

**Manual Recovery:**
```bash
# Check if Phase 4 complete
bq query "SELECT * FROM nba_reference.processor_run_history
  WHERE processor_name = 'MLFeatureStoreProcessor'
    AND data_date = '2025-01-15'
  ORDER BY processed_at DESC LIMIT 1"

# Manually trigger Phase 5
curl -X POST https://prediction-coordinator.../trigger \
  -d '{"game_date": "2025-01-15"}'

# Or use /start endpoint
curl -X POST https://prediction-coordinator.../start \
  -d '{"game_date": "2025-01-15"}'
```

**Prevention:**
- Backup scheduler (already planned)
- Monitor Pub/Sub subscription lag
- Alert if no /trigger call within 1 hour of Phase 4 completion
- DLQ for failed message delivery

---

### Failure Point 8.2: Phase 4 Validation Fails (Not Enough Data)

**Scenario:** /trigger receives message but Phase 4 has <80% player coverage

**Detection:**
- /trigger runs validation
- Logs "Phase 4 not ready: 350/450 players (77%)"
- Returns error, doesn't start predictions

**Self-Healing:** 🟡 Auto-Retry (via retry schedulers)
- Retry schedulers at 6:15 AM, 6:30 AM
- By then, Phase 4 may have more data
- Backup scheduler at 6:00 AM also retries

**Manual Recovery:**
```bash
# Check Phase 4 coverage
bq query "SELECT COUNT(DISTINCT player_lookup)
  FROM nba_precompute.ml_feature_store_v2
  WHERE game_date = '2025-01-15'"

# If truly insufficient, investigate Phase 4
# Check which players missing

# If acceptable coverage (>100 players), override threshold
curl -X POST https://prediction-coordinator.../start \
  -d '{"game_date": "2025-01-15", "min_players": 100}'
```

**Prevention:**
- Alert if Phase 4 coverage <90% at 5:00 AM
- Investigate Phase 4 failures early
- Add /status endpoint showing coverage
- Configurable threshold per environment

---

### Failure Point 8.3: Some Workers Succeed, Some Fail (Partial Batch)

**Scenario:** 400/450 workers succeed, 50 fail

**Detection:**
- Coordinator tracks completion: 400/450
- After timeout, considers batch "partial"
- processor_run_history shows status='partial'

**Self-Healing:** 🟡 Auto-Retry (via retry endpoints)
- Retry schedulers at 6:15 AM, 6:30 AM
- /retry endpoint processes only failed players
- Gradually fills in missing predictions

**Manual Recovery:**
```bash
# Check completion status
curl https://prediction-coordinator.../status?batch_id=<batch_id>

# Get list of failed players
# From coordinator state or prediction_worker_runs table

# Option 1: Use /retry endpoint
curl -X POST https://prediction-coordinator.../retry \
  -d '{"game_date": "2025-01-15"}'

# Option 2: Manually trigger workers for specific players
for player in <failed_list>; do
  gcloud pubsub topics publish prediction-request-prod \
    --message="{\"player_lookup\": \"$player\", \"game_date\": \"2025-01-15\"}"
done
```

**Prevention:**
- Robust worker error handling
- Worker retries on transient errors
- Coordinator timeout (30 minutes)
- Automatic retry schedulers
- Alert if completion <95%

---

### Failure Point 8.4: Coordinator State Corrupted

**Scenario:** In-memory coordinator state lost (instance restart)

**Detection:**
- Coordinator logs show restart
- No batch tracking info
- Workers complete but coordinator doesn't know

**Self-Healing:** 🔴 Manual (for v1.0)
- v1.0 uses in-memory state (lost on restart)
- v1.1 will use Firestore for persistence

**Manual Recovery:**
```bash
# Check prediction table for completeness
bq query "SELECT COUNT(DISTINCT player_lookup)
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '2025-01-15'"

# If incomplete, check which players missing
# Re-run coordinator /start (will republish all, deduplication in workers)
curl -X POST https://prediction-coordinator.../start \
  -d '{"game_date": "2025-01-15", "force": true}'
```

**Prevention:**
- v1.1: Use Firestore for coordinator state
- Add health check that rebuilds state from BigQuery
- Monitor coordinator uptime
- Alert on coordinator restarts

---

## Cross-Cutting Failures

### Failure Point 9.1: Pub/Sub Message Too Large

**Scenario:** Message exceeds 10MB limit (e.g., entities_changed list with 10,000 players)

**Detection:**
- Pub/Sub publish fails with "Message too large" error
- Processor logs error

**Self-Healing:** 🔴 Manual
- Need to redesign message or split

**Manual Recovery:**
```bash
# Identify large message
# Check processor logs

# Option 1: Split into multiple messages
# Option 2: Use GCS for large data, send GCS path in message
# Option 3: Fall back to full batch (entities_changed = null)

# For immediate recovery, bypass Pub/Sub
curl -X POST https://next-phase-url.../process \
  -d '{"game_date": "2025-01-15", "is_full_batch": true}'
```

**Prevention:**
- Limit entities_changed list size
- If >1000 entities, send is_full_batch=true instead
- Monitor message sizes
- Test with large entity lists

---

### Failure Point 9.2: Correlation ID Lost

**Scenario:** Correlation ID not propagated through a phase

**Detection:**
- Can't trace prediction back to scraper
- Correlation ID is null in downstream phases

**Self-Healing:** 🟢 Auto-Heal (for future runs)
- Fix bug in processor that lost it
- Previous runs lost tracking (acceptable)

**Manual Recovery:**
- No recovery needed
- Fix code for future runs

**Prevention:**
- Unit tests verify correlation_id propagation
- Log correlation_id at every phase
- Monitor correlation_id presence
- Alert if correlation_id null > 5%

---

### Failure Point 9.3: BigQuery Quota Exceeded

**Scenario:** Hit daily query quota limit

**Detection:**
- BigQuery returns "Quota exceeded" error
- All BigQuery operations fail
- Alert triggered

**Self-Healing:** 🟢 Auto-Heal (at midnight PT)
- Quota resets daily
- System recovers automatically next day

**Manual Recovery:**
```bash
# Check quota usage
gcloud compute project-info describe --project=nba-props-platform

# Option 1: Request quota increase (if needed long-term)
# GCP Console → IAM & Admin → Quotas

# Option 2: Wait for quota reset (midnight PT)

# Option 3: Optimize queries to reduce usage
```

**Prevention:**
- Monitor quota usage daily
- Alert at 80% used
- Request higher quota proactively
- Cache query results when possible
- Optimize queries (partition pruning, etc.)

---

### Failure Point 9.4: Cloud Run Memory Limit Exceeded

**Scenario:** Processor runs out of memory (OOM killed)

**Detection:**
- Cloud Run logs show "Container killed: out of memory"
- Processor crashes mid-run
- Status='failed'

**Self-Healing:** 🟡 Auto-Retry
- Pub/Sub redelivery
- If issue is persistent, will fail again

**Manual Recovery:**
```bash
# Check Cloud Run logs for OOM
gcloud run services logs read SERVICE_NAME --limit=50

# Increase memory allocation
gcloud run services update SERVICE_NAME --memory=4Gi

# Retry
curl -X POST https://SERVICE_URL.../process \
  -d '{"game_date": "2025-01-15"}'
```

**Prevention:**
- Load test with production data volumes
- Set appropriate memory limits (start with 2GB)
- Use streaming/batching for large datasets
- Monitor memory usage
- Alert if memory >90%

---

### Failure Point 9.5: Network Partition / GCP Region Outage

**Scenario:** us-west2 region unavailable

**Detection:**
- All services return 503
- GCP status page shows outage
- Widespread alerts

**Self-Healing:** 🟢 Auto-Heal (when region recovers)
- Services automatically recover
- Pub/Sub messages queued during outage
- Processing resumes when region up

**Manual Recovery:**
```bash
# Check GCP status
# https://status.cloud.google.com

# If extended outage, consider:
# 1. Wait for recovery (messages queued)
# 2. Deploy to secondary region (if configured)
# 3. Manual processing after recovery

# After recovery, verify:
# - All Pub/Sub messages processed
# - No data loss
# - Pipeline caught up
```

**Prevention:**
- Multi-region deployment (future)
- GCS replication to multiple regions
- Pub/Sub automatic retry
- Monitor GCP status
- Have disaster recovery plan documented

---

## Recovery Procedures

### Procedure 1: Full Pipeline Reprocess for a Date

**When:** Data corruption, missed processing, manual fix needed

**Steps:**
```bash
# 1. Clear all processor_run_history for that date
bq query "DELETE FROM nba_reference.processor_run_history
  WHERE data_date = '2025-01-15'"

# 2. Clear all Firestore orchestrator state for that date
# Firebase Console → Delete documents:
#   - phase2_completion/2025-01-15
#   - phase3_completion/2025-01-15
#   - phase4_completion/2025-01-15

# 3. Re-trigger Phase 1 (will cascade through entire pipeline)
for scraper in bdl_games nbac_player_boxscore ...; do
  curl -X POST https://nba-phase1-scrapers.../scrape \
    -d "{\"scraper\": \"$scraper\", \"game_date\": \"2025-01-15\"}"
done

# 4. Monitor progress
watch -n 60 'bq query "SELECT phase, COUNT(*) as count
  FROM nba_reference.processor_run_history
  WHERE data_date = \"2025-01-15\"
  GROUP BY phase"'
```

---

### Procedure 2: Restart from Specific Phase

**When:** Only downstream phases need reprocessing

**Steps:**
```bash
# Example: Restart from Phase 4

# 1. Clear processor_run_history for Phase 4 and Phase 5
bq query "DELETE FROM nba_reference.processor_run_history
  WHERE data_date = '2025-01-15'
    AND phase IN ('phase_4_precompute', 'phase_5_predictions')"

# 2. Clear Firestore state for Phase 4
# Firebase Console → Delete: phase4_completion/2025-01-15

# 3. Delete output data (optional, if MERGE doesn't work)
bq query "DELETE FROM nba_precompute.ml_feature_store_v2
  WHERE game_date = '2025-01-15'"
bq query "DELETE FROM nba_predictions.player_prop_predictions
  WHERE game_date = '2025-01-15'"

# 4. Manually trigger Phase 4
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15"}'

# Phase 4→5 will cascade automatically
```

---

### Procedure 3: Check Pipeline Health for a Date

**When:** Verification, debugging, daily checks

**Steps:**
```bash
# 1. Check all phases completed
bq query "
SELECT
  phase,
  COUNT(*) as processors_run,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
  SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) as partial
FROM nba_reference.processor_run_history
WHERE data_date = '2025-01-15'
GROUP BY phase
ORDER BY phase
"

# 2. Check data volumes
bq query "
SELECT
  'Phase 2: Games' as metric,
  COUNT(*) as count
FROM nba_raw.bdl_games
WHERE game_date = '2025-01-15'

UNION ALL

SELECT
  'Phase 3: Player Summary',
  COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date = '2025-01-15'

UNION ALL

SELECT
  'Phase 4: ML Features',
  COUNT(DISTINCT player_lookup)
FROM nba_precompute.ml_feature_store_v2
WHERE game_date = '2025-01-15'

UNION ALL

SELECT
  'Phase 5: Predictions',
  COUNT(DISTINCT player_lookup)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-01-15'
"

# 3. Check orchestrator state
# Firebase Console:
#   - phase2_completion/2025-01-15 (should show all 21 processors)
#   - phase3_completion/2025-01-15 (should show all 5 processors)
#   - phase4_completion/2025-01-15 (should show all 5 processors)

# 4. Check for errors
gcloud run services logs read nba-phase3-analytics-processors \
  --filter="severity=ERROR AND timestamp>=\"2025-01-15T00:00:00Z\"" \
  --limit=50
```

---

### Procedure 4: Emergency: Bypass Orchestrator

**When:** Orchestrator stuck, need to proceed urgently

**Steps:**
```bash
# Bypass Phase 2→3 orchestrator
curl -X POST https://nba-phase3-analytics-processors.../process \
  -d '{"analysis_date": "2025-01-15", "bypass_orchestrator": true}'

# Bypass Phase 3→4 orchestrator
curl -X POST https://nba-phase4-precompute-processors.../process-date \
  -d '{"analysis_date": "2025-01-15", "bypass_orchestrator": true}'

# Bypass Phase 4→5 Pub/Sub
curl -X POST https://prediction-coordinator.../start \
  -d '{"game_date": "2025-01-15", "force": true}'
```

---

## Prevention Strategies

### Strategy 1: Comprehensive Monitoring

**What to Monitor:**

1. **Pipeline Health Dashboard**
   - Phase completion rates (daily)
   - End-to-end latency (Phase 1 → Phase 5)
   - Error rates by phase
   - Data volumes by phase

2. **Orchestrator Health**
   - Firestore write latency
   - Orchestrator execution time
   - Stuck orchestrators (>2 hours)

3. **Resource Usage**
   - BigQuery quota (alert at 80%)
   - Pub/Sub quota
   - Cloud Run memory usage
   - Firestore quota

4. **Data Quality**
   - Expected vs actual row counts
   - Data freshness (hours since last update)
   - Prediction coverage (% of expected players)

**Implementation:**
```bash
# Create monitoring dashboard
# Cloud Monitoring → Dashboards → Create

# Add widgets for:
# - Pipeline completion chart
# - Error rate by phase
# - Latency metrics
# - Resource usage
```

---

### Strategy 2: Proactive Alerting

**Alert Tiers:**

**Critical (Immediate - Slack + Email):**
- Any phase 100% failure
- Phase 5 predictions <90% coverage
- End-to-end latency >4 hours
- GCP quota exceeded

**Warning (Same Day - Slack Only):**
- Any phase >10% failure rate
- Orchestrator stuck >2 hours
- Resource usage >80%
- Data quality issues

**Info (Daily Summary - Slack Only):**
- Successful daily run
- Performance metrics
- Coverage statistics

**Implementation:**
```python
# In AlertManager
ALERT_CONFIG = {
    'critical': {
        'channels': ['slack', 'email'],
        'conditions': [
            'phase_failure_rate > 1.0',
            'prediction_coverage < 0.90',
            'pipeline_latency > 14400',  # 4 hours
        ]
    },
    'warning': {
        'channels': ['slack'],
        'conditions': [
            'phase_failure_rate > 0.10',
            'orchestrator_stuck > 7200',  # 2 hours
            'resource_usage > 0.80',
        ]
    }
}
```

---

### Strategy 3: Testing in Production

**Canary Testing:**
- Test with single game date before full rollout
- Monitor for errors
- Rollback if issues

**Chaos Engineering:**
- Randomly kill processors (test recovery)
- Simulate Firestore failures
- Test with malformed messages
- Verify self-healing works

**Load Testing:**
- Test with 100,000 players (future growth)
- Test concurrent processing
- Verify resource scaling

---

### Strategy 4: Runbook Automation

**Automate Common Procedures:**

1. **Auto-Retry Failed Processors**
   ```python
   # Cloud Function: auto_retry_failed_processors
   # Runs hourly, checks processor_run_history
   # Retries any failed processors from last 24 hours
   ```

2. **Auto-Clean Stuck Orchestrators**
   ```python
   # Cloud Function: clean_stuck_orchestrators
   # Runs every 4 hours
   # Deletes Firestore state >8 hours old with incomplete processors
   # Alerts on cleanup
   ```

3. **Auto-DLQ Processing**
   ```python
   # Cloud Function: process_dlq_messages
   # Runs every hour
   # Pulls messages from DLQ
   # Investigates common issues
   # Auto-retries if possible, alerts if manual intervention needed
   ```

---

## Summary: Self-Healing Capabilities

### 🟢 Fully Automatic (No Manual Intervention)

1. Scraper transient failures → Scheduler retries
2. Pub/Sub transient failures → Automatic redelivery
3. BigQuery quota exceeded → Resets daily
4. Orchestrator crashes → Pub/Sub redelivery, Firestore state persists
5. Cloud Run crashes → Automatic restart
6. Change detection failures → Falls back to full batch
7. Duplicate messages → Idempotent processing ignores
8. GCP outages → Queued messages process when recovered

### 🟡 Semi-Automatic (Retries, May Need Monitoring)

1. Worker failures → Coordinator retries
2. Phase 5 /trigger fails → Backup scheduler
3. Dependency check fails → Pub/Sub retries after upstream completes
4. Firestore write fails → Pub/Sub retries with backoff
5. BigQuery query timeout → May succeed on retry

### 🔴 Manual Intervention Required

1. Schema mismatches → Fix schema, reprocess
2. Data quality issues → Fix source, reprocess
3. Deduplication false positives → Clear history, reprocess
4. Orchestrator stuck (missing processors) → Investigate, re-run missing
5. Partial batch (Phase 5 <90%) → Check failures, retry
6. Firestore state corrupted → Manually fix or delete
7. Pub/Sub message too large → Redesign message
8. Memory limits exceeded → Increase limits

---

**Document Status:** ✅ Complete Failure Analysis
**Next Action:** Review and validate against implementation plan
**Maintenance:** Update as new failure modes discovered in production
