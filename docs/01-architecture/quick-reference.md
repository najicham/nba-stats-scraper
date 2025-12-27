# NBA Data Pipeline - Quick Reference

**File:** `docs/01-architecture/quick-reference.md`
**Created:** 2025-11-15 10:00 PST
**Last Updated:** 2025-12-27 (v2.0 - Full system operational)
**Purpose:** At-a-glance overview of the event-driven pipeline architecture
**For detailed docs:** See v1.0 architecture docs: [Pub/Sub Topics](./orchestration/pubsub-topics.md), [Orchestrators](./orchestration/orchestrators.md), [Firestore State](./orchestration/firestore-state-management.md)

---

## 🎯 The Big Picture

**What:** Event-driven data pipeline from NBA API scraping → predictions → web app

**How:** 5 phases connected via Pub/Sub with atomic orchestrators coordinating transitions

**Status:** v1.0 Deployed and Production Ready (2025-11-29)

---

## 📊 System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                NBA DATA PIPELINE v1.0                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Phase 1: Scrapers (33) ✅ Production                       │
│  └─► Pub/Sub: nba-phase1-scrapers-complete ✅               │
│      ↓                                                       │
│  Phase 2: Raw Processors (21) ✅ Production                 │
│  └─► Pub/Sub: nba-phase2-raw-complete ✅                   │
│      ↓                                                       │
│  Phase 2→3 Orchestrator ✅ Cloud Function (tracks 21)       │
│  └─► Pub/Sub: nba-phase3-trigger ✅                        │
│      ↓                                                       │
│  Phase 3: Analytics Processors (5) ✅ Production            │
│  └─► Pub/Sub: nba-phase3-analytics-complete ✅             │
│      ↓                                                       │
│  Phase 3→4 Orchestrator ✅ Cloud Function (tracks 5)        │
│  └─► Pub/Sub: nba-phase4-trigger ✅ (+ entities_changed)   │
│      ↓                                                       │
│  Phase 4: Precompute Processors (5) ✅ Production           │
│  └─► Pub/Sub: nba-phase4-precompute-complete ✅            │
│      ↓                                                       │
│  Phase 5: Predictions ✅ Production                         │
│  └─► Pub/Sub: nba-phase5-predictions-complete ✅           │
│      ↓                                                       │
│  Phase 6: Publishing ✅ Production (GCS JSON exports)       │
│  └─► Static JSON files to GCS for website                   │
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

## 📈 Current Status (2025-12-27)

### What's Working ✅

**Complete Event-Driven Pipeline (v2.0 Production)**
- 33 scrapers collect data from NBA APIs
- 21 raw processors load to BigQuery `nba_raw.*` tables
- Phase 2→3 orchestrator coordinates 21 processor completions
- 5 analytics processors create `nba_analytics.*` summaries
- Phase 3→4 orchestrator coordinates 5 processor completions + entity aggregation
- 5 precompute processors generate ML features
- Prediction coordinator and workers operational
- Phase 6 publishing exports predictions to GCS as static JSON
- Full Pub/Sub event chain working end-to-end
- Atomic Firestore transactions prevent race conditions
- End-to-end correlation ID tracking

**Same-Day Prediction Schedulers (Added Dec 2025):**
| Scheduler | Time (ET) | Purpose |
|-----------|-----------|---------|
| `same-day-phase3` | 10:30 AM | UpcomingPlayerGameContextProcessor for TODAY |
| `same-day-phase4` | 11:00 AM | MLFeatureStoreProcessor for TODAY |
| `same-day-predictions` | 11:30 AM | Prediction coordinator for TODAY |

**Date Modes:**
- `analysis_date: "AUTO"` → Resolves to YESTERDAY (post-game processing)
- `analysis_date: "TODAY"` → Resolves to current date in ET (same-day predictions)

**Key v2.0 Infrastructure:**
- 8 Pub/Sub topics for event-driven communication
- 2 Cloud Function orchestrators (Phase 2→3, Phase 3→4)
- Firestore for atomic state management
- Cloud Run for Phase 5 predictions
- GCS buckets for Phase 6 JSON exports
- AWS SES for email alerts

### Remaining Work ⏳

1. **Historical backfill completion**
   - 4-season backfill (2021-2024) Phase 5 in progress
   - 2021-22 complete, 2022-2025 pending

2. **System evolution**
   - Adaptive learning framework (blocked by backfill)

---

## 🚀 Current Focus

### Active: Four-Season Backfill

**Goal:** Complete historical data for ML model training

**Status:**
- Phases 1-4: Complete for all 4 seasons (2021-2024)
- Phase 5: 2021-22 complete, 2022-2025 in progress

**See:** [08-projects/current/four-season-backfill/](../08-projects/current/four-season-backfill/)

### Active: System Evolution

**Goal:** Implement adaptive learning framework

**Status:** Planning (blocked by backfill completion)

**See:** [08-projects/current/system-evolution/](../08-projects/current/system-evolution/)

---

## 📚 Documentation Map

**New to the system? Read in this order:**

1. **[SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md)** ⭐ START HERE
   - Current deployment status
   - Data coverage metrics
   - Quick links

2. **[pipeline-design.md](./pipeline-design.md)**
   - Complete 6-phase architecture
   - Design principles and patterns

3. **[Orchestration Docs](./orchestration/)**
   - Pub/Sub topics and message formats
   - Cloud Function orchestrators
   - Firestore state management
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

**"How do I check pipeline health?"**
```bash
# Quick health check
./bin/orchestration/quick_health_check.sh

# Validate specific date
python3 bin/validate_pipeline.py 2024-01-15
```

**"What's the current priority?"**
Four-season historical backfill (Phase 5 predictions for 2022-2025 seasons).

**"Are predictions automatic?"**
Yes - v1.0 pipeline is fully event-driven. Predictions run automatically after Phase 4 completes.

**"How do I implement a new processor?"**
See existing examples:
- Phase 2: `data_processors/raw/processor_base.py`
- Phase 3: `data_processors/analytics/player_game_summary/`
- Phase 4: `data_processors/precompute/ml_feature_store/`

**"How do I validate data?"**
```bash
# Single date
python3 bin/validate_pipeline.py 2024-01-15

# Date range with JSON output
python3 bin/validate_pipeline.py 2024-01-15 2024-01-28 --format json
```

See: [Validation System](../07-monitoring/validation-system.md)

---

## 💡 Key Files

**Scrapers:**
- `scrapers/scraper_base.py` - Base class with Pub/Sub publishing

**Phase 2 (Raw):**
- `data_processors/raw/main_processor_service.py` - Event routing
- `data_processors/raw/processor_base.py` - Base class with run history

**Phase 3 (Analytics):**
- `data_processors/analytics/main_analytics_service.py` - Event routing
- `data_processors/analytics/analytics_base.py` - Dependency checking + quality tracking

**Phase 4 (Precompute):**
- `data_processors/precompute/main_precompute_service.py` - Event routing
- `data_processors/precompute/precompute_base.py` - Base class with quality tracking

**Phase 5 (Predictions):**
- `predictions/coordinator/coordinator.py` - Orchestrates prediction generation
- `predictions/worker/` - Worker pool for parallel predictions

**Validation:**
- `bin/validate_pipeline.py` - Pipeline validation tool
- `shared/validation/` - Validation framework

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

- **Architecture docs:** `docs/01-architecture/README.md`
- **Orchestration guides:** `docs/01-architecture/orchestration/`
- **Operations:** `docs/02-operations/`
- **Deployment guide:** `docs/04-deployment/v1.0-deployment-guide.md`
- **System status:** [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md)

---

**Last Updated:** 2025-12-27
**Next Review:** After four-season backfill complete
