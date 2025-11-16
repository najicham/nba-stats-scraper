# NBA Data Pipeline - Quick Reference

**File:** `docs/architecture/00-quick-reference.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** At-a-glance overview of the event-driven pipeline architecture
**For detailed docs:** Start with [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md)

---

## 🎯 The Big Picture

**What:** Event-driven data pipeline from NBA API scraping → predictions → web app

**How:** 6 phases connected via Pub/Sub, each phase triggers the next automatically

**Status:** ~45% implemented (Phase 1→2 working 100%, verified 2025-11-15)

---

## 📊 System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    NBA DATA PIPELINE                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Phase 1: Scrapers (26+) ✅ 100%                            │
│  └─► Pub/Sub: nba-scraper-complete                         │
│      ↓                                                       │
│  Phase 2: Raw Processors (19) ✅ 100% (reception)           │
│  └─► Pub/Sub: nba-raw-data-complete ❌ 0% (publishing)     │
│      ↓                                                       │
│  Phase 3: Analytics Processors ⚠️ 90%                       │
│  └─► Pub/Sub: nba-analytics-complete ❌ Missing            │
│      ↓                                                       │
│  Phase 4: Precompute Processors ⚠️ 10% (skeleton)          │
│  └─► Pub/Sub: nba-precompute-complete ❌ Missing           │
│      ↓                                                       │
│  Phase 5: Prediction Processors ⚠️ 40% (standalone)        │
│  └─► Pub/Sub: nba-predictions-complete ❌ Missing          │
│      ↓                                                       │
│  Phase 6: Publishing Service ❌ Not started                 │
│  └─► Firestore + GCS → Web App                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 Key Concepts

**Event-Driven Architecture**
- Each phase publishes Pub/Sub events when complete
- Next phase automatically triggered (no manual coordination)
- Automatic retries via Pub/Sub (exponential backoff)
- Dead Letter Queues (DLQ) preserve failed messages

**Opportunistic Triggering**
- Phase 3 triggered on ANY Phase 2 completion
- Checks dependencies each time via `check_dependencies()`
- Skips if not ready (will retry on next trigger)
- Self-healing automatic retries

**Dependency Coordination**
- Phase 3+ processors define dependencies (critical vs optional)
- Example: PlayerGameSummaryProcessor needs 6 Phase 2 tables
- Only processes when critical dependencies met
- Optional dependencies enhance but don't block

**Idempotency**
- Processors track recent executions
- Prevent duplicate work (don't reprocess if done in last hour)
- Safe to retry messages

**Correlation ID**
- Unique ID flows through entire pipeline (Phase 1→6)
- Enables end-to-end debugging
- Detects stuck pipelines
- Example: `morning_operations_abc123`

---

## 📈 Current Status (2025-11-15)

### What's Working ✅

**Phase 1 → Phase 2 (100%)**
- 26 scrapers collect data from NBA APIs
- Publish to `nba-scraper-complete` topic
- 19 raw processors receive events via Pub/Sub
- Load to BigQuery `nba_raw.*` tables
- **Verified:** 1,482 events in past 3 hours, 100% delivery

**Phase 3 Analytics (90%)**
- Event routing infrastructure ready
- Dependency checking implemented
- Idempotency tracking working
- 3+ analytics processors operational

### Critical Gaps ❌

1. **Phase 2 doesn't publish events** (0%) - Sprint 1: ~5 hrs
   - Blocks automatic Phase 3 triggering
   - Manual triggers only

2. **No correlation ID tracking** (0%) - Sprint 2: ~8 hrs
   - Can't trace end-to-end pipeline flow
   - Can't detect stuck pipelines

3. **Phase 4-6 not connected** (0-10%) - Sprints 3-7: ~40 hrs
   - Precompute, predictions, publishing all manual

---

## 🚀 Next Steps

### Sprint 1: Connect Phase 2→3 (~5 hours) 🔴 Critical

**Goal:** Enable automatic Phase 3 analytics triggering

**Tasks:**
1. Create `RawDataPubSubPublisher` utility
2. Add publishing to Phase 2 processor base classes
3. Create Pub/Sub infrastructure (topic, subscription, DLQ)
4. Test end-to-end flow

**Impact:** Unlocks automatic analytics processing

### Sprint 2: Correlation ID Tracking (~8 hours) 🔴 Critical

**Goal:** End-to-end pipeline visibility

**Tasks:**
1. Generate correlation_id in scrapers
2. Thread through all phases via Pub/Sub messages
3. Create `pipeline_execution_log` table
4. Add logging to all processor base classes

**Impact:** Can debug stuck pipelines, track data lineage

### Sprint 3-8: Complete Pipeline (~60 hours)

See [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md) for full plan.

---

## 📚 Documentation Map

**New to the system? Read in this order:**

1. **[04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md)** ⭐ START HERE
   - Complete 6-phase architecture
   - Design principles and patterns
   - ~1,100 lines (comprehensive)

2. **[05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md)**
   - What works vs what's missing
   - Prioritized 8-sprint plan (~73 hours)
   - Gap analysis and effort estimates

3. **[01-phase1-to-phase5-integration-plan.md](./01-phase1-to-phase5-integration-plan.md)**
   - Detailed Phase 2→3 integration plan
   - Dependency coordination solutions
   - Implementation specifics

4. **[02-phase1-to-phase5-granular-updates.md](./02-phase1-to-phase5-granular-updates.md)**
   - Entity-level granularity (performance optimization)
   - Incremental updates (process 1 player vs 450)
   - Sprint 8 enhancement

5. **[03-pipeline-monitoring-and-error-handling.md](./03-pipeline-monitoring-and-error-handling.md)**
   - End-to-end monitoring and alerting
   - DLQ handling and recovery procedures
   - Correlation ID tracking design

6. **[06-change-detection-and-event-granularity.md](./06-change-detection-and-event-granularity.md)** (FUTURE)
   - Fine-grained change detection patterns
   - When to optimize vs keep it simple
   - Decision framework with metrics
   - Read when planning optimizations

---

## 🔍 Common Questions

**"How do I check if Phase 1→2 is working?"**
```bash
bin/orchestration/quick_health_check.sh
bin/orchestration/check_pubsub_health.sh
```

**"What's the most critical gap?"**
Phase 2→3 connection (Sprint 1: ~5 hours). Everything else depends on this.

**"When will predictions be automatic?"**
After Sprint 6 (~40 hours of work across Sprints 1-6).

**"How do I implement a new processor?"**
See existing examples:
- Phase 2: `data_processors/raw/processor_base.py`
- Phase 3: `data_processors/analytics/player_game_summary_processor.py`

**"Where are the code examples?"**
- `examples/pubsub_integration/` - Publishers and message formats
- `examples/monitoring/` - BigQuery queries
- `examples/recovery/` - DLQ replay scripts

---

## 💡 Key Files

**Scrapers:**
- `scrapers/scraper_base.py` - Base class with Pub/Sub publishing

**Phase 2 (Raw):**
- `data_processors/raw/main_processor_service.py` - Event routing
- `data_processors/raw/processor_base.py` - Base class (needs publishing added)

**Phase 3 (Analytics):**
- `data_processors/analytics/main_analytics_service.py` - Event routing
- `data_processors/analytics/analytics_base.py` - Dependency checking
- `data_processors/analytics/player_game_summary_processor.py` - Example processor

**Phase 4 (Precompute):**
- `data_processors/precompute/main_precompute_service.py` - Stub (needs completion)

**Phase 5 (Predictions):**
- `predictions/coordinator.py` - Standalone (needs Pub/Sub integration)

**Monitoring:**
- `bin/orchestration/quick_health_check.sh` - Phase 1 health
- `bin/orchestration/check_pubsub_health.sh` - Pub/Sub metrics
- `docs/monitoring/01-grafana-monitoring-guide.md` - Grafana setup

---

## 🎓 Learning Path

**For implementers:**
1. Read this quick reference
2. Read doc 04 (architecture)
3. Read doc 05 (status & roadmap)
4. Check examples/ directory for code samples
5. Start with Sprint 1 tasks

**For operators:**
1. Read operational guides in `docs/orchestration/`
2. Learn monitoring scripts in `bin/orchestration/`
3. Understand DLQ recovery procedures (doc 03)

**For architects:**
1. Read docs 04, 01, 02, 03 in order
2. Understand design decisions and trade-offs
3. Review implementation status (doc 05)

---

## 📞 Quick Links

- **Architecture docs:** `docs/architecture/README.md`
- **Operational guides:** `docs/orchestration/`
- **Code examples:** `examples/`
- **Sprint roadmap:** [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md)
- **Pub/Sub status:** `docs/orchestration/pubsub-integration-status-2025-11-15.md`

---

**Last Updated:** 2025-11-15
**Next Review:** After Sprint 1 completion (Phase 2→3 connection)
