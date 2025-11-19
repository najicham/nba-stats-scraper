# Documentation Navigation Guide

**File:** `docs/NAVIGATION_GUIDE.md`
**Created:** 2025-11-15
**Purpose:** How to navigate the NBA stats pipeline documentation system
**Audience:** Anyone asking "where do I find information about X?"

---

## 🎯 TL;DR - Quick Decision Tree

```
What do you need?

├─ System status / deployment status → docs/SYSTEM_STATUS.md (START HERE!)
│
├─ Quick lookup (1-5 min) → Processor Cards (docs/processor-cards/)
│
├─ Production is broken → Cross-Phase Troubleshooting (docs/operations/)
│
├─ Deep understanding (30+ min) → Detailed Docs (by phase)
│   ├─ Phase 1 → docs/orchestration/
│   ├─ Phase 2-4 → docs/processors/
│   ├─ Phase 5 → docs/predictions/
│   └─ Architecture → docs/architecture/
│
└─ Daily operations → Monitoring Docs (docs/monitoring/)
```

---

## 📚 Documentation Types - When to Use What

### Type 1: System Status (Single Source of Truth)
**File:** `docs/SYSTEM_STATUS.md`

**Use when you need:**
- Current deployment status (what's in production?)
- Phase-by-phase readiness
- Next steps roadmap
- Quick "state of the system" overview

**Time:** 2-3 minutes
**Best for:** Leadership, new team members, status updates

**Example questions:**
- "What's working today?"
- "When will Phase 5 be deployed?"
- "What's the current progress?"

---

### Type 2: Processor Cards (Quick Reference)
**Location:** `docs/processor-cards/`

**Use when you need:**
- Fast facts about a specific processor
- Health check queries (copy-paste ready)
- Common issues and quick fixes
- Performance metrics and benchmarks

**Time:** 1-5 minutes per card
**Best for:** Daily operations, debugging, quick lookups

**What's included:**
- 11 processor cards (5 Phase 3, 5 Phase 4, 1 Phase 5)
- 2 workflow cards (daily timeline + real-time flow)
- All verified against source code

**Example questions:**
- "How many tests does Player Game Summary have?"
- "What's the expected duration for Phase 4?"
- "Quick health check for all processors?"

**Start here:** `docs/processor-cards/README.md`

---

### Type 3: Troubleshooting Guides (When Things Break)
**Location:** `docs/operations/`

**Use when:**
- Production is broken
- Need to diagnose issues
- Tracing problems backward through pipeline

**Time:** 5-30 minutes (diagnosis + fix)
**Best for:** On-call engineers, incident response

**Key documents:**
- **Cross-Phase Troubleshooting Matrix** - Symptom-based (START HERE when broken!)
- Phase-specific troubleshooting (linked from matrix)

**Navigation flow:**
1. Start with Cross-Phase Matrix (symptom → phase)
2. Navigate to phase-specific troubleshooting
3. Reference processor cards for specific issues

**Example questions:**
- "Why are predictions missing?"
- "Phase 4 has low row counts, what's wrong?"
- "All predictions are PASS, is this normal?"

**Start here:** `docs/operations/cross-phase-troubleshooting-matrix.md`

---

### Type 4: Detailed Documentation (Deep Understanding)
**Locations:** Multiple directories by topic

**Use when you need:**
- Complete understanding of a phase
- Implementation details
- Architecture decisions
- Deployment procedures

**Time:** 20-60 minutes per doc
**Best for:** Development, planning, onboarding

**By Phase:**

#### Phase 1: Orchestration
**Location:** `docs/orchestration/`
- How orchestration works (Cloud Scheduler, workflows)
- BigQuery schemas
- Troubleshooting

**Start with:** `docs/orchestration/01-how-it-works.md`

#### Phase 2-4: Processors
**Location:** `docs/processors/`
- Operations guides for each phase
- Scheduling strategies
- Deployment procedures

**Start with:** `docs/processors/01-phase2-operations-guide.md`

#### Phase 5: Predictions
**Location:** `docs/predictions/`
- **Getting started guide** (comprehensive onboarding)
- All 5 prediction models explained
- Deployment guide
- Worker internals

**Start with:** `docs/predictions/tutorials/01-getting-started.md` ⭐

#### Architecture & Design
**Location:** `docs/architecture/`
- System architecture overview
- Event-driven pipeline design
- Implementation roadmap
- Future planning

**Start with:** `docs/architecture/00-quick-reference.md`

---

### Type 5: Monitoring & Operations
**Location:** `docs/monitoring/`

**Use when:**
- Daily health checks
- Setting up Grafana dashboards
- Monitoring queries

**Time:** 2-30 minutes
**Best for:** SRE, daily ops

**Key documents:**
- Daily health check (quick dashboard)
- Comprehensive monitoring guide

**Start with:** `docs/monitoring/02-grafana-daily-health-check.md` (quick start)

---

### Type 6: Infrastructure & Data Flow
**Locations:** `docs/infrastructure/`, `docs/data-flow/`

**Use when:**
- Setting up Pub/Sub
- Understanding data transformations
- Tracing field lineage

**Time:** 15-45 minutes
**Best for:** Integration work, debugging data issues

**Key documents:**
- Pub/Sub integration verification
- Data flow mappings (field-level transformations)

---

## 🛤️ Common Scenarios - Navigation Paths

### Scenario 1: New Developer Onboarding

**Goal:** Understand the system from scratch

**Path (4-6 hours total):**

1. **Quick Overview (10 min)**
   - Read: `docs/SYSTEM_STATUS.md`
   - Read: `docs/architecture/00-quick-reference.md`

2. **Complete Architecture (45 min)**
   - Read: `docs/architecture/04-event-driven-pipeline-architecture.md`

3. **Phase 1 Understanding (30 min)**
   - Read: `docs/orchestration/01-how-it-works.md`
   - Read: `docs/orchestration/02-phase1-overview.md`

4. **Daily Operations (30 min)**
   - Read: `docs/processor-cards/workflow-daily-processing-timeline.md`
   - Read: `docs/monitoring/02-grafana-daily-health-check.md`
   - Run: `./bin/orchestration/quick_health_check.sh`

5. **Hands-on Exploration (2-3 hours)**
   - Browse processor cards: `docs/processor-cards/README.md`
   - Read Phase 5 getting started: `docs/predictions/tutorials/01-getting-started.md`
   - Explore troubleshooting: `docs/operations/cross-phase-troubleshooting-matrix.md`

**Success criteria:** Can explain 6-phase pipeline, run health checks, navigate docs independently

---

### Scenario 2: Production Issue - Predictions Missing

**Goal:** Fix broken predictions ASAP

**Path (5-15 minutes):**

1. **Symptom → Diagnosis (2 min)**
   - Open: `docs/operations/cross-phase-troubleshooting-matrix.md`
   - Go to Section 1.1: "No Predictions Generated Today"
   - Follow diagnostic steps (check coordinator, features, games)

2. **Phase-Specific Troubleshooting (3-5 min)**
   - If Phase 5 issue: `docs/predictions/operations/03-troubleshooting.md`
   - If Phase 4 issue: `docs/processors/07-phase4-troubleshooting.md`

3. **Processor Details (if needed) (5 min)**
   - Phase 5 details: `docs/processor-cards/phase5-prediction-coordinator.md`
   - ML Feature Store: `docs/processor-cards/phase4-ml-feature-store-v2.md`

4. **Apply Fix & Verify**
   - Run fix procedure from troubleshooting doc
   - Verify with health check query

**Success criteria:** Predictions restored, root cause identified

---

### Scenario 3: Daily Health Check

**Goal:** Verify system health (daily routine)

**Path (2-3 minutes):**

1. **Quick Script (30 seconds)**
   ```bash
   ./bin/orchestration/quick_health_check.sh
   ```

2. **If Issues Found (2-3 min)**
   - Open: `docs/monitoring/02-grafana-daily-health-check.md`
   - Run relevant queries from 6-panel dashboard
   - If problems → Go to Scenario 2 (troubleshooting)

3. **Weekly Deep Check (10 min)**
   - Review: `docs/monitoring/01-grafana-monitoring-guide.md`
   - Check all phase health queries

**Success criteria:** All phases healthy, no alerts

---

### Scenario 4: Deploying Phase 3 for First Time

**Goal:** Deploy Phase 3 analytics processors

**Path (2-4 hours):**

1. **Understand What's Being Deployed (30 min)**
   - Read: `docs/SYSTEM_STATUS.md` (Phase 3 section)
   - Read: `docs/processor-cards/README.md` (Phase 3 section)
   - Scan: All 5 Phase 3 processor cards

2. **Operations Guide (45 min)**
   - Read: `docs/processors/02-phase3-operations-guide.md`
   - Read: `docs/processors/03-phase3-scheduling-strategy.md`

3. **Architecture Understanding (30 min)**
   - Read: `docs/architecture/01-phase1-to-phase5-integration-plan.md`
   - Understand Pub/Sub connection from Phase 2 → Phase 3

4. **Deployment (1-2 hours)**
   - Follow deployment steps from operations guide
   - Set up Cloud Scheduler triggers
   - Verify with health checks

5. **Post-Deployment Verification (15 min)**
   - Run health checks from processor cards
   - Monitor for 24 hours
   - Reference troubleshooting if issues

**Success criteria:** Phase 3 processing nightly, health checks passing

---

### Scenario 5: Understanding How Predictions Work

**Goal:** Deep understanding of Phase 5 ML system

**Path (1-2 hours):**

1. **Quick Overview (5 min)**
   - Read: `docs/processor-cards/phase5-prediction-coordinator.md`

2. **Comprehensive Tutorial (30-45 min)**
   - Read: `docs/predictions/tutorials/01-getting-started.md` ⭐
   - Covers: All 5 models, ensemble weighting, confidence scoring

3. **Architecture Deep Dive (30 min)**
   - Read: `docs/predictions/operations/04-worker-deepdive.md`
   - Read: `docs/predictions/architecture/01-parallelization-strategy.md`

4. **Real-Time Flow (15 min)**
   - Read: `docs/processor-cards/workflow-realtime-prediction-flow.md`

5. **Code Exploration (optional) (30+ min)**
   - Explore: `predictions/worker/prediction_systems/`
   - Read: Source code for each model

**Success criteria:** Can explain 5 models, ensemble logic, confidence thresholds

---

### Scenario 6: Planning Next Sprint

**Goal:** Understand implementation roadmap

**Path (45 minutes):**

1. **Current Status (5 min)**
   - Read: `docs/SYSTEM_STATUS.md` (roadmap section)

2. **Detailed Roadmap (30 min)**
   - Read: `docs/architecture/05-implementation-status-and-roadmap.md`
   - Review 8-sprint plan (~73 hours total)

3. **Specific Integration Plans (10 min)**
   - Read: `docs/architecture/01-phase1-to-phase5-integration-plan.md`
   - Focus on relevant sprint

**Success criteria:** Sprint plan clear, dependencies understood

---

### Scenario 7: Debugging Data Quality Issues

**Goal:** Why is feature_quality_score low?

**Path (10-20 minutes):**

1. **Symptom Diagnosis (3 min)**
   - Open: `docs/operations/cross-phase-troubleshooting-matrix.md`
   - Go to Section 1.4: "Low Confidence Predictions"

2. **Trace Backward (5 min)**
   - Check Phase 4 completeness queries
   - Identify which Phase 4 processor has low quality

3. **Processor Details (5 min)**
   - If ML Feature Store: `docs/processor-cards/phase4-ml-feature-store-v2.md`
   - Check quality scoring logic (lines 112-132)

4. **Fix Upstream (5-10 min)**
   - Identify missing Phase 4 processor
   - Run manual trigger or check dependencies

**Success criteria:** Quality score > 85, predictions confident

---

### Scenario 8: Setting Up Monitoring

**Goal:** Create Grafana dashboard for system

**Path (1-2 hours):**

1. **Quick Dashboard (30 min)**
   - Read: `docs/monitoring/02-grafana-daily-health-check.md`
   - Implement 6-panel dashboard
   - Copy-paste queries

2. **Comprehensive Monitoring (1-2 hours)**
   - Read: `docs/monitoring/01-grafana-monitoring-guide.md`
   - Set up all phase-specific queries
   - Configure alerts

3. **Troubleshooting Setup (30 min)**
   - Add quick links to troubleshooting docs
   - Document escalation procedures

**Success criteria:** Dashboard showing all phases, alerts configured

---

## 🔍 Quick Reference - By Question Type

### "What's the current state?"
→ `docs/SYSTEM_STATUS.md`

### "How do I check if X is working?"
→ `docs/processor-cards/` (find relevant card, use health check query)

### "Production is broken, how do I fix it?"
→ `docs/operations/cross-phase-troubleshooting-matrix.md`

### "How does X work?"
→ Phase-specific detailed docs:
- Phase 1: `docs/orchestration/01-how-it-works.md`
- Phase 5: `docs/predictions/tutorials/01-getting-started.md`

### "How do I deploy X?"
→ Operations guides in `docs/processors/` or `docs/predictions/operations/`

### "What's the roadmap?"
→ `docs/architecture/05-implementation-status-and-roadmap.md`

### "What tables does X read/write?"
→ Processor cards have dependencies section

### "What are the performance benchmarks?"
→ Processor cards or `docs/processor-cards/workflow-daily-processing-timeline.md`

### "How do I add new documentation?"
→ `docs/DOCUMENTATION_GUIDE.md` + `docs/DOCS_DIRECTORY_STRUCTURE.md`

---

## 📊 Documentation Map - Visual Overview

```
docs/
├── SYSTEM_STATUS.md ⭐ START HERE
├── NAVIGATION_GUIDE.md (you are here)
│
├── processor-cards/ 🏃 QUICK REFERENCE
│   ├── README.md (13 cards)
│   ├── phase3-*.md (5 cards)
│   ├── phase4-*.md (5 cards)
│   ├── phase5-prediction-coordinator.md
│   └── workflow-*.md (2 cards)
│
├── operations/ 🚨 TROUBLESHOOTING
│   └── cross-phase-troubleshooting-matrix.md
│
├── orchestration/ 📋 PHASE 1
│   ├── 01-how-it-works.md ⭐
│   ├── 02-phase1-overview.md
│   ├── 03-bigquery-schemas.md
│   └── 04-troubleshooting.md
│
├── processors/ 🔧 PHASE 2-4
│   ├── 01-phase2-operations-guide.md
│   ├── 02-phase3-operations-guide.md
│   ├── 03-phase3-scheduling-strategy.md
│   ├── 04-phase3-troubleshooting.md
│   ├── 05-phase4-operations-guide.md
│   ├── 06-phase4-scheduling-strategy.md
│   ├── 07-phase4-troubleshooting.md
│   └── 08-phase4-ml-feature-store-deepdive.md
│
├── predictions/ 🤖 PHASE 5
│   ├── tutorials/ (4 docs)
│   │   ├── 01-getting-started.md ⭐⭐ PHASE 5 START HERE
│   │   ├── 02-understanding-prediction-systems.md
│   │   ├── 03-worked-prediction-examples.md
│   │   └── 04-operations-command-reference.md
│   ├── operations/ (9 docs)
│   │   ├── 01-deployment-guide.md
│   │   ├── 02-scheduling-strategy.md
│   │   ├── 03-troubleshooting.md
│   │   ├── 04-worker-deepdive.md
│   │   ├── 05-daily-operations-checklist.md
│   │   ├── 06-performance-monitoring.md
│   │   ├── 07-weekly-maintenance.md
│   │   ├── 08-monthly-maintenance.md
│   │   └── 09-emergency-procedures.md
│   ├── ml-training/ (2 docs)
│   │   ├── 01-initial-model-training.md
│   │   └── 02-continuous-retraining.md
│   ├── algorithms/ (2 docs)
│   │   ├── 01-composite-factor-calculations.md
│   │   └── 02-confidence-scoring-framework.md
│   ├── architecture/ (1 doc)
│   │   └── 01-parallelization-strategy.md
│   ├── design/ (1 doc)
│   │   └── 01-architectural-decisions.md
│   └── data-sources/ (1 doc)
│       └── 01-data-categorization.md
│
├── monitoring/ 📊 DAILY OPS
│   ├── 01-grafana-monitoring-guide.md
│   └── 02-grafana-daily-health-check.md ⭐ DAILY START HERE
│
├── architecture/ 🏗️ DESIGN
│   ├── 00-quick-reference.md ⭐
│   ├── 01-phase1-to-phase5-integration-plan.md
│   ├── 02-phase1-to-phase5-granular-updates.md
│   ├── 03-pipeline-monitoring-and-error-handling.md
│   ├── 04-event-driven-pipeline-architecture.md ⭐⭐ COMPLETE VISION
│   ├── 05-implementation-status-and-roadmap.md
│   └── 06-change-detection-and-event-granularity.md
│
├── infrastructure/ 🔌 PUB/SUB
│   ├── 01-pubsub-integration-verification.md
│   └── 02-pubsub-schema-management.md
│
└── data-flow/ 📈 TRANSFORMATIONS
    ├── (10 detailed mapping docs)
    └── README.md
```

---

## 💡 Tips for Efficient Navigation

### Tip 1: Use the ⭐ Markers
Documents marked with ⭐ are recommended starting points for that topic.

### Tip 2: Start with Cards, Go Deep When Needed
- Quick question? → Processor card (1-5 min)
- Need details? → Follow link to detailed doc (20-60 min)

### Tip 3: Bookmark These 5 Docs
1. `docs/SYSTEM_STATUS.md` - Current state
2. `docs/processor-cards/README.md` - Quick reference index
3. `docs/operations/cross-phase-troubleshooting-matrix.md` - When broken
4. `docs/monitoring/02-grafana-daily-health-check.md` - Daily checks
5. `docs/predictions/tutorials/01-getting-started.md` - Phase 5 complete guide

### Tip 4: Follow the Cross-References
All docs link to related docs. If you're in the wrong place, follow links to the right doc.

### Tip 5: Use the README Files
Each directory has a README with:
- Reading order
- What belongs in that directory
- Quick navigation

---

## 🎓 Learning Paths by Role

### Data Engineer (Building Processors)
1. System overview → `SYSTEM_STATUS.md`
2. Architecture → `architecture/04-event-driven-pipeline-architecture.md`
3. Phase operations → `processors/02-phase3-operations-guide.md`
4. Processor cards → Browse relevant phase cards
5. Data flow → `data-flow/` (field mappings)

### SRE / Operations Engineer
1. Daily health → `monitoring/02-grafana-daily-health-check.md`
2. Troubleshooting → `operations/cross-phase-troubleshooting-matrix.md`
3. Processor cards → All cards for health checks
4. Phase 1 ops → `orchestration/04-troubleshooting.md`
5. Scripts → `./bin/orchestration/quick_health_check.sh`

### ML Engineer (Phase 5 Focus)
1. Phase 5 overview → `processor-cards/phase5-prediction-coordinator.md`
2. Complete tutorial → `predictions/tutorials/01-getting-started.md` ⭐⭐
3. Worker internals → `predictions/operations/04-worker-deepdive.md`
4. Deployment → `predictions/operations/01-deployment-guide.md`
5. Source code → `predictions/worker/prediction_systems/`

### Product Manager / Leadership
1. System status → `SYSTEM_STATUS.md`
2. Quick overview → `architecture/00-quick-reference.md`
3. Roadmap → `architecture/05-implementation-status-and-roadmap.md`
4. Daily timeline → `processor-cards/workflow-daily-processing-timeline.md`

### New Team Member (Any Role)
1. System status → `SYSTEM_STATUS.md` (10 min)
2. Quick reference → `architecture/00-quick-reference.md` (5 min)
3. Complete architecture → `architecture/04-event-driven-pipeline-architecture.md` (45 min)
4. Daily operations → `orchestration/01-how-it-works.md` (10 min)
5. Role-specific path → Follow relevant path above

---

## 🔄 Documentation Maintenance

### When to Update This Guide
- New documentation directories added
- Major reorganization of docs
- New common scenarios identified
- User feedback on navigation confusion

### Who Maintains This
- Engineering team (collectively)
- Review quarterly or after major doc changes

### Version History
- v1.0 (2025-11-15): Initial navigation guide

---

## ❓ Still Can't Find What You Need?

**Try these steps:**

1. **Search by keyword**
   ```bash
   # From repo root
   grep -r "your keyword" docs/
   ```

2. **Check the main README**
   - `docs/README.md` has directory-by-directory guidance

3. **Ask in team chat**
   - Include: What you're trying to do
   - Include: What docs you've already checked

4. **Improve the docs**
   - If you struggled to find something, others will too
   - Add navigation hints or create new docs
   - Update this navigation guide

---

**Document Version**: 1.0
**Created**: 2025-11-15
**Maintained By**: Engineering team
**Next Review**: After Phase 3 deployment

---

*This navigation guide is the map to the documentation system. Bookmark it!*
