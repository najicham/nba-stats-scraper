# Phase 5 Predictions Documentation

**Last Updated:** 2025-11-15
**Purpose:** Complete documentation for Phase 5 prediction generation system
**Audience:** Engineers deploying, operating, and understanding the prediction pipeline

---

## 📖 Reading Order (Start Here!)

**New to Phase 5? Read these in order:**

### Getting Started

**0. `tutorials/01-getting-started.md`** ⭐⭐ START HERE FIRST!
- **Purpose:** Complete onboarding guide answering all common questions
- **Contains:** What exists, what's ready, what's needed, quick answers to 5 key questions
- **When to read:** FIRST - before anything else if you're new to Phase 5
- **Status:** ✅ Current

### Operations Guides (Deploy & Run)

**1. `operations/01-deployment-guide.md`**
- **Purpose:** Deploy coordinator and worker services to production
- **Contains:** Cloud Run config, Pub/Sub setup, ML model deployment
- **When to read:** After reading getting started, before deploying Phase 5 for the first time
- **Status:** ✅ Current (Note: Will be enhanced with additional deployment details)

**2. `operations/02-scheduling-strategy.md`**
- **Purpose:** Cloud Scheduler configuration and dependency management
- **Contains:** 6:15 AM trigger, Phase 4 validation, auto-scaling, retry strategy
- **When to read:** After deployment, configuring scheduling
- **Status:** ✅ Current

**3. `operations/03-troubleshooting.md`**
- **Purpose:** Failure scenarios and recovery procedures
- **Contains:** 6 failure scenarios, P0/P1/P2 incident playbooks, health checks
- **When to read:** When things break, or preparing for on-call
- **Status:** ✅ Current

**4. `operations/04-worker-deepdive.md`** 🎯 Advanced
- **Purpose:** Worker internals - model loading, concurrency, performance
- **Contains:** 5 system interfaces, cold start optimization, graceful degradation
- **When to read:** Optimizing performance or debugging worker issues
- **Status:** ✅ Current

---

### Data Sources (Understand the Data)

**5. `data-sources/01-data-categorization.md`** 📊 Important
- **Purpose:** How Phase 5 categorizes and uses data
- **Contains:** 4 data categories (Pre-Game, Real-Time, Game Results, ML Predictions)
- **When to read:** Understanding what data feeds predictions
- **Status:** ✅ Current

---

### Architecture (Understand the Design)

**6. `architecture/01-parallelization-strategy.md`** 🏗️ Strategic
- **Purpose:** When and how to parallelize prediction processing
- **Contains:** Decision framework, 3 patterns, cost analysis, migration path
- **When to read:** Planning infrastructure or optimizing throughput
- **Status:** ✅ Current

---

## 🗂️ Directory Structure

```
docs/predictions/
├── README.md                          # This file - reading guide
│
├── operations/                        # HOW to deploy and run Phase 5
│   ├── 01-deployment-guide.md        # Cloud Run, Pub/Sub, ML models
│   ├── 02-scheduling-strategy.md     # Cloud Scheduler, dependencies, retries
│   ├── 03-troubleshooting.md         # Failure recovery, incident response
│   └── 04-worker-deepdive.md         # Worker internals, performance
│
├── data-sources/                      # WHAT data flows where
│   └── 01-data-categorization.md     # 4 data categories, pipeline timing
│
├── architecture/                      # WHY we built it this way
│   └── 01-parallelization-strategy.md # Parallel processing decisions
│
├── tutorials/                         # LEARN the prediction systems
│   ├── 01-getting-started.md         # Complete onboarding guide ⭐⭐
│   ├── (future) 02-prediction-systems.md
│   └── (future) 03-algorithm-specs.md
│
└── archive/                           # Historical documentation
    └── (archived materials)
```

---

## 🎯 Quick Start

### I'm completely new to Phase 5
1. **READ THIS FIRST:** `tutorials/01-getting-started.md` ⭐⭐
2. Then proceed with relevant guides below

### I want to deploy Phase 5 for the first time
1. Read `tutorials/01-getting-started.md` (answers key questions)
2. Read `operations/01-deployment-guide.md` (deployment steps)
3. Follow deployment checklist
4. Configure scheduler using `operations/02-scheduling-strategy.md`

### I need to troubleshoot a failure
1. Check `operations/03-troubleshooting.md` for failure scenario
2. Follow recovery procedure
3. Use health check queries

### I want to understand the data pipeline
1. Read `data-sources/01-data-categorization.md` for data categories
2. Review `operations/01-deployment-guide.md` for data flow
3. Check Phase 4→5 mapping in `docs/data-flow/13-phase4-to-phase5-feature-consumption.md`

### I want to optimize performance
1. Read `operations/04-worker-deepdive.md` for concurrency patterns
2. Review `architecture/01-parallelization-strategy.md` for scaling options
3. Check cost analysis in deployment guide

---

## 🔑 Key Concepts

### Coordinator-Worker Pattern
- **Coordinator:** Single instance, orchestrates daily predictions (6:15 AM)
- **Workers:** Auto-scale 0-20 instances, process individual players
- **Communication:** Pub/Sub fan-out (450 messages → 20 workers)

### 5 Prediction Systems
1. **Moving Average Baseline:** Simple recent average
2. **Zone Matchup V1:** Shot zones vs opponent defense
3. **Similarity Balanced V1:** Pattern matching historical games
4. **XGBoost V1:** ML model predictions
5. **Meta Ensemble V1:** Weighted combination of all 4

### Data Pipeline Timing
- **11 PM - 6 AM:** Overnight processing (Phase 4 features)
- **6:15 AM:** Coordinator starts, fans out to workers
- **6:15 AM - 6:20 AM:** Workers generate predictions (2-5 min target)
- **Hourly:** Real-time context updates (injury reports, line movement)

### Critical Dependencies
1. **Phase 4:** ml_feature_store_v2 (MUST be ready by 6 AM)
2. **Phase 3:** upcoming_player_game_context (player schedule)
3. **Phase 2:** odds_player_props (betting lines)

---

## 📊 Quick Reference

### Daily Processing Scale
- **Players:** ~450 per day
- **Predictions:** 2,250 (single line) or 11,250 (multi-line)
- **Systems:** 5 per player
- **Duration:** 2-5 minutes
- **Cost:** ~$60/day

### Service Configuration
| Service | Type | Instances | Concurrency | Memory | CPU |
|---------|------|-----------|-------------|--------|-----|
| Coordinator | Cloud Run Job | 1 | 1 | 1Gi | 1 |
| Worker | Cloud Run Service | 0-20 | 5 | 2Gi | 2 |

### Pub/Sub Topics
- `prediction-request` - Work queue (coordinator → workers)
- `prediction-ready` - Completion events (workers → Phase 6)
- `prediction-worker-dlq` - Failed messages

---

## 🔗 Related Documentation

### Upstream Dependencies
- **Phase 4:** `docs/processors/05-phase4-operations-guide.md` - ML Feature Store
- **Phase 3:** `docs/processors/02-phase3-operations-guide.md` - Upcoming game context
- **Phase 2:** `docs/processors/01-phase2-operations-guide.md` - Raw data processing

### Data Flow Mappings
- **Phase 4→5:** `docs/data-flow/13-phase4-to-phase5-feature-consumption.md`

### Infrastructure
- **Pub/Sub:** `docs/infrastructure/` - Event infrastructure setup
- **Monitoring:** `docs/monitoring/01-grafana-monitoring-guide.md`

### Architecture
- **Pipeline:** `docs/architecture/04-event-driven-pipeline-architecture.md`
- **Roadmap:** `docs/architecture/05-implementation-status-and-roadmap.md`

---

## 📝 Adding New Documentation

When adding new Phase 5 documentation:

1. **Determine category:**
   - Operations guide → `operations/`
   - Data mapping → `data-sources/`
   - Strategic design → `architecture/`
   - Learning/tutorial → `tutorials/`

2. **Find next number:**
   ```bash
   ls operations/*.md | tail -1  # Currently at 04, next is 05
   ```

3. **Use standard header:**
   ```markdown
   # Title

   **File:** `docs/predictions/category/##-filename.md`
   **Created:** YYYY-MM-DD
   **Purpose:** Brief description
   **Status:** Current/Draft/Archived
   ```

4. **Update this README** with the new doc in reading order

---

## 🚀 Status

### Current Implementation

**Phase 5 Status:** 🚧 Documentation complete, code implementation in progress

| Component | Status | Notes |
|-----------|--------|-------|
| Coordinator | 🟡 Code exists | Needs Pub/Sub integration |
| Worker | 🟡 Code exists | Needs Cloud Run deployment |
| Pub/Sub Topics | ❌ Not created | Infrastructure setup needed |
| Cloud Scheduler | ❌ Not configured | Trigger setup needed |
| Monitoring | ❌ Not deployed | Grafana dashboards pending |

### Documentation Coverage

| Category | Docs | Status |
|----------|------|--------|
| Tutorials | 1 doc | ✅ Complete (getting started) |
| Operations | 4 docs | ✅ Complete |
| Data Sources | 1 doc | ✅ Complete |
| Architecture | 1 doc | ✅ Complete |

---

## 🎓 Learning Path

### For Operators
1. Start with `operations/01-deployment-guide.md`
2. Learn `operations/03-troubleshooting.md`
3. Understand daily health checks
4. Practice manual operations

### For Developers
1. Read `data-sources/01-data-categorization.md`
2. Study `operations/04-worker-deepdive.md`
3. Review `architecture/01-parallelization-strategy.md`
4. Examine source code in `predictions/`

### For Architects
1. Review `architecture/01-parallelization-strategy.md`
2. Study event-driven pipeline in `docs/architecture/`
3. Understand cost trade-offs
4. Plan future enhancements

---

**Directory Status:** Active
**Documentation Status:** Comprehensive (7 docs, ~200KB)
**Next Steps:** Deploy to production, validate with real data

---

## 💡 Quick Tips

- **Coordinator not starting?** Check Phase 4 dependency validation
- **Workers not scaling?** Verify Pub/Sub push subscription configured
- **Predictions incomplete?** Check worker DLQ for failed messages
- **Slow performance?** Review worker-deepdive for optimization strategies
- **Cost too high?** Check parallelization-strategy for cost analysis

---

**Maintained by:** Platform team
**Last Review:** 2025-11-15
**Next Review:** After Phase 5 production deployment
