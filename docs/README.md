# NBA Props Platform Documentation

**Project:** NBA player props prediction system - 6-phase event-driven data pipeline
**Goal:** 55%+ accuracy on over/under bets
**Current Status:** Phase 1 orchestration deployed, Phase 2 processors operational (Nov 2025)

---

## 🎯 For Humans (Quick Navigation)

**New to the system?** Start here:

1. **📊 System Status** → [SYSTEM_STATUS.md](SYSTEM_STATUS.md) ⭐
   - What's deployed in production today?
   - Phase-by-phase readiness
   - Next steps roadmap (3 min read)

2. **🗺️ Navigation Guide** → [NAVIGATION_GUIDE.md](NAVIGATION_GUIDE.md) ⭐
   - How to find information fast
   - Common scenarios with navigation paths
   - Quick decision tree (2 min read)

3. **🏃 Quick Reference** → [Processor Cards](processor-cards/README.md)
   - 13 processor reference cards
   - Health check queries (copy-paste ready)
   - Common issues and fixes (1-5 min per card)

4. **🚨 Production Issues?** → [Cross-Phase Troubleshooting](operations/cross-phase-troubleshooting-matrix.md)
   - Symptom-based troubleshooting
   - Trace issues backward through pipeline
   - Start here when things break

**Daily Operations:** Run `./bin/orchestration/quick_health_check.sh`

---

## 🤖 For AI Assistants (Start Here!)

**New to this project in a fresh conversation?**

### Step 1: You Already Have Context
Your `.claude/claude_project_instructions.md` has been loaded with:
- Complete architecture overview (6-phase pipeline)
- Technology stack and core principles
- Documentation standards and organization
- Key file locations and commands

### Step 2: Route to Specific Documentation

Use this decision tree to find the right docs for your task:

```
What are you working on?

├─ Phase 1 Orchestration (Scheduler, Cloud Scheduler jobs, workflows)
│  → docs/orchestration/README.md
│  → Start with: 01-how-it-works.md, then 02-phase1-overview.md
│
├─ Phase 2-4 Processors (Data processing operations)
│  → docs/processors/README.md
│  → Start with: 01-phase2-operations-guide.md
│
├─ Phase 5 Predictions (ML prediction system, coordinator-worker)
│  → docs/predictions/README.md
│  → Start with: tutorials/01-getting-started.md ⭐⭐ READ THIS FIRST!
│
├─ Pub/Sub Infrastructure (Cross-phase messaging, event integration)
│  → docs/infrastructure/README.md
│  → Start with: 01-pubsub-integration-verification.md
│
├─ Monitoring & Observability (Grafana, health checks, alerts)
│  → docs/monitoring/README.md
│  → Start with: 02-grafana-daily-health-check.md (quick), then 01 (comprehensive)
│
├─ Data Flow & Mappings (How data transforms between phases)
│  → docs/data-flow/README.md
│  → Status: Placeholder awaiting data mapping documentation
│
├─ System Architecture & Design (Future plans, integration roadmap)
│  → docs/architecture/README.md
│  → Start with: 00-quick-reference.md, then 04-event-driven-pipeline-architecture.md
│
└─ Documentation Organization (Where to put new docs)
   → docs/DOCS_DIRECTORY_STRUCTURE.md (which directory?)
   → docs/DOCUMENTATION_GUIDE.md (how to organize files within directory?)
```

### Step 3: Common Task Quick Links

| Task | Read This First |
|------|----------------|
| **Check system status** | `SYSTEM_STATUS.md` ⭐ |
| **Navigate docs** | `NAVIGATION_GUIDE.md` ⭐ |
| **Quick reference** | `processor-cards/README.md` |
| **Troubleshoot production** | `operations/cross-phase-troubleshooting-matrix.md` |
| Daily health check | `monitoring/02-grafana-daily-health-check.md` |
| Observability gaps | `monitoring/04-observability-gaps-and-improvement-plan.md` |
| Observability quick ref | `monitoring/OBSERVABILITY_QUICK_REFERENCE.md` (one-page checklist) |
| Data completeness validation | `monitoring/05-data-completeness-validation.md` (validation queries) |
| **Alerting & on-call** | `monitoring/06-alerting-strategy-and-escalation.md` ⭐ (severity, escalation, runbooks) |
| **Debug single entity** | `monitoring/07-single-entity-debugging.md` (trace player/team/game) |
| Troubleshoot Phase 1 | `orchestration/04-troubleshooting.md` |
| Troubleshoot Phase 2-4 | `processors/01-phase2-operations-guide.md` (Troubleshooting section) |
| **Run backfills** | `operations/01-backfill-operations-guide.md` ⭐ (step-by-step guide) |
| **Cross-date dependencies** | `architecture/08-cross-date-dependency-management.md` (backfill order) |
| **Learn about Phase 5** | `predictions/tutorials/01-getting-started.md` ⭐⭐ |
| **Deploy Phase 5** | `predictions/operations/01-deployment-guide.md` |
| Verify Pub/Sub working | `infrastructure/01-pubsub-integration-verification.md` |
| Understand architecture | `architecture/00-quick-reference.md` → `architecture/04-event-driven-pipeline-architecture.md` |
| Change detection investigation | `architecture/07-change-detection-current-state-investigation.md` (entity vs date-level) |
| Add new documentation | `DOCS_DIRECTORY_STRUCTURE.md` (where?) + `DOCUMENTATION_GUIDE.md` (how?) |
| Run health check script | `bin/orchestration/quick_health_check.sh` |
| Review BigQuery schemas | `orchestration/03-bigquery-schemas.md` |

### Step 4: Key Principles to Remember

**Documentation:**
- All docs have metadata headers (File, Created, Last Updated, Purpose, Status)
- Use chronological numbering (01-99) within directories
- Always update directory README when adding docs
- Archive old docs, don't delete

**Code Quality:**
- Discovery queries before assumptions
- Always filter BigQuery partitions explicitly
- One small thing at a time with comprehensive testing
- "Show must go on" - graceful degradation

**Season Logic:**
- Oct-Dec dates → current year is season start (2024-12-15 = 2024-25 season)
- Jan-Sep dates → previous year is season start (2025-01-15 = 2024-25 season)

---

## 📁 Documentation Structure

Our documentation is organized into **7 focused directories** (reorganized 2025-11-15):

### `architecture/` - Strategic Design & Planning
**Focus:** System design, future vision, architectural decisions
**Time Horizon:** Present → Future (6-12 months ahead)
**Key Docs:**
- `00-quick-reference.md` - At-a-glance system overview (START HERE - 2-3 min)
- `04-event-driven-pipeline-architecture.md` - Comprehensive architecture (30-45 min)
- `05-implementation-status-and-roadmap.md` - Current status: ~45% complete

**When to read:** Understanding system design, planning new features, architectural decisions

---

### `orchestration/` - Phase 1 Scheduler & Workflows
**Focus:** Phase 1 orchestration system - time-based scheduling
**Scope:** Cloud Scheduler jobs, workflow config, decision engine
**Key Docs:**
- `01-how-it-works.md` - Simple explanation (START HERE - 5-10 min)
- `02-phase1-overview.md` - Architecture and components
- `03-bigquery-schemas.md` - Orchestration table schemas
- `04-troubleshooting.md` - Common issues and fixes

**When to read:** Operating Phase 1 scheduler, troubleshooting workflows, understanding daily execution

**Key Distinction:** Orchestration = time-based (Cloud Scheduler), not event-based (Pub/Sub)

---

### `infrastructure/` - Cross-Phase Shared Services
**Focus:** Infrastructure connecting multiple phases (the "plumbing")
**Scope:** Pub/Sub topics, message schemas, shared services
**Key Docs:**
- `01-pubsub-integration-verification.md` - How to verify Pub/Sub working
- `02-pubsub-schema-management.md` - Message schemas and error prevention

**When to read:** Setting up Pub/Sub, troubleshooting integration, understanding event flow

**Key Distinction:** Infrastructure = shared plumbing used by multiple phases

---

### `processors/` - Data Processor Operations (Phase 2-4)
**Focus:** Operating and troubleshooting data processors
**Scope:** Phase 2-4 processor operations (Phase 2 deployed, Phase 3-4 documented)
**Key Docs:**

**Phase 2 (Deployed):**
- `01-phase2-operations-guide.md` - Phase 2 raw processors (GCS JSON → BigQuery raw tables)

**Phase 3 (Documentation Complete):**
- `02-phase3-operations-guide.md` - Analytics processors (raw → analytics tables)
- `03-phase3-scheduling-strategy.md` - Cloud Scheduler + Pub/Sub configuration
- `04-phase3-troubleshooting.md` - Failure scenarios and recovery

**Phase 4 (Documentation Complete):**
- `05-phase4-operations-guide.md` - Precompute processors (analytics → precompute)
- `06-phase4-scheduling-strategy.md` - Complex dependency management
- `07-phase4-troubleshooting.md` - Failure scenarios and recovery
- `08-phase4-ml-feature-store-deepdive.md` - Most complex processor deep-dive

**Note:** Phase 5 has moved to dedicated `predictions/` directory (see below)

**When to read:** Operating processors, troubleshooting data processing, debugging transformations

**Key Distinction:** Processors = data transformation operations, not infrastructure

---

### `predictions/` - Phase 5 Prediction System ⭐ NEW
**Focus:** ML prediction system - coordinator-worker pattern with 5 prediction models
**Scope:** Phase 5 only (distinct architecture deserves dedicated directory)
**Key Docs:**
- **🌟 `tutorials/01-getting-started.md`** - Complete onboarding guide (START HERE - 30 min)
- `tutorials/02-understanding-prediction-systems.md` - System types and concepts (Educational)
- `tutorials/03-worked-prediction-examples.md` - Step-by-step prediction examples
- `tutorials/04-operations-command-reference.md` - Quick command reference
- `operations/01-deployment-guide.md` - Complete deployment guide (ML models, cost, monitoring)
- `operations/02-scheduling-strategy.md` - Coordinator scheduling and auto-scaling
- `operations/03-troubleshooting.md` - Failure scenarios and recovery procedures
- `operations/04-worker-deepdive.md` - Worker internals, concurrency, performance
- `operations/05-daily-operations-checklist.md` - Daily operational checklist (2 min)
- `operations/06-performance-monitoring.md` - Complete monitoring guide
- `operations/07-weekly-maintenance.md` - Weekly maintenance procedures
- `operations/08-monthly-maintenance.md` - Monthly model retraining
- `operations/09-emergency-procedures.md` - Critical incident response
- `ml-training/01-initial-model-training.md` - XGBoost training from scratch
- `ml-training/02-continuous-retraining.md` - Model improvement and drift detection
- `ml-training/03-feature-development-strategy.md` - Feature engineering philosophy and growth strategy
- `algorithms/01-composite-factor-calculations.md` - Mathematical specifications
- `algorithms/02-confidence-scoring-framework.md` - Confidence scoring logic
- `architecture/01-parallelization-strategy.md` - When and how to parallelize
- `design/01-architectural-decisions.md` - Design rationale and decisions
- `data-sources/01-data-categorization.md` - How Phase 5 uses data
- `data-sources/02-bigquery-schema-reference.md` - BigQuery schema reference (11 tables + 5 views)
- `tutorials/05-testing-and-quality-assurance.md` - Testing & QA guide

**When to read:** Learning Phase 5, deploying predictions, understanding ML models, optimizing performance

**Key Distinction:** Phase 5 = coordinator-worker + ML systems (different from processor pattern)

**Documentation Status:** ✅ 100% Complete (23 docs across 7 categories, ~305KB)

---

### `monitoring/` - Observability & Health Checks
**Focus:** Monitoring, alerting, and health checks across all phases
**Scope:** Grafana dashboards, daily health checks, observability
**Key Docs:**
- `02-grafana-daily-health-check.md` - Quick 6-panel dashboard (START HERE - 2-3 min)
- `01-grafana-monitoring-guide.md` - Comprehensive monitoring queries and insights
- `04-observability-gaps-and-improvement-plan.md` - What visibility exists vs what's missing ⭐ NEW

**When to read:** Daily monitoring, investigating alerts, performance analysis, planning observability improvements

**Key Distinction:** Monitoring = observing the system; Troubleshooting = fixing it (goes in phase dirs)

---

### `operations/` - Operational Procedures
**Focus:** Step-by-step operational guides for running backfills and maintenance
**Scope:** Backfill procedures, data validation, recovery operations
**Key Docs:**
- `01-backfill-operations-guide.md` - Complete backfill procedures (scenarios, validation, recovery)

**When to read:** Running backfills, gap filling, re-processing data, validating completeness

**Key Distinction:** Operations = procedures for running tasks; Monitoring = observing health

---

### `data-flow/` - Data Lineage & Mappings
**Focus:** How data transforms between phases
**Scope:** Field mappings, transformation logic, end-to-end lineage
**Status:** 📋 Placeholder directory awaiting data mapping documentation

**Future Docs:**
- `01-phase1-to-phase2-mapping.md` - Scraper JSON → Raw tables
- `02-phase2-to-phase3-mapping.md` - Raw → Analytics tables
- `03-phase3-to-phase4-mapping.md` - Analytics → Precompute
- `04-phase4-to-phase5-mapping.md` - Precompute → Predictions
- `05-phase5-to-phase6-mapping.md` - Predictions → Web app API
- `99-end-to-end-example.md` - Complete trace through all 6 phases

**When to read:** Debugging missing data, understanding transformations, tracing field lineage

**Key Distinction:** Data flow = what data, how it transforms; Operations = how to run it

---

## 📖 For Human Engineers

### New Developer Onboarding

**Day 1: Understand the System**
1. **Quick Overview** (10 min): `architecture/00-quick-reference.md`
2. **Comprehensive Architecture** (45 min): `architecture/04-event-driven-pipeline-architecture.md`
3. **Current Status** (15 min): `architecture/05-implementation-status-and-roadmap.md`

**Day 2: Learn Operations**
1. **Phase 1 Overview** (10 min): `orchestration/01-how-it-works.md`
2. **Daily Health Check** (5 min): `monitoring/02-grafana-daily-health-check.md`
3. **Run Scripts**: `./bin/orchestration/quick_health_check.sh`

**Week 1: Deep Dive**
- Read all docs in `orchestration/` (Phase 1 details)
- Read all docs in `processors/` (Phase 2 operations)
- Review `monitoring/01-grafana-monitoring-guide.md` (comprehensive monitoring)

---

### Operations Engineer / SRE

**Daily Routine:**
1. **Health Check** (2-3 min): Run `./bin/orchestration/quick_health_check.sh`
2. **Grafana Dashboard** (30 sec): Check 6-panel health dashboard
3. **Review Docs**: `monitoring/02-grafana-daily-health-check.md`

**Troubleshooting:**
- **Phase 1 Issues**: `orchestration/04-troubleshooting.md`
- **Phase 2 Issues**: `processors/01-phase2-operations-guide.md` (Troubleshooting section)
- **Pub/Sub Issues**: `infrastructure/01-pubsub-integration-verification.md`
- **Observability Gaps**: `monitoring/04-observability-gaps-and-improvement-plan.md` (what's visible vs what's not)

**Key Metrics:**
- Workflow execution rate: >95% expected
- Scraper success rate: 97-99% typical
- Phase 2 delivery: 100% expected
- "no_data" status = normal (successful run, no new data)

---

### Product / Leadership

**System Understanding:**
1. **Quick Overview** (3 min): `architecture/00-quick-reference.md`
2. **Current Status** (15 min): `architecture/05-implementation-status-and-roadmap.md`
3. **System Health**: Ask engineer to run daily health check

**Key Takeaways:**
- 6-phase pipeline: Scrapers → Raw → Analytics → Precompute → Predictions → Web App
- Phases 1-2 deployed and operational (Nov 2025)
- Event-driven architecture via Pub/Sub
- ~45% complete (Phases 1, 2, 5 done; Phases 3, 4, 6 planned)

---

## 🛠️ Documentation Maintenance

### Where to Add New Documentation

**Determine directory:** Use `DOCS_DIRECTORY_STRUCTURE.md` decision tree

**Common scenarios:**
- **Phase 1 scheduler changes** → `orchestration/`
- **Phase 2+ processor operations** → `processors/`
- **Pub/Sub infrastructure** → `infrastructure/`
- **Monitoring/Grafana** → `monitoring/`
- **Data mappings** → `data-flow/`
- **Architecture/design** → `architecture/`

**File organization within directory:** Use `DOCUMENTATION_GUIDE.md`
- Chronological numbering (01-99)
- Update directory README with reading order
- Use standard metadata header

### Documentation Standards

**All documentation files must include:**
```markdown
# Document Title

**File:** `docs/category/NN-document-name.md`
**Created:** YYYY-MM-DD HH:MM PST
**Last Updated:** YYYY-MM-DD HH:MM PST
**Purpose:** Brief description
**Status:** Current|Draft|Superseded|Archive
```

**Key principles:**
- Use Pacific Time with explicit timezone (PST/PDT)
- Chronological numbering (creation order, not pedagogical)
- README provides reading order
- Archive old docs to `archive/YYYY-MM-DD/`

---

## 🔄 Recent Changes

**2025-11-15: Major Documentation Reorganization**
- Split mixed `orchestration/` directory into 5 focused directories
- Created `infrastructure/`, `processors/`, `monitoring/`, `data-flow/`
- Updated all cross-references
- Created comprehensive directory READMEs
- See: `MIGRATION-2025-11-15-docs-reorganization.md` for full details

**2025-11-15: Documentation Guides Created**
- `DOCS_DIRECTORY_STRUCTURE.md` - Where to put documentation
- `DOCUMENTATION_GUIDE.md` - How to organize files within directories
- Updated `.claude/claude_project_instructions.md` with new structure

---

## 📞 Quick Help

**"I need to..."**

| Need | Go To |
|------|-------|
| Understand the system | `architecture/00-quick-reference.md` |
| Check system health | `monitoring/02-grafana-daily-health-check.md` OR run `./bin/orchestration/quick_health_check.sh` |
| Troubleshoot Phase 1 | `orchestration/04-troubleshooting.md` |
| Troubleshoot Phase 2 | `processors/01-phase2-operations-guide.md` |
| Verify Pub/Sub working | `infrastructure/01-pubsub-integration-verification.md` |
| Add new documentation | `DOCS_DIRECTORY_STRUCTURE.md` + `DOCUMENTATION_GUIDE.md` |
| See what's deployed | `architecture/05-implementation-status-and-roadmap.md` |
| Understand workflows | `orchestration/01-how-it-works.md` |
| Learn Grafana monitoring | `monitoring/01-grafana-monitoring-guide.md` |

---

## 🎯 Project Quick Facts

**Pipeline Phases:**
1. **Data Collection** (Phase 1) - Scrapers → GCS JSON ✅ Deployed
2. **Raw Processing** (Phase 2) - JSON → BigQuery raw tables ✅ Deployed
3. **Analytics** (Phase 3) - Player/team summaries 🚧 Planned
4. **Precompute** (Phase 4) - Performance aggregates 🚧 Planned
5. **Predictions** (Phase 5) - ML models ✅ Complete (not deployed in pipeline)
6. **Publishing** (Phase 6) - Firestore/JSON for web app 🚧 Planned

**Technology Stack:**
- **Cloud:** BigQuery, Cloud Storage, Cloud Run, Pub/Sub, Cloud Scheduler
- **Languages:** Python (pandas, XGBoost, pytest)
- **Data Sources:** Odds API, NBA.com, Ball Don't Lie, BigDataBall, ESPN

**Key Metrics:**
- 30+ scrapers operational
- 21 Phase 2 processors deployed
- 97-99% success rate typical
- 100% Pub/Sub delivery rate

---

**Last Updated:** 2025-11-15
**Maintained By:** Project documentation standards
**Next Review:** After Phase 3 deployment

---

*This README serves as the master documentation index. Each directory has its own README with detailed guidance. See `DOCS_DIRECTORY_STRUCTURE.md` for the complete organization guide.*
