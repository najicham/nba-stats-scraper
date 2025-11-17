# Implementation Status & Roadmap

**File:** `docs/architecture/05-implementation-status-and-roadmap.md`
**Created:** 2025-11-14 22:41 PST
**Last Updated:** 2025-11-15 (Verified Phase 1→2 working, confirmed gaps)
**Purpose:** **Current implementation status** vs architecture, prioritized 8-sprint roadmap (~73 hours)
**Status:** Current - Verified 2025-11-15 (Phase 1→2 100% working, 1,482 events/3hrs)
**Related:** [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md) (complete vision)

---

## Executive Summary

The event-driven pipeline architecture is **well-designed and documented**, but only **Phase 1-3 are partially implemented**. The good news: the core patterns (dependency checking, event routing, idempotency) are working well in Phase 3. The challenge: these patterns need to be extended to Phases 4-6 and properly connected via Pub/Sub.

**Implementation Progress: ~45% Complete**

| Phase | Component | Status | Completeness |
|-------|-----------|--------|--------------|
| 1 | Scrapers + Pub/Sub Publishing | ✅ Complete | 100% |
| 2 | Raw Processors (event reception) | ✅ Complete | 90% |
| 2 | Raw Processors → Pub/Sub Publishing | ❌ Missing | 0% |
| 3 | Analytics Event Routing | ✅ Complete | 100% |
| 3 | Analytics Dependency Checking | ✅ Complete | 100% |
| 3 | Analytics Idempotency | ✅ Complete | 100% |
| 3 | Analytics → Pub/Sub Publishing | ❌ Missing | 0% |
| 4 | Precompute Orchestration | ❌ Skeleton Only | 10% |
| 5 | Predictions Integration | ⚠️ Partial | 40% |
| 6 | Publishing Service | ❌ Not Implemented | 0% |
| - | Correlation ID Tracking | ❌ Missing | 0% |
| - | Pipeline Execution Log (unified) | ❌ Missing | 20% |
| - | Monitoring Dashboards | ⚠️ Basic | 30% |
| - | DLQ Recovery Automation | ⚠️ Partial | 40% |

---

## What We Have (The Good News)

### ✅ Phase 1 → Phase 2: WORKING END-TO-END

**Scrapers → Pub/Sub → Raw Processors**

```
Phase 1: Scrapers
  ├─ ScraperBase publishes to "nba-phase1-scrapers-complete" topic
  ├─ Includes execution metadata (execution_id, status, gcs_path, etc.)
  ├─ 26+ scrapers all inherit and auto-publish
  └─ Logs to scraper_execution_log table

Phase 2: Raw Processors
  ├─ Flask service receives Pub/Sub events
  ├─ Normalizes message format (supports GCS Object Finalize + Scraper Completion)
  ├─ Routes to 19 registered processors
  ├─ Loads JSON from GCS, transforms, writes to BigQuery
  └─ BUT: Doesn't publish completion events (critical gap!)
```

**Implementation Quality:** Excellent, production-ready

**Key Files:**
- `scrapers/utils/pubsub_utils.py` - Publisher implementation
- `scrapers/scraper_base.py:650-737` - Publishing hooks
- `data_processors/raw/main_processor_service.py` - Event routing

---

### ✅ Phase 3: PARTIALLY WORKING

**Analytics Event Routing + Dependency Checking**

```
Phase 3: Analytics Processors
  ├─ Flask service receives events (but Phase 2 doesn't publish yet!)
  ├─ ANALYTICS_TRIGGERS registry maps tables → processors
  ├─ Multi-processor fan-out (one table triggers multiple processors)
  ├─ AnalyticsBase.check_dependencies() validates upstream tables
  │   ├─ CRITICAL vs OPTIONAL dependency classification
  │   ├─ Stale data detection (WARN/FAIL thresholds)
  │   └─ Source metadata tracking
  ├─ Idempotency checking prevents duplicate processing
  └─ BUT: Doesn't publish completion events (critical gap!)
```

**Implemented Dependencies:**
- `PlayerGameSummaryProcessor` - 6 tables (2 critical, 4 optional)
- `TeamOffenseProcessor` - Multiple dependencies
- `TeamDefenseProcessor` - Multiple dependencies

**Implementation Quality:** Very good, follows architecture well

**Key Files:**
- `data_processors/analytics/main_analytics_service.py` - Event routing
- `data_processors/analytics/analytics_base.py` - Dependency checking
- `data_processors/analytics/player_game_summary_processor.py` - Example processor

---

### ⚠️ Phase 4-6: SKELETON OR MISSING

**Precompute, Predictions, Publishing**

```
Phase 4: Precompute (10% implemented)
  ├─ main_precompute_service.py exists (40 lines, stub)
  ├─ 5 processors implemented (player_daily_cache, composite_factors, etc.)
  └─ BUT: No Flask orchestration, no event integration

Phase 5: Predictions (40% implemented)
  ├─ coordinator.py exists with worker implementation
  ├─ progress_tracker.py exists
  └─ BUT: No Pub/Sub integration, runs standalone

Phase 6: Publishing (0% implemented)
  └─ Not started - needs Firestore + GCS publishing
```

---

## What We're Missing (The Critical Gaps)

### ❌ Gap 1: Phase 2 → Phase 3 Event Publishing

**Problem:** Raw processors complete successfully but don't trigger Phase 3

**Impact:** Phase 3 analytics never run automatically (manual triggering only)

**Fix Required:**
```python
# Add to RawProcessorBase after successful BigQuery load:
from shared.utils.pubsub_utils import RawDataPubSubPublisher

class RawProcessorBase:
    def run(self, opts):
        # ... existing load logic ...

        # NEW: Publish completion event
        publisher = RawDataPubSubPublisher()
        publisher.publish_raw_data_loaded(
            source_table=self.table_name,
            game_date=opts['game_date'],
            record_count=len(records),
            correlation_id=opts.get('correlation_id'),
            execution_id=self.execution_id
        )
```

**Effort:** ~2 hours (create publisher class + add to base)

---

### ❌ Gap 2: Phase 3 → Phase 4 Event Publishing

**Problem:** Analytics processors complete but don't trigger Phase 4

**Impact:** Precompute layer never runs

**Fix Required:**
```python
# Add to AnalyticsBase after successful processing:
from shared.utils.pubsub_utils import AnalyticsPubSubPublisher

class AnalyticsBase:
    def run(self, opts):
        # ... existing processing logic ...

        # NEW: Publish completion event
        publisher = AnalyticsPubSubPublisher()
        publisher.publish_analytics_complete(
            processor_name=self.__class__.__name__,
            game_date=opts['game_date'],
            affected_entities=self.affected_entities,
            correlation_id=opts.get('correlation_id'),
            execution_id=self.execution_id
        )
```

**Effort:** ~2 hours (similar to Gap 1)

---

### ❌ Gap 3: Phase 4 Orchestration Service

**Problem:** Flask stub exists but doesn't wire processors together

**Impact:** Precompute processors can't be triggered automatically

**Fix Required:**
```python
# Complete main_precompute_service.py (copy pattern from analytics):

PRECOMPUTE_TRIGGERS = {
    'player_game_summary': [PlayerDailyCacheProcessor, PlayerCompositeFactorsProcessor],
    'team_offense_game_summary': [TeamDefenseZoneAnalysisProcessor],
    # ... etc
}

@app.route('/process', methods=['POST'])
def process_precompute():
    message = decode_pubsub_message(request)
    source_table = message['source_table']

    processors = PRECOMPUTE_TRIGGERS.get(source_table, [])
    for ProcessorClass in processors:
        processor = ProcessorClass()
        processor.run({'game_date': message['game_date']})

    return jsonify({"status": "completed"}), 200
```

**Effort:** ~4 hours (copy pattern, create trigger registry, test)

---

### ❌ Gap 4: Correlation ID Propagation

**Problem:** No way to track a single update through all 6 phases

**Impact:** Can't debug end-to-end, can't detect stuck pipelines

**Fix Required:**
```python
# 1. Phase 1 generates correlation_id (already has run_id)
correlation_id = f"{workflow}_{execution_id}"

# 2. Phase 2 receives correlation_id in message, passes to processor
opts['correlation_id'] = message.get('correlation_id')

# 3. Each processor logs with correlation_id
self.log_pipeline_execution(
    correlation_id=opts['correlation_id'],
    phase=2,
    status='completed'
)

# 4. Each processor publishes correlation_id in event
publisher.publish(correlation_id=opts['correlation_id'])
```

**Effort:** ~6 hours (thread through all phases, update logging)

---

### ❌ Gap 5: Unified Pipeline Execution Log

**Problem:** Only `scraper_execution_log` exists, no Phase 2-6 tracking

**Impact:** Can't query end-to-end pipeline status

**Fix Required:**
```sql
-- Create table (already designed in architecture doc):
CREATE TABLE nba_orchestration.pipeline_execution_log (
    execution_id STRING,
    correlation_id STRING,
    phase INT64,
    processor_name STRING,
    status STRING,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds FLOAT64,
    dependencies_met BOOL,
    missing_dependencies ARRAY<STRING>,
    error_message STRING,
    affected_entities JSON,
    ...
)
PARTITION BY game_date
CLUSTER BY correlation_id, phase, status;
```

**Effort:** ~3 hours (create table, add logging to base classes)

---

### ❌ Gap 6: Monitoring Dashboard

**Problem:** No visibility into pipeline health, stuck pipelines

**Impact:** Must manually check each phase to debug issues

**Fix Required:**
```sql
-- Query 1: Pipeline completion status
SELECT
    correlation_id,
    MAX(phase) as max_phase_reached,
    COUNTIF(status = 'failed') as failures
FROM pipeline_execution_log
WHERE game_date = CURRENT_DATE()
GROUP BY correlation_id
HAVING max_phase_reached < 6 OR failures > 0;

-- Query 2: Phase-by-phase breakdown
SELECT
    phase,
    COUNT(*) as executions,
    COUNTIF(status = 'completed') as completed,
    COUNTIF(status = 'failed') as failed,
    AVG(duration_seconds) as avg_duration
FROM pipeline_execution_log
WHERE game_date = CURRENT_DATE()
GROUP BY phase
ORDER BY phase;
```

**Effort:** ~8 hours (create Grafana dashboard, write queries, test)

---

### ❌ Gap 7: Phase 5 & 6 Integration

**Problem:** Predictions and Publishing run standalone, not event-driven

**Impact:** No automatic pipeline completion to web app

**Fix Required:**
- Phase 4 → Phase 5: Precompute publishes completion event
- Phase 5: Coordinator receives event, runs predictions, publishes completion
- Phase 6: Publishing service transforms and publishes to Firestore/GCS

**Effort:** ~16 hours (significant new service creation)

---

## Prioritized Roadmap

### 🎯 Sprint 1: Connect Phase 2 → Phase 3 (Week 1)

**Goal:** Enable automatic Phase 3 triggering from Phase 2 completion

**Tasks:**
1. ✅ Create `RawDataPubSubPublisher` class (~1 hour)
2. ✅ Add publishing to `RawProcessorBase.run()` (~30 min)
3. ✅ Create Pub/Sub topic: `nba-phase2-raw-complete` (~15 min)
4. ✅ Create subscription pointing to analytics service (~15 min)
5. ✅ Test with single scraper → raw processor → analytics flow (~2 hours)
6. ✅ Verify all 19 raw processors publish events (~1 hour)

**Success Criteria:**
- Run `nbac_injury_report` scraper
- Verify Phase 2 raw processor completes
- Verify Phase 3 analytics processors trigger automatically
- Check logs confirm dependency validation works

**Estimated Effort:** 5 hours
**Risk:** Low (pattern already proven in Phase 3)

---

### 🎯 Sprint 2: Add Correlation ID Tracking (Week 1-2)

**Goal:** Enable end-to-end tracing through pipeline

**Tasks:**
1. ✅ Update scrapers to generate `correlation_id` (~30 min)
2. ✅ Thread correlation_id through Phase 2 messages (~1 hour)
3. ✅ Thread correlation_id through Phase 3 messages (~1 hour)
4. ✅ Create `pipeline_execution_log` table (~1 hour)
5. ✅ Add logging to `RawProcessorBase` (~1 hour)
6. ✅ Add logging to `AnalyticsBase` (~1 hour)
7. ✅ Test correlation_id flows end-to-end (~2 hours)

**Success Criteria:**
- Query `pipeline_execution_log` and see Phase 1-3 executions
- Filter by `correlation_id` and see single pipeline journey
- Verify `affected_entities` JSON captured correctly

**Estimated Effort:** 7.5 hours
**Risk:** Medium (cross-cutting change)

---

### 🎯 Sprint 3: Connect Phase 3 → Phase 4 (Week 2)

**Goal:** Enable automatic Phase 4 triggering from Phase 3 completion

**Tasks:**
1. ✅ Create `AnalyticsPubSubPublisher` class (~1 hour)
2. ✅ Add publishing to `AnalyticsBase.run()` (~30 min)
3. ✅ Complete `main_precompute_service.py` Flask orchestration (~3 hours)
4. ✅ Create `PRECOMPUTE_TRIGGERS` registry (~1 hour)
5. ✅ Create Pub/Sub topic: `nba-phase3-analytics-complete` (~15 min)
6. ✅ Create subscription pointing to precompute service (~15 min)
7. ✅ Test Phase 3 → Phase 4 flow (~2 hours)

**Success Criteria:**
- Analytics processor completes → publishes event
- Precompute service receives event
- Correct precompute processors trigger based on registry
- Dependency checking works in precompute processors

**Estimated Effort:** 8 hours
**Risk:** Medium (new service completion)

---

### 🎯 Sprint 4: Basic Monitoring Dashboard (Week 3)

**Goal:** Visibility into pipeline health and stuck pipelines

**Tasks:**
1. ✅ Create BigQuery monitoring queries (~2 hours)
   - Pipeline completion status
   - Phase-by-phase breakdown
   - Recent failures
   - Stuck pipeline detection
2. ✅ Create Grafana dashboard (~4 hours)
   - Pipeline health panel
   - Failure rate panel
   - Average duration by phase
   - DLQ message count
3. ✅ Test dashboard with real data (~1 hour)
4. ✅ Document dashboard usage (~1 hour)

**Success Criteria:**
- Dashboard shows real-time pipeline status
- Can identify stuck pipelines within 5 minutes
- Can drill down to specific correlation_id
- Alerts when DLQ has messages

**Estimated Effort:** 8 hours
**Risk:** Low (query-based)

---

### 🎯 Sprint 5: DLQ Recovery Automation (Week 3-4)

**Goal:** Automate recovery from transient failures

**Tasks:**
1. ✅ Create DLQ replay script (~3 hours)
2. ✅ Add replay-from-phase capability (~2 hours)
3. ✅ Test replay scenarios (~2 hours)
4. ✅ Document recovery procedures (~1 hour)

**Success Criteria:**
- Can replay DLQ messages automatically
- Can trigger Phase 3 reprocessing manually
- Recovery procedures documented

**Estimated Effort:** 8 hours
**Risk:** Medium (needs careful testing)

---

### 🎯 Sprint 6: Phase 4 → Phase 5 Integration (Week 4-5)

**Goal:** Connect precompute to predictions

**Tasks:**
1. ✅ Add Pub/Sub publishing to precompute processors (~1 hour)
2. ✅ Update prediction coordinator to receive events (~4 hours)
3. ✅ Create Pub/Sub topic: `nba-phase4-precompute-complete` (~15 min)
4. ✅ Test Phase 4 → Phase 5 flow (~3 hours)

**Success Criteria:**
- Precompute completes → triggers predictions
- Predictions run with correct game scope
- Correlation ID flows through

**Estimated Effort:** 8.5 hours
**Risk:** Medium (coordinator integration)

---

### 🎯 Sprint 7: Phase 6 Publishing Service (Week 5-6)

**Goal:** Publish predictions to Firestore/GCS for web app

**Tasks:**
1. ✅ Create publishing service skeleton (~2 hours)
2. ✅ Implement Firestore publishing (~4 hours)
3. ✅ Implement GCS publishing (~3 hours)
4. ✅ Add JSON transformation logic (~3 hours)
5. ✅ Create Pub/Sub topic: `nba-phase5-predictions-complete` (~15 min)
6. ✅ Test Phase 5 → Phase 6 flow (~3 hours)

**Success Criteria:**
- Predictions published to Firestore in web-friendly format
- Predictions published to GCS for caching
- Web app can consume published data
- End-to-end Phase 1 → Phase 6 working

**Estimated Effort:** 15.5 hours
**Risk:** High (new service, external dependencies)

---

### 🎯 Sprint 8: Entity-Level Granularity (Week 7-8)

**Goal:** Add incremental update support (as designed in architecture)

**Tasks:**
1. ✅ Add `affected_entities` to all Pub/Sub messages (~2 hours)
2. ✅ Update processors to accept `player_ids`, `game_ids`, `team_ids` (~6 hours)
3. ✅ Test incremental updates (~3 hours)
4. ✅ Measure performance improvements (~1 hour)

**Success Criteria:**
- Injury update processes single player in < 5 seconds
- Full boxscore update still processes all players correctly
- No accuracy degradation

**Estimated Effort:** 12 hours
**Risk:** Medium (optimization, needs testing)

---

## Summary: Effort Estimates

| Sprint | Focus | Effort (hours) | Priority | Dependencies |
|--------|-------|----------------|----------|--------------|
| 1 | Phase 2 → 3 Connection | 5 | 🔴 Critical | None |
| 2 | Correlation ID Tracking | 7.5 | 🔴 Critical | Sprint 1 |
| 3 | Phase 3 → 4 Connection | 8 | 🔴 Critical | Sprint 2 |
| 4 | Monitoring Dashboard | 8 | 🟡 High | Sprint 2 |
| 5 | DLQ Recovery | 8 | 🟡 High | Sprint 3 |
| 6 | Phase 4 → 5 Connection | 8.5 | 🟡 High | Sprint 3 |
| 7 | Phase 6 Publishing | 15.5 | 🟢 Medium | Sprint 6 |
| 8 | Entity-Level Granularity | 12 | 🟢 Medium | Sprint 7 |

**Total Estimated Effort:** ~72.5 hours (~2 weeks at 40 hrs/week)

---

## Quick Wins (Do First)

### 1. Phase 2 → Phase 3 Publishing (2 hours)

**Impact:** Unlocks automatic analytics processing
**Risk:** Very low
**File Changes:** 2 files (`pubsub_utils.py`, `processor_base.py`)

### 2. Correlation ID Propagation (4 hours)

**Impact:** Enables end-to-end debugging
**Risk:** Low
**File Changes:** 4 files (scraper_base, raw/analytics base classes)

### 3. Complete Phase 4 Orchestration (4 hours)

**Impact:** Unlocks entire precompute layer
**Risk:** Low (copy existing pattern)
**File Changes:** 1 file (`main_precompute_service.py`)

---

## Risks & Mitigation

### Risk 1: Breaking Existing Workflows
**Mitigation:** Add Pub/Sub publishing behind feature flag, test thoroughly before full rollout

### Risk 2: Message Volume Overwhelming Services
**Mitigation:** Start with date-level granularity, add rate limiting, monitor Pub/Sub metrics

### Risk 3: Correlation ID Performance Impact
**Mitigation:** Indexed column, minimal overhead, test with realistic load

### Risk 4: Phase 6 Firestore Costs
**Mitigation:** Start with GCS only, add Firestore for real-time updates only when needed

---

## Next Steps

1. **Review this roadmap** - Confirm priorities align with business needs
2. **Start Sprint 1** - Connect Phase 2 → Phase 3 (highest ROI, lowest risk)
3. **Parallel track:** Create monitoring queries while implementing connections
4. **Weekly checkpoints:** Review progress, adjust priorities based on learnings

---

## Appendix: Files to Modify

### Phase 2 → 3 Connection
- `scrapers/utils/pubsub_utils.py` - Add `RawDataPubSubPublisher`
- `data_processors/raw/processor_base.py` - Add publishing call

### Correlation ID
- `scrapers/scraper_base.py` - Generate correlation_id
- `data_processors/raw/processor_base.py` - Thread and log
- `data_processors/analytics/analytics_base.py` - Thread and log
- `schemas/bigquery/nba_orchestration/` - Create `pipeline_execution_log.sql`

### Phase 3 → 4 Connection
- `scrapers/utils/pubsub_utils.py` - Add `AnalyticsPubSubPublisher`
- `data_processors/analytics/analytics_base.py` - Add publishing call
- `data_processors/precompute/main_precompute_service.py` - Complete orchestration

### Monitoring
- `monitoring/dashboards/` - New Grafana JSON
- `monitoring/queries/` - BigQuery monitoring queries
- `bin/orchestration/` - Enhanced monitoring scripts

### Recovery
- `bin/orchestration/replay_dlq.py` - New DLQ replay script
- `bin/orchestration/replay_pipeline.py` - New pipeline replay script
- `docs/orchestration/` - Recovery procedures documentation

---

**Last Updated:** 2025-11-15
**Status:** Roadmap Defined - Ready to Execute
**Next Action:** Review with team, begin Sprint 1
