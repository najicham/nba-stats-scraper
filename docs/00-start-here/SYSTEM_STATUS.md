# NBA Stats Pipeline - System Status

**File:** `docs/SYSTEM_STATUS.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-25
**Purpose:** Single source of truth for current deployment status and system roadmap
**Status:** Current
**Audience:** Anyone asking "what's the current state of the system?"

**⚠️ NOTE:** For detailed deployment status and history, see `docs/deployment/00-deployment-status.md`

---

## 🎯 TL;DR - Current State

**Overall Progress:** ~70% Complete
**Production Status:** Phases 1-3 fully operational, Phase 4 schemas deployed, Phase 5 partial
**Next Critical Step:** Update Phase 4 processor code with historical dependency checking (~2-3 hours)

---

## 📊 Phase-by-Phase Status

### Phase 1: Orchestration & Data Collection
**Status:** ✅ **DEPLOYED IN PRODUCTION**
**Deployed:** 2025-11-13
**Last Verified:** 2025-11-15

**What It Does:**
- Schedules and executes 7 workflows daily (5 AM - 11 PM ET)
- Orchestrates 33 scrapers across 5 data sources
- Writes scraped data to Google Cloud Storage (JSON files)

**Infrastructure:**
- ✅ Cloud Scheduler jobs (4 jobs: schedule locker, controller, executor, cleanup)
- ✅ Workflow decision engine (RUN/SKIP/ABORT logic)
- ✅ BigQuery orchestration tables (5 tables in `nba_orchestration` dataset)
- ✅ Error tracking and self-healing cleanup processor

**Key Metrics (Typical Day):**
- 38 workflow executions
- 500+ scraper runs
- 97-99% success rate

**Documentation:**
- ✅ Operations guide: `docs/orchestration/01-how-it-works.md`
- ✅ Architecture: `docs/orchestration/02-phase1-overview.md`
- ✅ Troubleshooting: `docs/orchestration/04-troubleshooting.md`
- ✅ Processor card: Part of workflow cards (`docs/processor-cards/workflow-*.md`)

**Health Check:** `./bin/orchestration/quick_health_check.sh`

---

### Phase 2: Raw Data Processing
**Status:** ✅ **DEPLOYED IN PRODUCTION** with Smart Idempotency
**Deployed:** 2025-11-20 (Smart Idempotency), Fixed: 2025-11-21 17:47
**Last Verified:** 2025-11-22

**What It Does:**
- Receives Pub/Sub messages from Phase 1 scrapers
- Processes GCS JSON files → BigQuery raw tables
- 25 processors handling different data types
- Smart idempotency: Skips writes when data hash unchanged (30-60% reduction)

**Infrastructure:**
- ✅ Pub/Sub topics and subscriptions (Phase 1 → Phase 2)
- ✅ Cloud Run processors (25 processors deployed)
- ✅ BigQuery raw dataset (`nba_raw` with 25 tables)
- ✅ Dead Letter Queue (DLQ) for failed messages
- ✅ All tables with `data_hash` columns
- ✅ SmartIdempotencyMixin pattern deployed

**Smart Patterns Active:**
- ✅ **Smart Idempotency (Pattern #14):** Compute SHA256 hash of output data, skip BigQuery write if hash unchanged
- **Expected skip rate:** 30-60%
- **Cost reduction:** 30-50%

**Key Metrics:**
- 100% Pub/Sub delivery rate
- Sub-second processing latency
- Automatic retry on failures

**Documentation:**
- ✅ Operations guide: `docs/processors/01-phase2-operations-guide.md`
- ✅ Reference: `docs/reference/02-processors-reference.md`
- ✅ Pub/Sub verification: `docs/infrastructure/01-pubsub-integration-verification.md`

**Health Check:** Query `nba_raw` tables for recent data

**Recent Changes:**
- **2025-11-21 17:47:** Fixed critical syntax error in SmartIdempotencyMixin
- **2025-11-20:** Deployed smart idempotency to all 25 processors

**Known Gaps:**
- ⏳ Phase 2 → Phase 3 Pub/Sub publishing (ready to connect)

---

### Phase 3: Analytics Processing
**Status:** ✅ **DEPLOYED IN PRODUCTION** with Smart Reprocessing
**Deployed:** 2025-11-18 (Processors), 2025-11-21 (Schemas verified)
**Last Verified:** 2025-11-22

**What It Does:**
- Transforms raw data → analytics tables (player/team summaries)
- Creates forward-looking context for predictions (fatigue, streaks, betting lines)
- 5 processors with comprehensive test coverage
- Smart reprocessing: Skips processing when source hashes unchanged (30-50% reduction)

**Processors:**
| Processor | Sources | Fields | Hash Columns | Status |
|-----------|---------|--------|--------------|--------|
| Player Game Summary | 6 | 72 | 6 | ✅ Deployed |
| Team Offense Summary | 2 | 47 | 2 | ✅ Deployed |
| Team Defense Summary | 3 | 54 | 3 | ✅ Deployed |
| Upcoming Player Context | 4 | 64 | 4 | ✅ Deployed |
| Upcoming Team Context | 3 | 40 | 3 | ✅ Deployed |

**Infrastructure:**
- ✅ Cloud Run processors (5 processors deployed)
- ✅ BigQuery analytics dataset (`nba_analytics` with 5 tables)
- ✅ All schemas with dependency tracking (4 fields per source)
- ✅ All schemas with source `data_hash` columns
- ✅ Pub/Sub infrastructure ready (Phase 2 → Phase 3)

**Smart Patterns Active:**
- ✅ **Dependency Tracking (v4.0):** Track 4 fields per source (last_updated, rows_found, completeness_pct, data_hash)
- ✅ **Smart Reprocessing:** Compare current vs. previous source hashes, skip if unchanged
- ✅ **Backfill Detection:** Find games with Phase 2 data but no Phase 3 analytics
- **Expected skip rate:** 30-50%

**Documentation:**
- ✅ Processor cards: `docs/processor-cards/phase3-*.md` (5 cards)
- ✅ Reference: `docs/reference/03-analytics-processors-reference.md`
- ✅ Operations guide: `docs/processors/02-phase3-operations-guide.md`
- ✅ Scheduling strategy: `docs/processors/03-phase3-scheduling-strategy.md`
- ✅ Troubleshooting: `docs/processors/04-phase3-troubleshooting.md`
- ✅ Monitoring: `docs/deployment/guides/phase3-monitoring.md`
- ✅ Data flow mappings: `docs/data-flow/` (5 detailed mapping docs)

**Recent Changes:**
- **2025-11-21:** Verified all schemas have hash columns deployed

**Next Steps:**
- Connect Phase 2 → Phase 3 Pub/Sub publishing
- Monitor skip rates after connection

---

### Phase 4: Precompute & Feature Engineering
**Status:** ⏳ **SCHEMAS DEPLOYED** - Processor Code Updates Needed
**Deployed:** 2025-11-22 08:43 (Schemas)
**Last Verified:** 2025-11-22

**What It Does:**
- Pre-aggregates expensive calculations (zone analysis, composite factors)
- Creates ML feature store for Phase 5 predictions
- Runs nightly (11 PM - 12 AM) to prepare data for next day
- 4 processors optimized for performance with historical dependency checking

**Processors:**
| Processor | Source Tables | Hash Columns | Historical Deps | Status |
|-----------|---------------|--------------|----------------|--------|
| Team Defense Zone Analysis | 1 (P3) | 2 | ✅ Complete | ⏳ Code update |
| Player Shot Zone Analysis | 1 (P3) | 2 | ✅ Complete | ⏳ Code update |
| Player Composite Factors | 3 (P3+P4) | 4 | ✅ Complete | ⏳ Code update |
| Player Daily Cache | 1 (P3) | 1 | ✅ Complete | ⏳ Code update |

**Infrastructure:**
- ✅ BigQuery schemas deployed (2025-11-22)
- ✅ BigQuery precompute dataset (`nba_precompute` with 4 tables)
- ✅ All schemas with source hash columns
- ✅ Historical dependency tracking implemented
- ❌ Cloud Run deployment (needs code updates)
- ❌ Phase 3 → Phase 4 Pub/Sub topics (pending deployment)
- ❌ Nightly scheduler setup (11 PM - 12 AM)

**Smart Patterns Implemented:**
- ✅ **Historical Dependency Checking:** Check for required historical data (last N games), early exit if insufficient
- ✅ **Phase 4 Dependency Tracking (v4.0 - Streamlined):** Track 3 fields per source (last_updated, rows_found, completeness_pct)
- Note: No data_hash for historical range queries (by design)

**Documentation:**
- ✅ Processor cards: `docs/processor-cards/phase4-*.md` (4 cards)
- ✅ Operations guide: `docs/processors/05-phase4-operations-guide.md`
- ✅ Scheduling strategy: `docs/processors/06-phase4-scheduling-strategy.md`
- ✅ Troubleshooting: `docs/processors/07-phase4-troubleshooting.md`
- ✅ ML Feature Store deep dive: `docs/processors/08-phase4-ml-feature-store-deepdive.md`
- ✅ Data flow mappings: `docs/data-flow/` (5 detailed mapping docs)

**Recent Changes:**
- **2025-11-22 08:43:** All 4 Phase 4 schemas deployed with hash columns
- **2025-11-22 09:02:** Historical dependency checking implementation complete

**Next Steps:**
1. Update processor code with historical dependency methods
2. Deploy to Cloud Run (estimated 2-3 hours)
3. Create Pub/Sub topics for Phase 3 → Phase 4
4. Test with single game before full deployment
5. Set up nightly scheduler (11 PM - 12 AM)

**Dependencies:**
- Requires: Phase 3 fully operational ✅
- Execution order: P1, P2 parallel → P3 (depends on P1+P2) → P4 parallel (depends on P3)

---

### Phase 5: Predictions & ML Models
**Status:** ❌ **NOT DEPLOYED** - ml_feature_store_v2 Schema Ready
**Code Completeness:** 100%
**Documentation:** ✅ Complete (23 docs)

**What It Does:**
- Generates player points predictions using 5 ML models
- Coordinator-worker architecture for scalability
- Real-time prediction updates when odds change
- Confidence scoring and edge calculation

**Models Implemented:**
| Model | Status | Description |
|-------|--------|-------------|
| Moving Average Baseline | ✅ Complete | Simple, reliable baseline |
| XGBoost V1 | ⚠️ Mock model | Code ready, needs trained model |
| Zone Matchup V1 | ✅ Complete | Shot zone analysis predictions |
| Similarity Balanced V1 | ✅ Complete | Pattern matching similar players |
| Ensemble V1 | ✅ Complete | Confidence-weighted combination |

**Infrastructure:**
- ✅ Code: `predictions/` directory (22 Python files, ~3,500 lines)
- ✅ Tests: Comprehensive test coverage
- ✅ ml_feature_store_v2 schema deployed (2025-11-22 08:43)
- ✅ Schema includes `data_hash` column
- ✅ Schema ready for Phase 4 → Phase 5 integration
- ❌ Deployment: Not deployed to Cloud Run
- ❌ Integration: Not connected to Phase 4
- ❌ Trained models: XGBoost needs real model (currently using mock)
- ❌ Pub/Sub topics: Not created (Phase 4 → Phase 5)

**Documentation:**
- ✅ **Tutorials (4 docs):**
  - `tutorials/01-getting-started.md` ⭐ - Complete onboarding
  - `tutorials/02-understanding-prediction-systems.md` - System types and concepts
  - `tutorials/03-worked-prediction-examples.md` - Step-by-step examples
  - `tutorials/04-operations-command-reference.md` - Quick command reference
- ✅ **Operations (9 docs):**
  - `operations/01-deployment-guide.md` - Complete deployment guide
  - `operations/02-scheduling-strategy.md` - Coordinator scheduling
  - `operations/03-troubleshooting.md` - Failure scenarios
  - `operations/04-worker-deepdive.md` - Worker internals
  - `operations/05-daily-operations-checklist.md` - Daily checklist (2 min)
  - `operations/06-performance-monitoring.md` - Monitoring guide
  - `operations/07-weekly-maintenance.md` - Weekly review
  - `operations/08-monthly-maintenance.md` - Model retraining
  - `operations/09-emergency-procedures.md` - Critical incidents
- ✅ **ML Training (3 docs):**
  - `ml-training/01-initial-model-training.md` - XGBoost training
  - `ml-training/02-continuous-retraining.md` - Drift detection & A/B testing
  - `ml-training/03-feature-development-strategy.md` - Feature engineering philosophy
- ✅ **Algorithms (2 docs):**
  - `algorithms/01-composite-factor-calculations.md` - Math specifications
  - `algorithms/02-confidence-scoring-framework.md` - Confidence logic
- ✅ **Architecture (1 doc):**
  - `architecture/01-parallelization-strategy.md` - Scaling patterns
- ✅ **Design (1 doc):**
  - `design/01-architectural-decisions.md` - Design rationale
- ✅ **Data Sources (1 doc):**
  - `data-sources/01-data-categorization.md` - Data pipeline

**Documentation Status:** ✅ **100% Complete (23 docs across 7 categories)**

**Documentation Gaps:**
- ❌ No Phase 5 processor card (to match Phase 3/4 style)

**Recent Changes:**
- **2025-11-22 08:43:** ml_feature_store_v2 schema deployed with data_hash column

**Deployment Needs:**
1. Train XGBoost model with real data (~4 hours)
2. Deploy coordinator and worker services to Cloud Run (~3 hours)
3. Create Pub/Sub topics for Phase 4 → Phase 5 (~2 hours)
4. Set up monitoring and alerts (~2 hours)
5. Create Phase 5 processor card (~2 hours)

**Next Steps:**
- Requires Phase 4 processors deployed first
- Then Phase 5 deployment: Sprint 6 (~13 hours)

**Estimated Deployment Time:** Sprint 6 (~13 hours after Phase 4 deployed)

---

### Phase 6: Publishing & Web API
**Status:** ❌ **NOT STARTED**
**Code Completeness:** 0%
**Documentation:** Not started

**What It Does (Planned):**
- Publishes predictions to Firestore for web app
- Provides REST API for frontend
- Real-time updates when predictions change

**Infrastructure Needed:**
- Everything (Sprint 7-8: ~16 hours)

**Dependencies:**
- Requires: Phase 5 fully operational

**Documentation Needed:**
- Operations guide
- API schema
- Deployment guide

**Estimated Start:** After Sprint 6 (Phase 5 deployment)

---

## 🗺️ Roadmap - Next Steps

### Current Sprint: Phase 4 Processor Deployment
**Goal:** Deploy Phase 4 precompute processors to Cloud Run

**Status:** ⏳ In Progress

**Tasks:**
1. ✅ Deploy Phase 4 schemas to BigQuery (COMPLETE - 2025-11-22)
2. ✅ Implement historical dependency checking (COMPLETE - 2025-11-22)
3. ⏳ Update processor code with historical dependency methods (~1 hour)
4. ⏳ Deploy to Cloud Run (~2-3 hours)
5. ⏳ Test with single game before full deployment (~1 hour)

**Value:** Enables ML feature store for Phase 5 predictions

---

### Next Sprint: Phase 2→3 Integration
**Goal:** Enable Phase 2 → Phase 3 automatic triggering

**Tasks:**
1. Implement Phase 2 Pub/Sub publishing (~2 hours)
2. Connect to existing Phase 3 processors (~1 hour)
3. Verify end-to-end Phase 1 → Phase 2 → Phase 3 flow (~1 hour)

**Value:** Enables automatic analytics updates, unblocks nightly processing pipeline

**Dependencies:** None (Phase 3 already deployed)

---

### Week 1-2: Observability (Sprint 2)
**Goal:** Add correlation ID tracking for end-to-end debugging

**Tasks:**
1. Implement correlation ID flow through all phases (~6 hours)
2. Create unified pipeline execution log (~3 hours)
3. Build Grafana queries for pipeline health (~2 hours)

**Value:** Critical for debugging multi-phase issues

**Status:** Ready to start after Sprint 1

---

### Future Sprint: Phase 3→4 Integration
**Goal:** Enable Phase 3 → Phase 4 automatic triggering

**Status:** Waiting for Phase 4 processor deployment

**Tasks:**
1. Create Phase 3 → Phase 4 Pub/Sub topics (~2 hours)
2. Connect Phase 3 processors to publish events (~1 hour)
3. Set up nightly scheduler (11 PM - 12 AM) (~2 hours)
4. Verify end-to-end flow (~1 hour)

**Value:** Enables nightly precompute and ML feature store updates

**Dependencies:** Phase 4 processors deployed

---

### Week 3-4: Phase 5 Integration (Sprint 6)
**Goal:** Deploy prediction system in pipeline

**Tasks:**
1. Train XGBoost model (~4 hours)
2. Deploy Phase 5 coordinator + workers (~3 hours)
3. Connect Phase 4 → Phase 5 (~2 hours)
4. Set up monitoring (~2 hours)
5. Create Phase 5 processor card (~2 hours)

**Value:** End-to-end predictions pipeline operational

**Dependencies:** Sprint 3 complete

---

### Month 2+: Phase 6 Publishing (Sprint 7-8)
**Goal:** Expose predictions to web app

**Tasks:**
1. Design API schema (~4 hours)
2. Implement publishing service (~8 hours)
3. Deploy and test (~4 hours)

**Value:** Makes predictions accessible to users

**Dependencies:** Sprint 6 complete

---

## 📈 Success Metrics

### Current Metrics (Phase 1-3 Operational)
- ✅ 97-99% scraper success rate (Phase 1)
- ✅ 100% Pub/Sub delivery rate (Phase 1→2)
- ✅ Sub-second Phase 2 processing latency
- ✅ Phase 2 smart idempotency: 30-60% expected skip rate
- ✅ Phase 3 processors deployed and ready
- ✅ Phase 3 smart reprocessing: 30-50% expected skip rate
- ✅ Phase 4 schemas deployed (2025-11-22)

### Target Metrics (Phase 3-5 Deployed)
- 🎯 End-to-end pipeline: Scraper → Prediction in <30 minutes
- 🎯 Phase 3 processing: <15 minutes nightly
- 🎯 Phase 4 processing: <30 minutes nightly (11 PM - 11:30 PM)
- 🎯 Phase 5 predictions: <1 second per odds update
- 🎯 55%+ prediction accuracy on over/under bets

---

## 🔧 Operational Status

### Currently Operational ✅
- Phase 1 orchestration (automated daily execution)
- Phase 2 raw processing (Pub/Sub event-driven) with smart idempotency
- Phase 3 analytics processing (deployed, ready for Pub/Sub connection)
- Health check scripts (`./bin/orchestration/*.sh`)
- Grafana monitoring dashboard (basic)

### Ready to Deploy ⚠️
- Phase 4 precompute processors (schemas deployed, code needs updates)
- Phase 5 prediction models (ml_feature_store_v2 deployed, needs Cloud Run deployment)

### In Progress 🔄
- Phase 4 processor code updates (historical dependency methods)
- Phase 2→3 Pub/Sub integration planning

### Not Yet Started ❌
- Phase 6 publishing
- Phase 3→4 Pub/Sub topics
- Phase 4→5 Pub/Sub topics
- Advanced monitoring (correlation IDs, unified logs)
- Entity-level granularity (performance optimization)

---

## 📚 Documentation Status

### Complete ✅
- **Phase 1:** 4 docs in `docs/orchestration/`
- **Phase 2:** Operations guide + reference + Pub/Sub docs
- **Phase 3:** 5 processor cards + reference + 4 operations docs + monitoring guide
- **Phase 4:** 4 processor cards + 4 operations docs
- **Phase 5:** 23 comprehensive docs across 7 categories
- **Reference:** 6 reference docs (scrapers, processors, analytics, player registry, notifications, utilities)
- **Guides:** BigQuery best practices, schema changes, backfill deployment, processor documentation
- **Operations:** Cloud Run args, cross-phase troubleshooting
- **Deployment:** Consolidated status, history, monitoring guide
- **Workflows:** 2 workflow cards
- **Monitoring:** 2 Grafana guides

### Recent Documentation Updates (2025-11-21 to 2025-11-22)
- ✅ Created 13 condensed reference and guide documents
- ✅ Organized deployment documentation into structured directory
- ✅ Created deployment status and history documents
- ✅ Added BigQuery best practices and Cloud Run args guides

### Gaps 🎯
- No Phase 5 processor card (to match Phase 3/4 style)

---

## 🚀 Quick Links

### For Daily Operations
- **Health check:** Run `./bin/orchestration/quick_health_check.sh`
- **Monitoring:** `docs/monitoring/02-grafana-daily-health-check.md`
- **Deployment status:** `docs/deployment/00-deployment-status.md` ⭐
- **Troubleshooting Phase 1:** `docs/orchestration/04-troubleshooting.md`
- **Troubleshooting Phase 2:** `docs/processors/01-phase2-operations-guide.md`
- **Troubleshooting Phase 3:** `docs/deployment/guides/phase3-monitoring.md`

### For Understanding the System
- **Quick overview:** `docs/architecture/00-quick-reference.md` (2-3 min)
- **Complete architecture:** `docs/architecture/04-event-driven-pipeline-architecture.md` (30-45 min)
- **Processor cards:** `docs/processor-cards/README.md`
- **Reference docs:** `docs/reference/README.md`
- **Phase 5 getting started:** `docs/predictions/tutorials/01-getting-started.md`

### For Development
- **Deployment status:** `docs/deployment/00-deployment-status.md` ⭐
- **Deployment history:** `docs/deployment/01-deployment-history.md`
- **BigQuery best practices:** `docs/guides/06-bigquery-best-practices.md`
- **Cloud Run args:** `docs/operations/03-cloud-run-jobs-arguments.md`
- **Integration guide:** `docs/architecture/01-phase1-to-phase5-integration-plan.md`

---

## ❓ Frequently Asked Questions

### "What's working in production today?"
Phases 1-3 are fully operational. We scrape data daily, process it into BigQuery raw tables with smart idempotency, and have analytics processors ready for connection.

### "When will predictions be live?"
Estimated timeline:
1. Phase 4 processor deployment: 2-3 hours
2. Phase 2→3 Pub/Sub connection: 4 hours
3. Phase 3→4 integration: 6 hours
4. Phase 5 deployment: 13 hours after Phase 4
Total: ~4-5 weeks after starting Phase 4 deployment

### "What's the current priority?"
Phase 4 processor code updates (historical dependency methods) - estimated 2-3 hours to complete and deploy.

### "What's the biggest risk?"
XGBoost model training for Phase 5. Currently using mock model. Need real trained model (~4 hours work).

### "Can I use the system for development?"
Yes! Phase 1-3 data is live. Phase 4-5 code is ready to run locally for testing.

---

## 📞 Getting Help

### For System Status Questions
- Read this document first (you are here!)
- Check roadmap section for timeline
- Review phase-specific status above

### For Operations Issues
- Phase 1: `docs/orchestration/04-troubleshooting.md`
- Phase 2: `docs/processors/01-phase2-operations-guide.md`
- Cross-phase: `docs/operations/cross-phase-troubleshooting-matrix.md`

### For Development Questions
- Architecture: `docs/architecture/README.md`
- Processors: `docs/processor-cards/README.md`
- Phase 5: `docs/predictions/tutorials/01-getting-started.md`

---

**Document Version:** 2.0
**Last System Verification:** 2025-11-22 10:20:00 PST (Phase 1-3 operational, Phase 4 schemas deployed)
**Next Review:** After Phase 4 processor deployment
**Maintained By:** Engineering team
**Update Frequency:** After each major deployment

---

*This is the single source of truth for system status. For detailed deployment information, see `docs/deployment/00-deployment-status.md`*
