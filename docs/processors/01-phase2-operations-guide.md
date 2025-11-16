# Phase 2 Operations Guide

**File:** `docs/processors/01-phase2-operations-guide.md`
**Created:** 2025-11-14 23:43 PST
**Last Updated:** 2025-11-15 (moved from orchestration/ to processors/)
**Last Verified:** 2025-11-15 (1,482 events in 3 hours, 100% delivery rate)
**Status:** ✅ DEPLOYED & OPERATIONAL
**Purpose:** Operational guide for Phase 2 raw data processing system
**Audience:** Engineers operating and troubleshooting Phase 2 processors

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Known Limitations](#known-limitations)
3. [System Architecture](#system-architecture)
4. [Processor Specifications](#processor-specifications)
5. [Monitoring & Health Checks](#monitoring--health-checks)
6. [Manual Operations](#manual-operations)
7. [Troubleshooting](#troubleshooting)
8. [Next Steps](#next-steps)

---

## Executive Summary

### What Phase 2 Does

**Mission:** Transform scraped NBA data from GCS into structured BigQuery tables.

**Current Status:**
- ✅ **Deployed:** November 13, 2025 (revision 00073)
- ✅ **Verified:** November 15, 2025 (100% message delivery, 1,482 events)
- ✅ **Event-driven:** Pub/Sub integration working end-to-end
- ✅ **Processing:** 21 processors operational, loading to BigQuery

**Key Metrics:**
- **Processing Scale:** 100-200 GCS files/day
- **Success Rate:** 95%+ target
- **Processing Latency:** <30 seconds (GCS write → BigQuery)
- **Data Quality:** 99.2% quality rate, 98.92% player name resolution

### Data Flow (Currently Working)

```
Phase 1 Scrapers (✅ OPERATIONAL)
  ↓ Writes JSON to GCS
  ↓ Publishes Pub/Sub event
Phase 2 Processors (✅ OPERATIONAL)
  ↓ Receives event
  ↓ Reads GCS file
  ↓ Transforms data
  ↓ Loads to BigQuery nba_raw.*
Phase 3 Analytics (⚠️ MANUAL TRIGGER ONLY)
```

**Total Latency:** ~18 seconds (scraper completion → BigQuery loaded)

---

## ⚠️ Known Limitations

### Phase 2→3 Event Publishing: NOT IMPLEMENTED

**What Works:**
- ✅ Phase 1 scrapers → Pub/Sub → Phase 2 processors (OPERATIONAL)
- ✅ Phase 2 processors load data to BigQuery nba_raw.* tables
- ✅ Event-driven triggering from Phase 1
- ✅ Message normalization for backward compatibility

**What's Missing:**
- ❌ Phase 2 processors **DO NOT** publish completion events
- ❌ Phase 3 analytics processors **DO NOT** trigger automatically
- ❌ No event-driven connection between Phase 2 and Phase 3

### Current Workaround

**Manual Triggering:** Phase 3 analytics processors must be triggered:
- Manually via HTTP POST
- Via Cloud Scheduler (time-based)
- Via manual scripts

### Integration Timeline

**Sprint 1:** Phase 2→3 Pub/Sub Connection (~2 hours effort)
- Create `RawDataPubSubPublisher` class
- Add publishing to Phase 2 processor base class
- Create Pub/Sub topic: `nba-raw-data-complete`
- Create subscription pointing to analytics service
- Test end-to-end flow

**Reference:** See `docs/architecture/implementation-status-and-roadmap.md` for complete plan.

**Related:** See `docs/architecture/event-driven-pipeline-architecture.md` for full vision.

---

## System Architecture

### High-Level Flow

```
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: Scrapers (Cloud Run)                    ✅ WORKING  │
│ • 26+ scrapers operational                                    │
│ • Writes JSON to GCS                                          │
│ • Publishes to nba-scraper-complete topic                    │
└──────────────────────────────────────────────────────────────┘
                           ↓ Pub/Sub event
┌──────────────────────────────────────────────────────────────┐
│ Pub/Sub: nba-scraper-complete                    ✅ WORKING  │
│ • Message retention: 1 day                                    │
│ • DLQ: nba-scraper-complete-dlq (7 days)                     │
└──────────────────────────────────────────────────────────────┘
                           ↓ Push subscription
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: Processors (Cloud Run)                  ✅ WORKING  │
│ • 21 processors operational                                   │
│ • Normalizes message format                                   │
│ • Loads to BigQuery nba_raw.*                                │
│ • ⚠️ Does NOT publish to Phase 3                             │
└──────────────────────────────────────────────────────────────┘
                           ↓ BigQuery writes
┌──────────────────────────────────────────────────────────────┐
│ BigQuery: nba_raw dataset                         ✅ WORKING  │
│ • 21 tables with partitioning/clustering                     │
│ • Metadata tracking (source_file_path, processed_at)        │
└──────────────────────────────────────────────────────────────┘
```

### Pub/Sub Configuration

**Topic:** `nba-scraper-complete`
- **Purpose:** Phase 1 scrapers publish completion events
- **Retention:** 1 day
- **Status:** ✅ Configured

**Subscription:** `nba-processors-sub`
- **Type:** Push subscription
- **Endpoint:** `https://nba-processors-XXX.run.app/process`
- **ACK Deadline:** 600s (10 minutes)
- **Max Delivery Attempts:** 5
- **DLQ:** `nba-scraper-complete-dlq`
- **Status:** ✅ Configured

**IAM:**
- ✅ Scraper service account: `roles/pubsub.publisher`
- ✅ Processor service account: `roles/pubsub.subscriber`, `roles/run.invoker`

### Message Format

Phase 2 processors handle both formats automatically:

**Format 1 - Scraper Completion (v1.0):**
```json
{
  "scraper_name": "bdl_boxscores",
  "execution_id": "2025-11-13T08:00:00_bdl_boxscores",
  "status": "success",
  "gcs_path": "gs://nba-scraped-data/.../file.json",
  "record_count": 150,
  "duration_seconds": 28.5,
  "timestamp": "2025-11-13T16:00:45Z",
  "workflow": "morning_operations"
}
```

**Format 2 - GCS Object Finalize (legacy):**
```json
{
  "bucket": "nba-scraped-data",
  "name": "ball-dont-lie/boxscores/2025-11-13/file.json",
  "timeCreated": "2025-11-13T16:00:45Z"
}
```

**Normalization:** Processor service automatically converts scraper format → GCS format for backward compatibility.

**Reference:** See `docs/specifications/pubsub-message-formats.md` for complete spec.

---

## Processor Specifications

### Overview

- **Total Processors:** 21
- **Deployment:** One Cloud Run service per processor
- **Trigger:** Pub/Sub push subscriptions (event-driven)
- **Dataset:** BigQuery `nba_raw.*`

### Processing Groups

#### Group 1: Morning Operations (6 processors)
**Purpose:** Daily foundation data
**Timing:** 5-7 AM ET
**Execution:** All parallel (no dependencies)

| Processor | Table | Duration | Memory |
|-----------|-------|----------|--------|
| NbacScheduleProcessor | nbac_schedule | ~27s | 4Gi |
| BasketballRefRosterProcessor | br_rosters_current | ~2min | 2Gi |
| BdlStandingsProcessor | bdl_standings | ~50s | 2Gi |
| EspnTeamRosterProcessor | espn_team_rosters | 20-25s | 1Gi |
| NbacPlayerMovementProcessor | nbac_player_movement | ~21s | 2Gi |
| NbacRefereeProcessor | nbac_referee_game_assignments | ~2min | 2Gi |

**Critical:** BasketballRefRosterProcessor MUST complete before NbacGamebookProcessor for optimal name resolution (98.92% accuracy).

#### Group 2: Real-Time Monitoring (5 processors)
**Purpose:** Player availability and injury intelligence
**Timing:** Hourly or every 2 hours
**Execution:** Independent

| Processor | Table | Strategy | Frequency |
|-----------|-------|----------|-----------|
| NbacPlayerListProcessor | nbac_player_list_current | MERGE_UPDATE | Every 2h |
| BdlActivePlayersProcessor | bdl_active_players_current | MERGE_UPDATE | Every 2h |
| NbacInjuryReportProcessor | nbac_injury_report | APPEND_ALWAYS | Hourly |
| BdlInjuriesProcessor | bdl_injuries | APPEND_ALWAYS | Every 2h |

**Note:** NbacInjuryReportProcessor runs 24 times/day.

#### Group 3: Pre-Game Collection (3 processors)
**Purpose:** Betting lines before games
**Timing:** 2 hours before tipoff
**Execution:** Parallel

| Processor | Table | Duration | Records/Game |
|-----------|-------|----------|--------------|
| OddsApiPropsProcessor | odds_api_player_points_props | ~5min | 20-28 players |
| OddsGameLinesProcessor | odds_api_game_lines | ~5min | 8 records |
| BettingPropsProcessor | bettingpros_player_points_props | ~5min | 49+ bookmakers |

#### Group 4: Post-Game Collection (6 processors)
**Purpose:** Game results and statistics
**Timing:** Post-game (8 PM, 11 PM, 5 AM ET)
**Execution:** Parallel

| Processor | Table | Duration | Memory | Strategy |
|-----------|-------|----------|--------|----------|
| BdlBoxscoresProcessor | bdl_player_boxscores | 90-120min | 4Gi | MERGE_UPDATE |
| NbacTeamBoxscoreProcessor | nbac_team_boxscore | <5min/game | 4Gi | MERGE_UPDATE |
| NbacPlayerBoxscoreProcessor | nbac_player_boxscores | <5min/game | 4Gi | MERGE_UPDATE |
| NbacGamebookProcessor | nbac_gamebook_player_stats | 19-24s/game | 8Gi | MERGE_UPDATE |
| NbacPlayByPlayProcessor | nbac_play_by_play | 19-24s/game | 8Gi | MERGE_UPDATE |
| BigDataBallPbpProcessor | bigdataball_play_by_play | ~18min | 4Gi | MERGE_UPDATE |

**Execution Windows:**
- **8 PM ET:** Early attempt (50-70% success)
- **11 PM ET:** Late retry (90%+ success)
- **5 AM ET:** Final validation

#### Group 5: Backup Validation (2 processors)
**Purpose:** Final data completeness check
**Timing:** 5 AM ET
**Execution:** Only if primary sources failed

| Processor | Table | Duration | Purpose |
|-----------|-------|----------|---------|
| EspnScoreboardProcessor | espn_scoreboard | 40-50s | Score validation |
| EspnBoxscoreProcessor | espn_boxscores | 15-20s | Stats backup |

### Resource Allocation

**Light Processors (1Gi, 1 CPU, 5-min timeout):**
- NbacPlayerListProcessor, BdlActivePlayersProcessor
- EspnScoreboardProcessor, EspnBoxscoreProcessor, EspnTeamRosterProcessor

**Medium Processors (2Gi, 1 CPU, 10-min timeout):**
- BasketballRefRosterProcessor, NbacPlayerMovementProcessor
- NbacRefereeProcessor, BdlStandingsProcessor

**Heavy Processors (4Gi, 2 CPU, 1-hour timeout):**
- BdlBoxscoresProcessor, NbacTeamBoxscoreProcessor
- NbacPlayerBoxscoreProcessor, OddsApiPropsProcessor, BigDataBallPbpProcessor

**Very Heavy Processors (8Gi, 4 CPU, multi-hour timeout):**
- NbacGamebookProcessor (6-hour timeout)
- NbacPlayByPlayProcessor (30-min timeout)

---

## Monitoring & Health Checks

### Quick Health Check

```bash
# Complete system health check
./bin/orchestration/quick_health_check.sh

# Check Pub/Sub status
./bin/pubsub/monitor_pubsub.sh

# Check DLQ for failures
./bin/pubsub/check_dead_letter_queue.sh
```

### Pub/Sub Monitoring

**Check Subscription Backlog:**
```bash
# Real-time monitoring
./bin/pubsub/monitor_pubsub.sh --watch

# One-time check
gcloud pubsub subscriptions describe nba-processors-sub \
  --format="value(numUndeliveredMessages)"

# Expected: 0 (no backlog)
```

**Check Dead Letter Queue:**
```bash
# Check DLQ message count
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# Expected: 0 (no failures)

# Pull DLQ messages if any
gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub \
  --limit=10 \
  --format=json > dlq_messages.json
```

### BigQuery Data Verification

**Check Recent Processing:**
```sql
-- Verify data written today
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  MAX(processed_at) as last_processed,
  MIN(processed_at) as first_processed
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE('America/New_York');
```

**Check Processing Lag:**
```sql
-- Find processing delay
SELECT
  source_file_path,
  processed_at,
  TIMESTAMP_DIFF(processed_at,
    PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%S',
      REGEXP_EXTRACT(source_file_path, r'/(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})')),
    SECOND) as lag_seconds
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE('America/New_York')
ORDER BY processed_at DESC
LIMIT 10;

-- Expected: <30 seconds lag
```

### Processor Health

**Check Processor Service:**
```bash
# Get service status
gcloud run services describe nba-processors \
  --region=us-west2 \
  --project=nba-props-platform

# Check health endpoint
SERVICE_URL=$(gcloud run services describe nba-processors \
  --region=us-west2 --format="value(status.url)")

curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "${SERVICE_URL}/health"

# Expected: {"status": "healthy"}
```

**Check Recent Logs:**
```bash
# View recent processor logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-processors" \
  --limit=50 \
  --format=json

# Filter for errors
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-processors \
  AND severity>=ERROR" \
  --limit=20
```

### Key Metrics to Monitor

**Daily Health Check:**
- ✅ Pub/Sub backlog = 0
- ✅ DLQ message count = 0
- ✅ Processing success rate ≥95%
- ✅ Average processing lag <30 seconds
- ✅ All 21 tables updated today

**Alert Thresholds:**
- 🚨 DLQ messages >0 → Investigate immediately
- ⚠️ Backlog >10 messages for >5 minutes → Check processor health
- ⚠️ Processing lag >60 seconds → Check processor resources
- ⚠️ Success rate <90% → Review error logs

---

## Manual Operations

### Manually Trigger Processor

**Method 1: Via Pub/Sub (Recommended)**
```bash
# Publish message to topic
gcloud pubsub topics publish nba-scraper-complete \
  --message='{
    "scraper_name": "bdl_boxscores",
    "gcs_path": "gs://nba-scraped-data/ball-dont-lie/boxscores/2025-11-13/file.json",
    "execution_id": "manual-trigger-001",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "status": "success",
    "record_count": 150
  }'
```

**Method 2: Direct HTTP POST**
```bash
# Get service URL and token
PROCESSOR_URL=$(gcloud run services describe nba-processors \
  --region=us-west2 --format="value(status.url)")
TOKEN=$(gcloud auth print-identity-token)

# Call processor directly
curl -X POST "${PROCESSOR_URL}/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "data": "<base64_encoded_message>",
      "attributes": {"scraper_name": "bdl_boxscores"}
    }
  }'
```

### Reprocess Historical Data

**Trigger Scraper → Processor Flow:**
```bash
# Step 1: Trigger scraper for specific date
TOKEN=$(gcloud auth print-identity-token)
SCRAPER_URL=$(gcloud run services describe nba-scrapers \
  --region=us-west2 --format="value(status.url)")

curl -X POST "${SCRAPER_URL}/scraper/bdl-boxscores" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date": "2025-11-13"}'

# Step 2: Wait for Pub/Sub event (automatic)
# Step 3: Processor triggered automatically
# Step 4: Verify in BigQuery

sleep 30

bq query --use_legacy_sql=false "
SELECT COUNT(*) as records
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date = '2025-11-13'
"
```

### Test End-to-End Flow

```bash
# Comprehensive integration test
./bin/pubsub/test_pubsub_flow.sh

# Manual verification steps:
# 1. Check Pub/Sub infrastructure
./bin/pubsub/show_pubsub_architecture.sh

# 2. Monitor delivery
./bin/pubsub/monitor_pubsub.sh

# 3. Check BigQuery data
bq query "SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores
  WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)"
```

---

## Troubleshooting

### Issue 1: Messages in DLQ

**Symptoms:**
- DLQ message count >0
- Processing failures visible in logs

**Diagnosis:**
```bash
# Check DLQ
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub

# Pull failed messages
gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub \
  --limit=5 \
  --format=json > failed_messages.json

# Analyze message content
cat failed_messages.json | jq '.[] | .message.data' | base64 -d
```

**Resolution:**
1. Identify error pattern from message content
2. Fix underlying issue (processor code, GCS permissions, BigQuery schema)
3. Replay DLQ messages after fix:
   ```bash
   # Republish to main topic
   gcloud pubsub topics publish nba-scraper-complete \
     --message="<message_data_from_dlq>"
   ```

### Issue 2: High Backlog

**Symptoms:**
- `nba-processors-sub` backlog >10 messages
- Processing delay visible

**Diagnosis:**
```bash
# Check backlog
gcloud pubsub subscriptions describe nba-processors-sub \
  --format="value(numUndeliveredMessages)"

# Check processor status
gcloud run services describe nba-processors --region=us-west2

# Check recent errors
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-processors \
  AND severity>=ERROR" \
  --limit=20
```

**Resolution:**
1. **If processor down:** Redeploy processor service
2. **If slow processing:** Check processor resources, increase CPU/memory
3. **If GCS issues:** Verify permissions, check bucket accessibility
4. **If BigQuery issues:** Check quotas, verify schema matches data

### Issue 3: Missing Data in BigQuery

**Symptoms:**
- Scraper ran successfully
- No data in BigQuery table

**Diagnosis:**
```bash
# Step 1: Verify scraper published event
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-scrapers \
  AND jsonPayload.message=~'Published.*Pub/Sub'" \
  --limit=10

# Step 2: Check if event delivered
./bin/pubsub/monitor_pubsub.sh

# Step 3: Check processor logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-processors" \
  --limit=20

# Step 4: Verify GCS file exists
gsutil ls gs://nba-scraped-data/ball-dont-lie/boxscores/2025-11-13/
```

**Resolution:**
1. **Event not published:** Check scraper logs, verify Pub/Sub permissions
2. **Event not delivered:** Check subscription configuration
3. **Processor error:** Check logs, verify GCS path format
4. **GCS file missing:** Scraper may have failed to write

### Issue 4: Processing Lag >60 seconds

**Symptoms:**
- Data appears in BigQuery but with significant delay

**Diagnosis:**
```sql
-- Check recent processing lag
SELECT
  source_file_path,
  processed_at,
  TIMESTAMP_DIFF(
    processed_at,
    PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%S',
      REGEXP_EXTRACT(source_file_path, r'/(\d{10})')),
    SECOND
  ) as lag_seconds
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE()
ORDER BY processed_at DESC
LIMIT 20;
```

**Resolution:**
1. **If consistent lag:** Increase processor CPU/memory
2. **If spike:** Temporary issue, monitor for recurrence
3. **If only specific processors:** Optimize processor code
4. **If Pub/Sub delay:** Check subscription ACK deadline

---

## Next Steps

### Current State (November 15, 2025)

✅ **Phase 1→2 Integration:** COMPLETE & OPERATIONAL
- Scrapers publish events automatically
- Processors receive and process events
- Data loads to BigQuery successfully
- 100% message delivery rate verified

### Immediate Next Steps (Sprint 1 - Week of Nov 18)

🎯 **Phase 2→3 Integration (~2 hours effort)**

**Goal:** Enable automatic Phase 3 triggering from Phase 2 completion

**Tasks:**
1. Create `RawDataPubSubPublisher` class in `data_processors/raw/utils/`
2. Add publishing to Phase 2 processor base class
3. Create Pub/Sub topic: `nba-raw-data-complete`
4. Create subscription: `nba-analytics-sub` → analytics service
5. Test with one processor (e.g., NbacGamebookProcessor)
6. Verify Phase 3 analytics processors trigger automatically

**Success Criteria:**
- Phase 2 processor completes → publishes event
- Analytics service receives event
- Phase 3 processors trigger with dependency checking
- End-to-end flow: Scraper → Phase 2 → Phase 3

**Reference:** See `docs/architecture/implementation-status-and-roadmap.md` Sprint 1 for details.

### Medium-Term (Sprints 2-4 - November-December)

**Sprint 2:** Correlation ID Tracking (~6 hours)
- Add correlation_id to all Pub/Sub messages
- Create `pipeline_execution_log` table
- Track executions across all phases
- Enable end-to-end debugging

**Sprint 3:** Phase 3→4 Integration (~8 hours)
- Apply same Pub/Sub pattern to Phase 3→4
- Complete precompute orchestration service
- Test Phase 3 → Phase 4 flow

**Sprint 4:** Monitoring Dashboard (~8 hours)
- Create Grafana dashboard for pipeline health
- Set up alerts (DLQ, stuck pipelines, failure rates)
- Document monitoring procedures

### Long-Term Vision

**Complete Event-Driven Pipeline:**
```
Phase 1 (Scrapers) → Phase 2 (Raw) → Phase 3 (Analytics)
  → Phase 4 (Precompute) → Phase 5 (Predictions) → Phase 6 (Publishing)
```

**Full end-to-end automation with:**
- Event-driven triggering at every phase
- Correlation ID tracking from scraper → web app
- Automatic retries and DLQ recovery
- Entity-level granular updates
- Complete observability

**Timeline:** 8 sprints, ~73 hours total effort

**Reference:** See `docs/architecture/event-driven-pipeline-architecture.md` for complete vision.

---

## Documentation References

### Operational Guides
- **Phase 1 Operations:** `docs/orchestration/phase1_monitoring_operations_guide.md`
- **Pub/Sub Verification:** `docs/orchestration/pubsub-integration-verification-guide.md`
- **Grafana Monitoring:** `docs/orchestration/grafana-monitoring-guide.md`

### Architecture & Planning
- **Event-Driven Architecture:** `docs/architecture/event-driven-pipeline-architecture.md`
- **Implementation Roadmap:** `docs/architecture/implementation-status-and-roadmap.md`
- **Integration Plan:** `docs/architecture/phase1-to-phase5-integration-plan.md`

### Technical Specifications
- **Message Formats:** `docs/specifications/pubsub-message-formats.md`
- **BigQuery Schemas:** `schemas/bigquery/nba_raw/`
- **Processor Reference:** `data_processors/raw/`

### Implementation Details
- **Session Summary:** `docs/sessions/2025-11-13-phase2-pubsub-integration.md`
- **Pub/Sub Scripts:** `bin/pubsub/` (5 operational scripts)

---

## Quick Reference

### Critical Commands

```bash
# Health check
./bin/orchestration/quick_health_check.sh

# Monitor Pub/Sub
./bin/pubsub/monitor_pubsub.sh --watch

# Check DLQ
./bin/pubsub/check_dead_letter_queue.sh

# Test end-to-end
./bin/pubsub/test_pubsub_flow.sh

# View processor logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-processors" --limit=50
```

### Key Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Processing Success Rate | ≥95% | <90% |
| Processing Latency | <30s | >60s |
| Pub/Sub Backlog | 0 | >10 for >5min |
| DLQ Message Count | 0 | >0 |
| Data Quality Rate | ≥99% | <95% |

### Service Accounts

- **Scrapers:** `bigdataball-puller@...` (Pub/Sub publisher)
- **Processors:** `756957797294-compute@...` (Pub/Sub subscriber, Cloud Run invoker)

### Infrastructure

- **Scraper Service:** `nba-scrapers` (revision 00073, Nov 13 2025)
- **Processor Service:** `nba-processors` (deployed Nov 13 2025)
- **Pub/Sub Topic:** `nba-scraper-complete`
- **Pub/Sub Subscription:** `nba-processors-sub`
- **BigQuery Dataset:** `nba_raw` (21 tables)

---

**Document Status:** Current and verified
**Next Review:** After Sprint 1 completion (Phase 2→3 integration)
**Questions/Issues:** Refer to implementation-status-and-roadmap.md for known gaps and solutions

---

*End of Phase 2 Operations Guide v4.0*
