# Processors Documentation

**Last Updated:** 2025-11-15
**Purpose:** Data processor operations for Phases 2-5
**Audience:** Engineers operating and troubleshooting data processors

---

## 📖 Reading Order (Start Here!)

**New to processors? Read these in order:**

### Phase 2: Raw Data Processing

### 1. **01-phase2-operations-guide.md** ⭐ START HERE
   - **Created:** 2025-11-14 23:43 PST
   - **Phase 2 raw data processor operations**
   - **Why read this:** Learn how Phase 2 processors transform GCS JSON → BigQuery raw tables
   - **Status:** ✅ Deployed & operational (verified 1,482 events, 100% delivery)

### Phase 3: Analytics Processing

### 2. **02-phase3-operations-guide.md** ⭐ START HERE for Phase 3
   - **Created:** 2025-11-15 14:30 PST
   - **Phase 3 analytics processor operations**
   - **Why read this:** Learn how Phase 3 transforms raw data → analytics tables (player/team summaries, upcoming context)
   - **Status:** 🚧 Draft (awaiting deployment)

### 3. **03-phase3-scheduling-strategy.md**
   - **Created:** 2025-11-15 14:45 PST
   - **Cloud Scheduler and Pub/Sub configuration for Phase 3**
   - **Why read this:** Deploy Phase 3 orchestration infrastructure (time-based + event-driven)
   - **Status:** 🚧 Draft (awaiting deployment)

### 4. **04-phase3-troubleshooting.md**
   - **Created:** 2025-11-15 15:00 PST
   - **Failure scenarios and recovery procedures**
   - **Why read this:** Fix Phase 3 issues, manual triggers, runbooks
   - **Status:** 🚧 Draft (awaiting deployment)

### Phase 4: Precompute Processing

### 5. **05-phase4-operations-guide.md** ⭐ START HERE for Phase 4
   - **Created:** 2025-11-15 15:30 PST
   - **Phase 4 precompute processor operations**
   - **Why read this:** Learn how Phase 4 pre-aggregates analytics → precompute tables (5 processors with complex dependencies)
   - **Status:** 🚧 Draft (awaiting deployment)

### 6. **06-phase4-scheduling-strategy.md**
   - **Created:** 2025-11-15 15:45 PST
   - **Cloud Scheduler and 4-way dependency management**
   - **Why read this:** Deploy Phase 4 orchestration with complex dependency chains (3 strategies: Cloud Function, Cloud Workflows, Time-based)
   - **Status:** 🚧 Draft (awaiting deployment)

### 7. **07-phase4-troubleshooting.md**
   - **Created:** 2025-11-15 16:00 PST
   - **Failure scenarios and recovery procedures**
   - **Why read this:** Fix Phase 4 issues, 7 failure scenarios including early season handling
   - **Status:** 🚧 Draft (awaiting deployment)

### 8. **08-phase4-ml-feature-store-deepdive.md** 🎯 Advanced
   - **Created:** 2025-11-15 16:30 PST
   - **ML Feature Store V2 deep-dive (most complex processor in system)**
   - **Why read this:** Understand 4-way dependency orchestration, Phase 3 fallback, quality scoring (0-100), cross-dataset writes, Phase 5 integration, incident response, performance optimization
   - **Status:** 🚧 Draft (awaiting deployment)

### Phase 5: Prediction Processing ✅ Documentation Moved

**📦 Phase 5 documentation has been moved to `docs/predictions/`**

**Why moved:** Phase 5 has distinct architecture (coordinator-worker pattern, ML prediction systems) and deserves dedicated documentation directory for better discoverability.

**New location:** [`docs/predictions/`](../predictions/README.md)

**Quick links:**
- **Getting Started:** [`tutorials/01-getting-started.md`](../predictions/tutorials/01-getting-started.md) ⭐⭐ **READ THIS FIRST**
- **Understanding Systems:** [`tutorials/02-understanding-prediction-systems.md`](../predictions/tutorials/02-understanding-prediction-systems.md)
- **Worked Examples:** [`tutorials/03-worked-prediction-examples.md`](../predictions/tutorials/03-worked-prediction-examples.md)
- **Command Reference:** [`tutorials/04-operations-command-reference.md`](../predictions/tutorials/04-operations-command-reference.md)
- **Deployment Guide:** [`operations/01-deployment-guide.md`](../predictions/operations/01-deployment-guide.md)
- **Daily Operations:** [`operations/05-daily-operations-checklist.md`](../predictions/operations/05-daily-operations-checklist.md)
- **Performance Monitoring:** [`operations/06-performance-monitoring.md`](../predictions/operations/06-performance-monitoring.md)
- **Emergency Procedures:** [`operations/09-emergency-procedures.md`](../predictions/operations/09-emergency-procedures.md)
- **ML Training:** [`ml-training/01-initial-model-training.md`](../predictions/ml-training/01-initial-model-training.md)
- **Feature Strategy:** [`ml-training/03-feature-development-strategy.md`](../predictions/ml-training/03-feature-development-strategy.md)
- **Algorithm Specs:** [`algorithms/01-composite-factor-calculations.md`](../predictions/algorithms/01-composite-factor-calculations.md)

**Documentation stats:**
- **Files:** 23 comprehensive docs across 7 categories (~305KB)
- **Coverage:** Tutorials (5), Operations (9), ML Training (3), Algorithms (2), Architecture (1), Design (1), Data Sources (2)
- **Status:** ✅ Complete and ready for deployment

---

## 🗂️ What Goes in This Directory

**Processors** = Operations guides for data transformation across all phases

**Belongs here:**
- ✅ Phase 2 processor operations (GCS → nba_raw)
- ✅ Phase 3 analytics processor guides (nba_raw → nba_analytics) [future]
- ✅ Phase 4 precompute processor guides (nba_analytics → nba_precompute) [future]
- ✅ Phase 5 prediction processor guides (nba_precompute → nba_predictions) [future]
- ✅ Processor troubleshooting and debugging
- ✅ Processor deployment guides

**Does NOT belong here:**
- ❌ Pub/Sub infrastructure (goes in `infrastructure/`)
- ❌ Phase 1 scheduler logic (goes in `orchestration/`)
- ❌ Monitoring queries (goes in `monitoring/`)
- ❌ Data mappings (goes in `data-flow/`)

**Rule of thumb:** If it's about operating/troubleshooting a data processor, it goes here.

---

## 📋 Current Topics

### Phase 2: Raw Data Processing ✅ Deployed
- **Processors:** 21 processors (nbac_schedule, nbac_player_list, odds_events, etc.)
- **Trigger:** Pub/Sub (listens to `scraper-success` topic)
- **Transform:** GCS JSON → BigQuery raw tables
- **Features:** Comprehensive validation, error handling, 100% delivery rate

### Phase 3: Analytics Processing 🚧 Documentation Complete
- **Processors:** 5 processors
  - Historical (3): player_game_summary, team_offense_game_summary, team_defense_game_summary
  - Upcoming Context (2): upcoming_team_game_context, upcoming_player_game_context
- **Trigger:** Time-based (Cloud Scheduler) + Event-driven (Pub/Sub)
- **Transform:** nba_raw → nba_analytics (player/team summaries, pre-game context)
- **Features:** Multi-source fallback, universal player IDs, graceful degradation
- **Duration:** 30-40 seconds total (all processors)
- **Status:** Documentation ready, awaiting code implementation

### Phase 4: Precompute Processing 🚧 Documentation Complete
- **Processors:** 5 processors
  - Parallel Set 1 (2): team_defense_zone_analysis, player_shot_zone_analysis
  - Parallel Set 2 (2): player_composite_factors, player_daily_cache
  - Final (1): ml_feature_store_v2 (4-way dependency - most complex in system)
- **Trigger:** Time-based start (11 PM) + Event-driven continuation (Pub/Sub)
- **Transform:** nba_analytics → nba_precompute → nba_predictions (cross-dataset!)
- **Features:** Sequential with parallelization, 4-way dependency, Phase 3 fallback, quality scoring
- **Duration:** 25-40 minutes total (critical path: 25 min)
- **Status:** Documentation ready, awaiting code implementation
- **Complexity:** Higher than Phase 3 (4 docs vs 3 docs due to ML Feature Store deep-dive)

### Phase 5: Prediction Processing 📦 Moved to docs/predictions/
- **Status:** Documentation moved to dedicated directory [`docs/predictions/`](../predictions/README.md)
- **Why moved:** Distinct architecture (coordinator-worker, ML systems) deserves dedicated space
- **Quick start:** Read [`docs/predictions/tutorials/01-getting-started.md`](../predictions/tutorials/01-getting-started.md) ⭐⭐
- **Documentation:** 7 comprehensive docs (tutorials, operations, data sources, architecture)
- **Summary:**
  - 2 services: Coordinator (Cloud Run Job) + Worker (0-20 auto-scaling instances)
  - 5 ML systems: Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble
  - Processing: 450 players in 2-5 minutes (parallel fan-out via Pub/Sub)
  - Features: Confidence-weighted ensemble, edge calculation, graceful degradation

### Future Phases
- **Phase 6 Publishing:** Web app JSON generation (planned)

---

## 🔗 Related Documentation

**Infrastructure & Integration:**
- **Pub/Sub:** `docs/infrastructure/` - Event infrastructure
- **Phase 1:** `docs/orchestration/` - Upstream scraper orchestration

**Observability:**
- **Monitoring:** `docs/monitoring/` - Grafana dashboards for processor health
- **Data Flow:** `docs/data-flow/` - Input/output schemas and transformations

**Architecture:**
- **Design:** `docs/architecture/` - Overall pipeline architecture

---

## 📝 Adding New Documentation

**To add processor documentation:**

1. **Determine phase** - Which phase is this processor for?
2. **Find next number:** `ls *.md | tail -1` → Currently at 01, next is 02
3. **Create file:** `02-phase3-analytics-guide.md` (example)
4. **Use standard metadata header**
5. **Update this README** with the new document

**Naming convention:**
- Phase-specific guides: `NN-phaseN-{topic}-guide.md`
- Cross-phase guides: `NN-processor-{topic}.md`

**See:** `docs/DOCUMENTATION_GUIDE.md` for file organization standards

---

## 🗄️ Archive Policy

**Move to `archive/` when:**
- Processor operations superseded by new approach
- Phase documentation replaced by updated version
- Historical reference only (no longer in production)

**Archive structure:**
```
archive/
├── YYYY-MM-DD/     (session artifacts)
└── old/            (superseded guides)
```

---

**Directory Status:** Active
**File Organization:** Chronological numbering (01-99)
**Next Available Number:** 13

---

## 🚀 Quick Reference

**Phase 2 Processors:**
- **Deployed:** 21 processors operational
- **Trigger:** Pub/Sub `scraper-success` topic
- **Status:** ✅ 100% delivery rate (Nov 15, 2025)
- **Guide:** `01-phase2-operations-guide.md`

**Phase 3 Processors:**
- **Planned:** 5 processors (3 historical + 2 upcoming context)
- **Trigger:** Cloud Scheduler (time-based) + Pub/Sub (event-driven)
- **Status:** 🚧 Documentation complete, awaiting implementation
- **Guides:**
  - Operations: `02-phase3-operations-guide.md`
  - Scheduling: `03-phase3-scheduling-strategy.md`
  - Troubleshooting: `04-phase3-troubleshooting.md`

**Phase 4 Processors:**
- **Planned:** 5 processors (2+2 parallel sets + 1 final with 4-way dependency)
- **Trigger:** Cloud Scheduler (11 PM start) + Pub/Sub (dependency orchestration)
- **Status:** 🚧 Documentation complete, awaiting implementation
- **Complexity:** 4-way dependency (ML Feature Store waits for ALL 4 upstream)
- **Guides:**
  - Operations: `05-phase4-operations-guide.md`
  - Scheduling: `06-phase4-scheduling-strategy.md` (3 strategies: Cloud Function, Cloud Workflows, Time-based)
  - Troubleshooting: `07-phase4-troubleshooting.md`
  - ML Feature Store Deep-Dive: `08-phase4-ml-feature-store-deepdive.md` ✅

**Phase 5 Processors:**
- **Planned:** 2 services - coordinator + worker (20 instances × 5 threads = 100 concurrent)
- **Prediction Systems:** 5 systems (Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble)
- **Trigger:** Cloud Scheduler (6:15 AM coordinator) + Pub/Sub (worker fanout)
- **Status:** 🚧 Documentation complete, awaiting implementation
- **Complexity:** Highest operational complexity (coordinator-worker pattern, 5 system interfaces)
- **Guides:**
  - Operations: `09-phase5-operations-guide.md` ⭐
  - Scheduling: `10-phase5-scheduling-strategy.md`
  - Troubleshooting: `11-phase5-troubleshooting.md`
  - Worker Deep-Dive: `12-phase5-worker-deepdive.md` 🎯 (model loading, concurrency, 67x optimization)

**Future Processors:**
- **Phase 6:** Publishing (Web app JSON generation)
