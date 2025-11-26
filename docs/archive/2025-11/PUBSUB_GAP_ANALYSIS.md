# Pub/Sub Architecture: Implementation vs Documentation Gap Analysis

**Date:** 2025-11-18
**Scope:** Compare actual Pub/Sub infrastructure and code to documented architecture
**Status:** Phase 1→2→3 operational, Phase 4-6 incomplete

---

## Executive Summary

**What's Working ✅**
- Phase 1 (Scrapers) → Phase 2 (Raw Processors): **Fully operational**
- Phase 2 (Raw) → Phase 3 (Analytics): **Fully operational**
- Topics and subscriptions properly configured with DLQs
- Code uses centralized topic configuration (`shared/config/pubsub_topics.py`)

**What's Incomplete 🚧**
- Phase 3 → Phase 4 → Phase 5 → Phase 6: **Infrastructure exists, services not deployed**
- No correlation_id propagation (documented but not implemented)
- No pipeline execution logging table (documented but not implemented)
- Entity-level granularity not implemented (documented for future)
- Legacy topic names still exist alongside new naming convention

---

## Topic Configuration Analysis

### Centralized Configuration ✅

**File:** `shared/config/pubsub_topics.py`

All topic names are centralized and follow naming convention:
```
nba-phase{N}-{content}-{type}
```

**Defined Topics:**
- ✅ Phase 1→2: `nba-phase1-scrapers-complete` + DLQ
- ✅ Phase 2→3: `nba-phase2-raw-complete` + DLQ
- ✅ Phase 3→4: `nba-phase3-analytics-complete` + DLQ
- ✅ Phase 4→5: `nba-phase4-precompute-complete` + DLQ
- ✅ Phase 5→6: `nba-phase5-predictions-complete` + DLQ
- ✅ Fallback triggers: `nba-phase{2-6}-fallback-trigger`
- ✅ Manual operations: `nba-manual-reprocess`

**Helper Methods:**
- `get_all_topics()` - Returns all topic names
- `get_phase_topics(phase)` - Returns topics for specific phase

**Status:** ✅ **Complete and well-structured**

---

## GCP Infrastructure Analysis

### Deployed Topics

**Command:** `gcloud pubsub topics list --project=nba-props-platform`

**Current State:**
```
✅ nba-phase1-scrapers-complete
✅ nba-phase1-scrapers-complete-dlq
✅ nba-phase2-raw-complete
✅ nba-phase2-raw-complete-dlq
✅ nba-phase2-fallback-trigger
✅ nba-phase3-fallback-trigger
✅ nba-phase4-fallback-trigger
✅ nba-phase5-fallback-trigger
✅ nba-phase6-fallback-trigger
⚠️  nba-scraper-complete (LEGACY - should be deprecated)
⚠️  nba-scraper-complete-dlq (LEGACY - should be deprecated)
❌ nba-phase3-analytics-complete (MISSING!)
❌ nba-phase3-analytics-complete-dlq (MISSING!)
❌ nba-phase4-precompute-complete (MISSING!)
❌ nba-phase4-precompute-complete-dlq (MISSING!)
❌ nba-phase5-predictions-complete (MISSING!)
❌ nba-phase5-predictions-complete-dlq (MISSING!)
```

### Deployed Subscriptions

**Command:** `gcloud pubsub subscriptions list --project=nba-props-platform`

**Current State:**
```
✅ nba-phase2-raw-sub
   → Topic: nba-phase1-scrapers-complete
   → Subscriber: nba-phase2-raw-processors

✅ nba-phase3-analytics-sub
   → Topic: nba-phase2-raw-complete
   → Subscriber: nba-phase3-analytics-processors

✅ nba-phase3-fallback-sub
   → Topic: nba-phase3-fallback-trigger
   → Subscriber: nba-phase3-analytics-processors

✅ nba-phase2-raw-complete-dlq-sub
   → Topic: nba-phase2-raw-complete-dlq
   → Type: Pull (for monitoring)

⚠️  nba-processors-sub (LEGACY)
   → Topic: nba-scraper-complete
   → Should be migrated/deprecated

❌ Phase 4, 5, 6 subscriptions: NOT CREATED
```

### Deployed Services

**Command:** `gcloud run services list --project=nba-props-platform`

**Current State:**
```
✅ nba-phase2-raw-processors (us-west2)
   → Handles Phase 1→2 messages
   → URL: https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app

✅ nba-phase3-analytics-processors (us-west2)
   → Handles Phase 2→3 messages
   → URL: https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app

⚠️  nba-processors (us-west2) - LEGACY
⚠️  nba-analytics-processors (us-west2) - LEGACY (duplicate?)
⚠️  nba-reference-processors (us-west2) - Purpose unclear

❌ nba-phase4-precompute-processors - NOT DEPLOYED
❌ nba-phase5-prediction-coordinator - NOT DEPLOYED
❌ nba-phase5-prediction-worker - NOT DEPLOYED
❌ nba-phase6-publishing-service - NOT DEPLOYED
```

**Gap:** Phase 4, 5, 6 services not deployed yet

---

## Code Implementation Analysis

### Phase 2 (Raw Processors) → Phase 3 Publishing ✅

**File:** `data_processors/raw/processor_base.py:492`

**Implementation:**
```python
def _publish_completion_event(self) -> None:
    """Publish Phase 2 completion event to trigger Phase 3 analytics."""
    from shared.utils.pubsub_publishers import RawDataPubSubPublisher

    publisher = RawDataPubSubPublisher(project_id=project_id)
    message_id = publisher.publish_raw_data_loaded(
        source_table=self.table_name,
        game_date=str(game_date),
        record_count=self.stats.get('rows_inserted', 0),
        execution_id=self.run_id,
        correlation_id=correlation_id,
        success=True
    )
```

**Status:** ✅ **Implemented and working**

**Message Format:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2024-11-14",
  "record_count": 450,
  "execution_id": "proc-abc-123",
  "correlation_id": "scrape-xyz-456",
  "timestamp": "2024-11-14T12:00:00Z",
  "phase": 2,
  "success": true
}
```

---

### Phase 3 (Analytics) Message Receiver ✅

**File:** `data_processors/analytics/main_analytics_service.py`

**Implementation:**
- ✅ Flask service listening at `/process` endpoint
- ✅ Decodes Pub/Sub messages
- ✅ Has ANALYTICS_TRIGGERS mapping: source_table → processor classes
- ✅ Runs multiple processors for same source table
- ✅ Returns 200 on success (acknowledges message)

**Processor Triggers Configured:**
```python
ANALYTICS_TRIGGERS = {
    'nbac_gamebook_player_stats': [PlayerGameSummaryProcessor],
    'bdl_player_boxscores': [
        PlayerGameSummaryProcessor,
        TeamOffenseGameSummaryProcessor
    ],
    'nbac_scoreboard_v2': [
        TeamOffenseGameSummaryProcessor,
        TeamDefenseGameSummaryProcessor
    ],
    'nbac_injury_report': [PlayerGameSummaryProcessor],
    'odds_api_player_points_props': [PlayerGameSummaryProcessor],
}
```

**Status:** ✅ **Implemented and operational**

---

### Phase 3 → Phase 4 Publishing ❓

**Expected:** Analytics processors should publish to `nba-phase3-analytics-complete`

**File:** `data_processors/analytics/analytics_base.py`

**Status:** 🚧 **Need to verify** - Does analytics_base have `_publish_completion_event()` similar to processor_base?

**Gap:** Unclear if Phase 3 processors publish completion events

---

### Phase 4, 5, 6 Services ❌

**Expected Services:**
- Phase 4: Precompute processors
- Phase 5: Prediction coordinator + workers
- Phase 6: Publishing service (Firestore + GCS)

**Status:**
- ❌ No Phase 4 service code found
- ⚠️  Phase 5 code exists in `predictions/` directory but not deployed
- ❌ No Phase 6 publishing service found

**Note:** Architecture docs describe these in detail, but implementation incomplete

---

## Documentation vs Implementation Gaps

### 1. Correlation ID Tracking ❌

**Documented:** `docs/architecture/04-event-driven-pipeline-architecture.md:688`

The architecture doc describes correlation_id flowing through entire pipeline:
```
Phase 1: Generates correlation_id = "abc123"
Phase 2: Extracts and forwards correlation_id
Phase 3: Extracts and forwards correlation_id
...
```

**Implementation:**
- ✅ Phase 2 publishers include `correlation_id` field
- ⚠️  Phase 3 receivers extract it but unclear if they forward
- ❌ No unified correlation_id generation strategy
- ❌ Scrapers don't generate correlation_id consistently

**Gap:** Partial implementation, needs completion

---

### 2. Pipeline Execution Log Table ❌

**Documented:** `docs/architecture/04-event-driven-pipeline-architecture.md:645`

```sql
CREATE TABLE nba_orchestration.pipeline_execution_log (
    execution_id STRING,
    correlation_id STRING,
    phase INT64,
    processor_name STRING,
    status STRING,  -- 'started', 'completed', 'failed'
    ...
)
```

**Implementation:**
- ❌ Table does not exist
- ❌ No code logging to this table
- ❌ No Grafana dashboards querying this table

**Gap:** Completely unimplemented (design only)

---

### 3. Entity-Level Granularity ❌

**Documented:** `docs/architecture/04-event-driven-pipeline-architecture.md:313`

Enhanced message format with affected entities:
```json
{
  "affected_entities": {
    "players": ["1630567"],
    "teams": ["LAL"],
    "games": ["0022500225"]
  },
  "change_type": "incremental"
}
```

**Implementation:**
- ❌ Publishers don't include `affected_entities`
- ❌ Processors don't filter by entity IDs
- ✅ Doc correctly marks this as "Phase 2" future enhancement

**Gap:** Intentionally deferred (correct)

---

### 4. Dead Letter Queue (DLQ) Monitoring ⚠️

**Documented:** `docs/architecture/04-event-driven-pipeline-architecture.md:608`

DLQ retry and recovery workflows documented.

**Implementation:**
- ✅ DLQ topics created
- ✅ DLQ subscriptions configured with pull
- ⚠️  No automated DLQ monitoring (alerts)
- ⚠️  Recovery scripts exist in `bin/recovery/` but unclear if operational

**Gap:** Infrastructure ready, monitoring/alerting incomplete

---

### 5. Fallback Triggers (Time-Based Safety Nets) ⚠️

**Documented:** Phase-specific fallback topics for time-based triggering

**Implementation:**
- ✅ All fallback topics created (phase2-6)
- ✅ Phase 3 fallback subscription created
- ❌ No Cloud Scheduler jobs triggering fallbacks
- ❌ No code handling fallback messages differently

**Gap:** Infrastructure exists, scheduling not configured

---

## Terraform vs Actual State Mismatch

**File:** `infra/pubsub.tf`

**Issue:** Terraform uses old topic naming:
```hcl
resource "google_pubsub_topic" "analytics_ready" {
  name = "analytics-ready"  # ❌ OLD NAME
}

resource "google_pubsub_topic" "precompute_complete" {
  name = "precompute-complete"  # ❌ OLD NAME
}
```

**Expected names (from pubsub_topics.py):**
- `nba-phase3-analytics-complete`
- `nba-phase4-precompute-complete`

**Gap:** Terraform file needs updating to match naming convention

---

## Infrastructure Creation Scripts

**Script:** `bin/infrastructure/create_phase2_phase3_topics.sh`

**Status:** ✅ Well-written script that:
- Creates Phase 2→3 topics
- Creates subscriptions with proper configuration
- Sets up DLQs
- Creates fallback triggers
- Idempotent (checks if exists before creating)

**Gap:**
- ❌ No equivalent script for Phase 4, 5, 6
- ⚠️  Script hardcodes service URL (should be parameterized)

**Recommendation:** Create similar scripts:
- `create_phase3_phase4_topics.sh`
- `create_phase4_phase5_topics.sh`
- `create_phase5_phase6_topics.sh`

---

## Phase-by-Phase Status Summary

| Phase | Topics | Subscriptions | Service | Publishing Code | Docs |
|-------|--------|---------------|---------|----------------|------|
| **1→2** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **2→3** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **3→4** | ❌ | ❌ | ❌ | ❓ | ✅ |
| **4→5** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **5→6** | ❌ | ❌ | ❌ | ❌ | ✅ |

**Legend:**
- ✅ Complete and working
- ❓ Unclear/needs verification
- ❌ Missing or not implemented
- ⚠️  Partial implementation

---

## Priority Gaps to Address

### High Priority (Blocking Phase 3→4→5)

1. **Create Phase 3→4 Topics & Subscriptions**
   - Create `nba-phase3-analytics-complete` topic
   - Create `nba-phase3-analytics-complete-dlq` topic
   - Create subscription (when Phase 4 service ready)

2. **Verify Phase 3 Publishing**
   - Check if `analytics_base.py` publishes completion events
   - If not, add `_publish_completion_event()` method
   - Test Phase 3→4 message flow

3. **Deploy Phase 4 Service**
   - Create precompute processor service
   - Deploy to Cloud Run
   - Configure Pub/Sub push subscription

### Medium Priority (Observability)

4. **Implement Pipeline Execution Logging**
   - Create `nba_orchestration.pipeline_execution_log` table
   - Add logging to all processor bases
   - Enable end-to-end tracing

5. **Set Up DLQ Monitoring**
   - Create Grafana dashboard for DLQ depth
   - Set up alerts for messages in DLQ
   - Test recovery procedures

6. **Configure Fallback Schedulers**
   - Create Cloud Scheduler jobs for each phase
   - Configure to trigger fallbacks on schedule
   - Test fallback message handling

### Low Priority (Cleanup & Optimization)

7. **Clean Up Legacy Topics**
   - Migrate any remaining usage of `nba-scraper-complete`
   - Delete legacy topics and subscriptions
   - Update any hardcoded references

8. **Update Terraform**
   - Align `infra/pubsub.tf` with naming convention
   - Add Phase 4, 5, 6 infrastructure
   - Apply terraform changes

9. **Add Entity-Level Granularity**
   - Extend message format with `affected_entities`
   - Update processors to support entity filtering
   - Measure performance improvements

---

## Recommendations

### Immediate Next Steps

1. **Audit Phase 3 Analytics Code**
   ```bash
   # Check if analytics processors publish to Phase 4
   grep -r "publish" data_processors/analytics/
   grep -r "AnalyticsPubSubPublisher" data_processors/analytics/
   ```

2. **Create Missing Phase 3→4 Topics**
   ```bash
   # Create script: bin/infrastructure/create_phase3_phase4_topics.sh
   # Model after create_phase2_phase3_topics.sh
   ```

3. **Test Current Phase 2→3 Flow**
   ```bash
   # Trigger a test message and verify it reaches Phase 3
   gcloud pubsub topics publish nba-phase2-raw-complete \
     --message='{"source_table":"test","game_date":"2024-11-18"}'

   # Check Phase 3 service logs
   gcloud run services logs read nba-phase3-analytics-processors --limit=50
   ```

4. **Document Current State**
   - Update implementation status docs
   - Mark Phase 1→2→3 as operational
   - Clarify Phase 4-6 as "designed but not deployed"

### Long-Term Strategy

**Phase 1:** Complete Phase 3→4 Connection (1-2 weeks)
- Create topics/subscriptions
- Add publishing to analytics processors
- Deploy initial Phase 4 service (even if simple)
- Verify end-to-end flow

**Phase 2:** Add Observability (1 week)
- Implement pipeline_execution_log table
- Add logging to all phases
- Create monitoring dashboards

**Phase 3:** Phase 4→5→6 (4-6 weeks)
- Deploy prediction infrastructure
- Deploy publishing service
- Complete end-to-end pipeline

---

## Questions for User

1. **Phase 3 Publishing:** Should we verify if analytics processors are publishing, or assume they're not and add it?

2. **Phase 4 Priority:** Is Phase 4 (precompute) needed before Phase 5 (predictions), or can we skip to Phase 5?

3. **Legacy Cleanup:** Safe to delete `nba-scraper-complete` topic, or still in use?

4. **Service Naming:** Three analytics services exist (nba-analytics-processors, nba-phase3-analytics-processors, nba-processors) - which is canonical?

5. **Terraform Strategy:** Should we manage infrastructure via Terraform or continue with shell scripts?

---

**Analysis Complete:** 2025-11-18
**Next Action:** Review with team and prioritize gap closure
