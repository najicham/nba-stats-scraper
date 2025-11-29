# Greenfield Architecture Plan - Phases 3-5 Complete Rebuild

**Status:** 🎯 Ready to Build From Scratch
**Context:** Phases 1-2 working with backfills, Phases 3-5 never run in production
**Opportunity:** Build event-driven architecture correctly from day 1
**Timeline:** 4-5 days, ~24 hours total effort

---

## Executive Summary

**The Opportunity:**
- Phases 3-5 have NEVER processed production data
- Current season (2024-25) has NO data yet
- Perfect chance to build the architecture RIGHT

**What We'll Build:**
- ✅ Fully event-driven pipeline (Phase 2 → 3 → 4 → 5)
- ✅ Proper dependency orchestration for Phase 4
- ✅ Comprehensive error handling and retries
- ✅ Unified patterns across all phases
- ✅ Production-ready monitoring and alerting
- ✅ Clean, maintainable codebase

**Timeline:**
- Day 1-2: Design & implement Phases 3-4-5
- Day 3: Testing and validation
- Day 4: Backfill testing with historical data
- Day 5: Enable current season processing

---

## Architecture Design

### Complete Event-Driven Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          COMPLETE PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1: Data Collection (Time-Based Start)                                │
│  ├─ Cloud Scheduler triggers scrapers hourly/daily                          │
│  ├─ Each scraper publishes to: nba-phase1-scrapers-complete                 │
│  └─ Message: {scraper, game_date, success, ...}                            │
│                                                                              │
│                          ↓ Pub/Sub Push                                     │
│                                                                              │
│  Phase 2: Raw Processing (Event-Driven)                                     │
│  ├─ Subscription: nba-phase2-raw-sub                                        │
│  ├─ 21 raw processors convert JSON → BigQuery                               │
│  ├─ Each processor publishes to: nba-phase2-raw-complete                    │
│  ├─ Message: {source_table, analysis_date, processor_name, success}        │
│  └─ Feature: Can disable Phase 3 trigger for backfills                     │
│                                                                              │
│                          ↓ Pub/Sub Push                                     │
│                                                                              │
│  Phase 3: Analytics (Event-Driven) ← WE'LL BUILD THIS                      │
│  ├─ Subscription: nba-phase3-analytics-sub                                  │
│  ├─ 5 analytics processors run in PARALLEL:                                 │
│  │   ├─ player_game_summary                                                 │
│  │   ├─ team_offense_game_summary                                           │
│  │   ├─ team_defense_game_summary                                           │
│  │   ├─ upcoming_player_game_context                                        │
│  │   └─ upcoming_team_game_context                                          │
│  ├─ Each processor publishes when complete                                  │
│  ├─ Publish to: nba-phase3-analytics-complete                               │
│  └─ Message: {processor_name, analysis_date, records_processed, success}   │
│                                                                              │
│                          ↓ Pub/Sub Push                                     │
│                                                                              │
│  Phase 3→4 Orchestrator (Cloud Function) ← NEW                              │
│  ├─ Listens to: nba-phase3-analytics-complete                               │
│  ├─ Tracks completion of all 5 Phase 3 processors                           │
│  ├─ Uses Firestore for state tracking (atomic updates)                     │
│  ├─ When ALL 5 complete → triggers Phase 4                                  │
│  └─ Publishes to: nba-phase4-trigger (internal orchestration)              │
│                                                                              │
│                          ↓ Pub/Sub Push                                     │
│                                                                              │
│  Phase 4: Precompute (Event-Driven) ← WE'LL BUILD THIS                     │
│  ├─ Subscription: nba-phase4-trigger-sub                                    │
│  ├─ 5 precompute processors with dependencies:                              │
│  │                                                                           │
│  │   Level 1 (Parallel - no dependencies):                                  │
│  │   ├─ team_defense_zone_analysis (~2 min)                                 │
│  │   ├─ player_shot_zone_analysis (~8 min)                                  │
│  │   └─ player_daily_cache (~10 min)                                        │
│  │           ↓                                                               │
│  │   Level 2 (Waits for Level 1):                                           │
│  │   └─ player_composite_factors (~15 min)                                  │
│  │       Depends on: ALL Level 1 + upcoming_player_game_context             │
│  │           ↓                                                               │
│  │   Level 3 (Waits for ALL above):                                         │
│  │   └─ ml_feature_store_v2 (~2 min)                                        │
│  │       Depends on: ALL Level 1 + Level 2                                  │
│  │                                                                           │
│  ├─ Each processor publishes when complete                                  │
│  ├─ Phase 4 orchestrator tracks progress                                    │
│  └─ When ml_feature_store_v2 complete → Publish to:                        │
│      nba-phase4-precompute-complete                                         │
│                                                                              │
│                          ↓ Pub/Sub Push                                     │
│                                                                              │
│  Phase 5: Predictions (Event-Driven + Backup) ← WE'LL BUILD THIS           │
│  ├─ PRIMARY: Subscription to nba-phase4-precompute-complete                 │
│  │   └─ Push to: /trigger endpoint                                          │
│  ├─ BACKUP: Cloud Scheduler at 6:00 AM PT                                   │
│  │   └─ HTTP POST to: /start endpoint (with 30-min wait)                   │
│  ├─ RETRY: Cloud Scheduler at 6:15 AM, 6:30 AM PT                          │
│  │   └─ HTTP POST to: /retry endpoint                                      │
│  └─ STATUS: Cloud Scheduler at 7:00 AM PT (10 AM ET SLA)                   │
│      └─ HTTP GET to: /status endpoint → Alert if <90% coverage             │
│                                                                              │
│  Phase 5 Coordinator:                                                        │
│  ├─ Validates Phase 4 ready (80% threshold OR 100 players)                 │
│  ├─ Queries Phase 3 for player list                                         │
│  ├─ Deduplication check (already processed?)                                │
│  ├─ Publishes ~450 messages to: prediction-request-prod                     │
│  └─ Tracks completion via: prediction-ready-prod                            │
│                                                                              │
│  Phase 5 Workers (100 concurrent):                                          │
│  ├─ Process one player each                                                 │
│  ├─ Query Phase 4 ml_feature_store_v2 for features                          │
│  ├─ Run 5 prediction systems                                                │
│  ├─ Write to: nba_predictions.player_prop_predictions                       │
│  └─ Publish to: prediction-ready-prod                                       │
│                                                                              │
│  Phase 5 Coordinator (Fan-In):                                              │
│  ├─ Receives prediction-ready events                                        │
│  ├─ Tracks progress (450/450)                                               │
│  └─ When complete → Publish to: nba-phase5-predictions-complete            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase A: Fix Phase 3 Analytics (Day 1, ~6 hours)

**Goal:** Make Phase 3 properly event-driven with completion publishing

#### A1. Add Pub/Sub Publishing to Phase 3 Base Class

**File:** `data_processors/analytics/analytics_base.py`

**Current state:** Already has `_publish_completion_message()` method (line 1516)

**Verify it works:**
```python
# Check current implementation at line 1516-1555
# Should publish to: nba-phase3-analytics-complete
# Message format: {source_table, analysis_date, processor_name, success, run_id}
```

**Action:** ✅ Already implemented! Just verify and test.

#### A2. Update Phase 3 Processors

**Files to check:**
- `player_game_summary_processor.py`
- `team_offense_game_summary_processor.py`
- `team_defense_game_summary_processor.py`
- `upcoming_player_game_context_processor.py`
- `upcoming_team_game_context_processor.py`

**Verify:** Each processor extends `AnalyticsProcessorBase` and calls `super().post_process()`

**Action:** Test that all 5 processors publish completion events

#### A3. Add Deduplication to Phase 3

**Why:** Prevent reprocessing if Pub/Sub retries

**Add to AnalyticsProcessorBase:**
```python
def _check_already_processed(self, analysis_date: date) -> bool:
    """
    Check if this processor already ran successfully for this date.
    Prevents duplicate processing from Pub/Sub retries.
    """
    from google.cloud import bigquery
    client = bigquery.Client(project=self.project_id)

    query = """
    SELECT status
    FROM `{project}.nba_reference.processor_run_history`
    WHERE processor_name = @processor_name
      AND data_date = @analysis_date
      AND status = 'success'
    ORDER BY processed_at DESC
    LIMIT 1
    """.format(project=self.project_id)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("processor_name", "STRING", self.__class__.__name__),
            bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)
        ]
    )

    results = list(client.query(query, job_config=job_config).result())
    already_done = len(results) > 0

    if already_done:
        logger.info(f"{self.__class__.__name__} already processed {analysis_date}, skipping")

    return already_done

# Add to run() method at the start:
def run(self, opts: Dict) -> bool:
    # ... existing setup code ...

    # NEW: Check deduplication
    if self._check_already_processed(analysis_date):
        return True  # Already done, return success

    # ... rest of existing run() logic ...
```

**Effort:** ~1 hour

#### A4. Test Phase 3 End-to-End

**Test script:**
```bash
# Manually trigger Phase 3 for a backfill date
curl -X POST "https://nba-phase3-analytics-processors-XXX.run.app/process" \
    -H "Content-Type: application/json" \
    -d '{
        "message": {
            "data": "'$(echo -n '{"source_table":"player_boxscores","analysis_date":"2024-01-15"}' | base64)'"
        }
    }'

# Check if all 5 processors published completion events
# Check processor_run_history for all 5 processors
bq query --use_legacy_sql=false '
SELECT processor_name, status, records_processed, processed_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = "2024-01-15"
  AND phase = "phase_3_analytics"
ORDER BY processed_at
'
```

**Effort:** ~1 hour

---

### Phase B: Build Phase 4 Orchestrator (Day 1-2, ~8 hours)

**Goal:** Proper dependency management for Phase 4 processors

#### B1. Create Cloud Function for Phase 3→4 Orchestration

**File:** `cloud_functions/phase3_to_phase4_orchestrator/main.py`

```python
"""
Phase 3 → Phase 4 Orchestrator
Tracks completion of all 5 Phase 3 processors, triggers Phase 4 when all done
"""
import functions_framework
from google.cloud import firestore, pubsub_v1
import logging
import json
import base64
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
PHASE3_PROCESSORS = [
    'PlayerGameSummaryProcessor',
    'TeamOffenseGameSummaryProcessor',
    'TeamDefenseGameSummaryProcessor',
    'UpcomingPlayerGameContextProcessor',
    'UpcomingTeamGameContextProcessor'
]

@functions_framework.cloud_event
def handle_phase3_completion(cloud_event):
    """
    Handle Phase 3 completion events.
    Track which processors have completed, trigger Phase 4 when all done.
    """
    try:
        # Decode Pub/Sub message
        pubsub_message = base64.b64decode(cloud_event.data["message"]["data"]).decode()
        event = json.loads(pubsub_message)

        processor_name = event.get('processor_name')
        analysis_date = event.get('analysis_date')
        success = event.get('success', True)

        if not success:
            logger.info(f"Phase 3 processor {processor_name} failed, not tracking")
            return

        logger.info(f"Received completion for {processor_name}, date {analysis_date}")

        # Track completion in Firestore
        db = firestore.Client(project=PROJECT_ID)
        doc_ref = db.collection('phase3_completion').document(analysis_date)

        # Atomic update: add this processor to completed set
        doc_ref.set({
            processor_name: {
                'completed_at': firestore.SERVER_TIMESTAMP,
                'run_id': event.get('run_id')
            }
        }, merge=True)

        # Check if all processors complete
        doc = doc_ref.get()
        if not doc.exists:
            logger.warning(f"Document not found for {analysis_date}")
            return

        data = doc.to_dict()
        completed_processors = set(data.keys())
        required_processors = set(PHASE3_PROCESSORS)

        logger.info(f"Completed: {completed_processors}")
        logger.info(f"Required: {required_processors}")

        if completed_processors >= required_processors:
            # ALL PROCESSORS COMPLETE! Trigger Phase 4
            logger.info(f"🎉 All Phase 3 processors complete for {analysis_date}, triggering Phase 4")

            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(PROJECT_ID, 'nba-phase4-trigger')

            message = {
                'event_type': 'phase3_all_complete',
                'analysis_date': analysis_date,
                'processors_completed': list(completed_processors),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            message_bytes = json.dumps(message).encode('utf-8')
            future = publisher.publish(topic_path, data=message_bytes)
            message_id = future.result(timeout=10.0)

            logger.info(f"Published Phase 4 trigger, message_id: {message_id}")

            # Mark orchestration complete
            doc_ref.set({
                'phase4_triggered': True,
                'phase4_triggered_at': firestore.SERVER_TIMESTAMP,
                'message_id': message_id
            }, merge=True)
        else:
            missing = required_processors - completed_processors
            logger.info(f"Waiting for {len(missing)} more processors: {missing}")

    except Exception as e:
        logger.error(f"Error in orchestrator: {e}", exc_info=True)
        raise
```

**Deployment:**
```bash
# Deploy Cloud Function
gcloud functions deploy phase3-to-phase4-orchestrator \
    --gen2 \
    --runtime=python311 \
    --region=us-west2 \
    --source=./cloud_functions/phase3_to_phase4_orchestrator \
    --entry-point=handle_phase3_completion \
    --trigger-topic=nba-phase3-analytics-complete \
    --project=nba-props-platform
```

**Effort:** ~3 hours

#### B2. Add Phase 4 Orchestrator for Internal Dependencies

**File:** `cloud_functions/phase4_orchestrator/main.py`

This tracks completion of Phase 4 processors and triggers dependent processors:

```python
"""
Phase 4 Internal Orchestrator
Manages dependencies between Phase 4 processors:
- Level 1: team_defense_zone, player_shot_zone, player_daily_cache (parallel)
- Level 2: player_composite_factors (waits for Level 1)
- Level 3: ml_feature_store_v2 (waits for all)
"""
# Similar structure to Phase 3→4 orchestrator
# Tracks 5 Phase 4 processors
# Triggers ml_feature_store_v2 when all dependencies ready
```

**Effort:** ~3 hours

#### B3. Update Phase 4 Processors to Publish Completion

**Add to PrecomputeProcessorBase:**
```python
def post_process(self) -> None:
    """
    Post-processing - publish completion event.
    """
    super().post_process()
    self._publish_completion_event()

def _publish_completion_event(self) -> None:
    """
    Publish completion event for dependency tracking.
    """
    try:
        from google.cloud import pubsub_v1
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(self.project_id, 'nba-phase4-processor-complete')

        message = {
            'processor_name': self.__class__.__name__,
            'analysis_date': self.opts['analysis_date'].isoformat(),
            'records_processed': len(self.transformed_data) if self.transformed_data else 0,
            'success': True,
            'run_id': self.run_id
        }

        message_bytes = json.dumps(message).encode('utf-8')
        future = publisher.publish(topic_path, data=message_bytes)
        future.result(timeout=10.0)

        logger.info(f"Published completion event for {self.__class__.__name__}")
    except Exception as e:
        logger.error(f"Failed to publish completion event: {e}")
```

**Effort:** ~1 hour

#### B4. Add ml_feature_store_v2 Phase 5 Trigger

**Add to MLFeatureStoreProcessor:**
```python
def _publish_phase5_trigger(self) -> None:
    """
    Publish to nba-phase4-precompute-complete to trigger Phase 5.
    This is separate from internal Phase 4 completion tracking.
    """
    # Same code as in IMPLEMENTATION-FULL.md
    # Publishes to: nba-phase4-precompute-complete
```

**Effort:** ~30 min

---

### Phase C: Build Phase 5 Integration (Day 2, ~4 hours)

**Goal:** Event-driven Phase 5 with backup scheduler

This is the same as IMPLEMENTATION-FULL.md:
- Add `/trigger` endpoint (Pub/Sub handler)
- Update `/start` endpoint (scheduler backup with validation)
- Add `/retry` endpoint (incremental processing)
- Add all 7 helper functions

**Code:** Already written in IMPLEMENTATION-FULL.md

**Effort:** ~4 hours (implementation + testing)

---

### Phase D: Infrastructure Deployment (Day 2, ~2 hours)

**New Topics to Create:**
```bash
# Phase 4 internal orchestration
gcloud pubsub topics create nba-phase4-trigger --project=nba-props-platform
gcloud pubsub topics create nba-phase4-processor-complete --project=nba-props-platform

# Phase 4 to Phase 5
gcloud pubsub topics create nba-phase4-precompute-complete --project=nba-props-platform

# Phase 5 internal
# (prediction-request-prod and prediction-ready-prod already exist)
```

**New Subscriptions:**
```bash
# Phase 4 orchestrator subscription
gcloud pubsub subscriptions create phase4-processor-complete-sub \
    --topic=nba-phase4-processor-complete \
    --push-endpoint=https://[PHASE4-ORCHESTRATOR-FUNCTION-URL] \
    --project=nba-props-platform

# Phase 5 trigger subscription
gcloud pubsub subscriptions create nba-phase5-trigger-sub \
    --topic=nba-phase4-precompute-complete \
    --push-endpoint=https://[COORDINATOR-URL]/trigger \
    --project=nba-props-platform
```

**Scheduler Jobs:**
```bash
# Phase 5 backup (6:00 AM PT)
# Phase 5 retry (6:15 AM, 6:30 AM PT)
# Phase 5 status (7:00 AM PT)
```

**Use script:** `bin/phase5/deploy_pubsub_infrastructure.sh` (already written)

---

### Phase E: Testing & Validation (Day 3, ~6 hours)

#### E1. Unit Tests (~3 hours)

Write tests for:
- Phase 3: Deduplication logic
- Phase 4: All orchestration logic
- Phase 5: All 7 helper functions + 3 endpoints

**Coverage goal:** >90%

#### E2. Integration Tests (~2 hours)

**Test 1: End-to-End Happy Path**
```bash
# 1. Trigger Phase 2 with backfill date
# 2. Verify Phase 3 receives trigger
# 3. Verify all 5 Phase 3 processors run
# 4. Verify Phase 3→4 orchestrator triggers Phase 4
# 5. Verify Phase 4 processors run in correct order
# 6. Verify ml_feature_store_v2 triggers Phase 5
# 7. Verify Phase 5 generates predictions
```

**Test 2: Deduplication**
```bash
# Trigger Phase 3 twice for same date
# Verify second trigger is skipped
```

**Test 3: Partial Failure Recovery**
```bash
# Simulate 2/5 Phase 3 processors failing
# Verify Phase 4 NOT triggered
# Re-run failed processors
# Verify Phase 4 triggers when all complete
```

#### E3. Backfill Testing (~1 hour)

**Test with historical data:**
```bash
# Pick a date with known good data (e.g., 2024-01-15)
# Trigger entire pipeline
# Verify predictions match expected output
```

---

### Phase F: Enable Current Season (Day 4-5, ~2 hours)

#### F1. Backfill Current Season

```bash
# Enable Phase 1 scrapers for current season
# Let them run for 2-3 days to collect data
# Monitor Phase 2 processing
```

#### F2. Enable Phase 2→3 Trigger

**Remove the disable flag:**
```python
# In Phase 2 raw processors
# Enable Pub/Sub publishing to Phase 3
ENABLE_PHASE3_TRIGGER = True  # Was False for backfills
```

#### F3. Monitor End-to-End

```bash
# Watch logs for all phases
# Verify event-driven triggering works
# Check latency metrics
# Verify predictions generated
```

---

## Timeline Summary

| Day | Phase | Hours | Deliverables |
|-----|-------|-------|--------------|
| **1** | A: Fix Phase 3 | 6 | Phase 3 event-driven + tested |
| **2** | B: Phase 4 orchestration | 8 | Cloud Functions deployed |
| **2** | C: Phase 5 integration | 4 | All endpoints implemented |
| **2** | D: Infrastructure | 2 | Pub/Sub topics/subs created |
| **3** | E: Testing | 6 | All tests passing |
| **4** | F: Backfill testing | 4 | Historical data validated |
| **5** | F: Enable current season | 2 | Live production pipeline |
| **Total** | | **32 hours** | **Complete pipeline** |

---

## Success Criteria

**Phase 3:**
- [ ] All 5 processors publish completion events
- [ ] Deduplication prevents duplicate processing
- [ ] Orchestrator tracks completion correctly

**Phase 4:**
- [ ] Processors run in correct dependency order
- [ ] ml_feature_store_v2 waits for all dependencies
- [ ] Phase 5 triggered immediately when ready

**Phase 5:**
- [ ] Event-driven trigger works (<5 min latency)
- [ ] Scheduler backup catches failures
- [ ] Retry logic processes stragglers
- [ ] >95% prediction completion rate

**Overall:**
- [ ] End-to-end latency: Phase 2 completion → Predictions ready in <60 min
- [ ] Zero duplicate processing
- [ ] Comprehensive error handling
- [ ] Clean audit trail in processor_run_history

---

## Advantages of This Approach

**vs. Minimal Integration (Original Plan):**

| Aspect | Minimal | Greenfield | Difference |
|--------|---------|------------|------------|
| **Time to first deploy** | 2 days | 5 days | +3 days |
| **Technical debt** | High | None | ✅ Clean start |
| **Future refactoring** | Required | Not needed | ✅ Saves weeks later |
| **Maintainability** | Complex | Simple | ✅ Unified patterns |
| **Real-time updates** | Hard to add | Easy to add | ✅ Foundation ready |
| **Debugging** | Difficult | Easy | ✅ Clear event flow |
| **Total effort** | 13 hours + refactor later | 32 hours once | ✅ Net savings |

**The extra 19 hours upfront saves you 40+ hours of refactoring later.**

---

## Next Steps

**Immediate:**
1. Review this plan
2. Confirm approach
3. Start Phase A (Fix Phase 3)

**This Week:**
1. Complete Phases A-D (infrastructure + code)
2. Complete Phase E (testing)

**Next Week:**
1. Backfill testing
2. Enable current season
3. Monitor production

---

**Document Status:** ✅ Ready for Implementation
**Recommendation:** Proceed with greenfield rebuild - perfect opportunity
**Expected Completion:** End of next week (5 business days)
