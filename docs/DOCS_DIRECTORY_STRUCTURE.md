# Documentation Directory Structure

**Version:** 3.0
**Created:** 2025-11-15
**Last Updated:** 2025-11-22 10:45:00 PST
**Purpose:** Define top-level documentation directory organization
**Audience:** Engineers and AI assistants organizing documentation

---

## Quick Reference

```
docs/
├── deployment/            # Deployment status, history, guides ⭐ NEW
├── reference/             # Quick reference docs (scrapers, processors) ⭐ NEW
├── guides/                # How-to guides (BigQuery, Cloud Run, etc.) ⭐ NEW
├── handoff/               # Session handoff documents ⭐ NEW
├── architecture/          # Design, planning, future vision
├── orchestration/         # Phase 1: Scheduler & daily workflows
├── infrastructure/        # Cross-phase: Pub/Sub, shared services
├── processors/            # Phase 2-4: Data processor operations
├── predictions/           # Phase 5: ML prediction system
├── monitoring/            # Cross-phase: Grafana, observability
├── data-flow/            # Phase-to-phase data mappings
├── DOCUMENTATION_GUIDE.md      # How to organize files WITHIN directories
└── DOCS_DIRECTORY_STRUCTURE.md # This file - what goes WHERE
```

**Related Guide:** See `DOCUMENTATION_GUIDE.md` for file naming and organization within directories

---

## Table of Contents

1. [Directory Purposes](#directory-purposes)
2. [What Goes Where](#what-goes-where)
3. [Decision Tree](#decision-tree)
4. [Migration from Old Structure](#migration-from-old-structure)
5. [Examples](#examples)

---

## Directory Purposes

### `deployment/` - Deployment Status & History ⭐ NEW

**Focus:** Current deployment status, deployment history, and deployment guides

**Time Horizon:** Living document (status) + Historical record (archive)

**Audience:**
- Engineers checking what's deployed
- Operations team during deployments
- Anyone asking "what's the current state?"

**Contains:**
- `00-deployment-status.md` - **Single source of truth** for current deployment state
- `01-deployment-history.md` - Append-only deployment changelog
- `02-rollback-procedures.md` - Rollback guide (when created)
- `guides/` - Permanent deployment guides (monitoring, procedures)
- `archive/2025-11/` - Temporal deployment reports by month

**Does NOT contain:**
- Architecture/design docs (goes in `architecture/`)
- Operations guides for running systems (goes in phase dirs)
- Monitoring procedures (goes in `monitoring/`)

**Status:** ✅ Organized (2025-11-22)

**Key Distinction:** Deployment = what's deployed + when + how; Operations = how to run it daily

---

### `reference/` - Quick Reference Documentation ⭐ NEW

**Focus:** Scannable quick reference docs for system components

**Format:** Condensed, table-based, 1-2 page quick lookups

**Audience:**
- Engineers needing quick facts
- Anyone looking for "what scrapers exist?"
- Quick lookup during development

**Contains:**
- `01-scrapers-reference.md` - All 25 scrapers by data source
- `02-processors-reference.md` - Phase 2 raw processors
- `03-analytics-processors-reference.md` - Phase 3 analytics
- `04-player-registry-reference.md` - Player ID system
- `05-notification-system-reference.md` - Pub/Sub notifications
- `06-shared-utilities-reference.md` - Common utilities
- `README.md` - Index of all references

**Does NOT contain:**
- Operations guides (goes in phase dirs)
- Detailed how-tos (goes in `guides/`)
- Architecture decisions (goes in `architecture/`)

**Status:** ✅ Created (2025-11-21)

**Key Distinction:** Reference = quick facts; Guides = how to do something

---

### `guides/` - How-To Guides ⭐ NEW

**Focus:** Step-by-step instructions for common tasks

**Format:** Task-oriented, actionable guides

**Audience:**
- Engineers learning the system
- Anyone doing a specific task
- New team members onboarding

**Contains:**
- `00-overview.md` - Index of all guides
- `01-processor-development-guide.md` - Building processors
- `02-quick-start-processor.md` - Processor quickstart
- `03-backfill-deployment-guide.md` - Deploying backfills
- `04-schema-change-process.md` - Schema migrations
- `05-processor-documentation-guide.md` - Writing processor docs
- `06-bigquery-best-practices.md` - BigQuery patterns
- `processor-patterns/` - Specific patterns (dependency tracking, etc.)

**Does NOT contain:**
- Reference lookups (goes in `reference/`)
- Deployment status (goes in `deployment/`)
- Phase-specific operations (goes in phase dirs)

**Status:** ✅ Created (2025-11-21)

**Key Distinction:** Guides = how to do X; Reference = quick facts about X

---

### `handoff/` - Session Handoff Documents ⭐ NEW

**Focus:** Session-to-session handoff notes and progress updates

**Format:** Temporal, dated handoff documents

**Audience:**
- AI assistants resuming work
- Engineers reviewing recent progress
- Historical record of development sessions

**Contains:**
- `HANDOFF-YYYY-MM-DD-{topic}.md` - Daily handoff documents
- Session summaries and progress updates
- Work-in-progress status
- Next steps for following sessions

**Does NOT contain:**
- Permanent documentation (goes in appropriate phase dirs)
- Deployment records (goes in `deployment/archive/`)
- Guides or references (goes in `guides/` or `reference/`)

**Status:** ✅ Organized (2025-11-22)

**Key Distinction:** Handoff = temporal progress notes; Other docs = permanent knowledge

---

### `architecture/` - Strategic Design & Planning

**Focus:** System design, future vision, architectural decisions

**Time Horizon:** Present → Future (6-12 months ahead)

**Audience:**
- Engineers planning new features
- Leadership understanding system evolution
- AI assistants designing new components

**Contains:**
- Event-driven pipeline architecture
- Phase 1→5 integration plans
- Implementation roadmaps
- Architecture decision records (ADRs)
- Design patterns and principles

**Does NOT contain:**
- Operational guides (those go in phase-specific dirs)
- Monitoring procedures (goes in `monitoring/`)
- Code examples (goes in phase-specific dirs)

**Status:** ✅ Organized (2025-11-15)

**README:** `architecture/README.md` provides reading order

---

### `orchestration/` - Phase 1 Scheduler & Workflows

**Focus:** Phase 1 orchestration system - how daily workflows are scheduled and executed

**Scope:** ONLY Phase 1 orchestration components:
- Cloud Scheduler jobs (daily-schedule-locker, master-controller-hourly, etc.)
- Workflow configuration (`config/workflows.yaml`)
- Decision engine logic (RUN/SKIP/ABORT)
- BigQuery orchestration tables
- Workflow execution tracking

**Contains:**
- How orchestration works (overview)
- Phase 1 architecture & components
- BigQuery schema reference (orchestration tables)
- Troubleshooting Phase 1 scheduler
- Cloud Scheduler job configuration

**Does NOT contain:**
- Phase 2 processor operations (goes in `processors/`)
- Pub/Sub infrastructure (goes in `infrastructure/`)
- Grafana monitoring (goes in `monitoring/`)

**Status:** ✅ Reorganized (2025-11-15)

**Key Distinction:** "Orchestration" = time-based scheduling of workflows, not event-based processing

---

### `infrastructure/` - Cross-Phase Shared Services

**Focus:** Infrastructure that connects multiple phases - the "plumbing" of the pipeline

**Scope:** Shared infrastructure used by 2+ phases:
- Pub/Sub topics and subscriptions
- Message schemas and formats
- Integration verification guides
- Authentication and service accounts
- Shared BigQuery datasets (if any)
- Cloud Run service configuration

**Contains:**
- Pub/Sub integration verification
- Pub/Sub message schema management
- Cross-phase authentication
- Infrastructure deployment guides
- Service account permissions

**Does NOT contain:**
- Phase-specific operations (goes in phase dirs)
- Monitoring dashboards (goes in `monitoring/`)
- Business logic (goes in phase dirs)

**Status:** 🆕 Created (2025-11-15)

**Key Distinction:** Infrastructure = shared plumbing used by multiple phases

---

### `processors/` - Data Processor Operations (Phase 2-4)

**Focus:** Operating and troubleshooting data processors

**Scope:** Phase 2, 3, 4 processor operations:
- **Phase 2:** Raw data processors (GCS → BigQuery nba_raw)
- **Phase 3:** Analytics processors (nba_raw → nba_analytics)
- **Phase 4:** Precompute processors (nba_analytics → nba_precompute)

**Contains:**
- Phase 2 operations guide (deployed)
- Phase 3 analytics guide (documented)
- Phase 4 precompute guide (documented)
- Processor troubleshooting
- Processor deployment guides

**Does NOT contain:**
- Phase 5 predictions (moved to `predictions/` - see below)
- Pub/Sub infrastructure (goes in `infrastructure/`)
- Scheduler logic (goes in `orchestration/`)
- Monitoring queries (goes in `monitoring/`)

**Status:** ✅ Active (Phase 2 deployed, Phase 3-4 documented)

**Key Distinction:** Processors = standard data transformation pattern

---

### `predictions/` - Phase 5 Prediction System ⭐ NEW

**Focus:** ML prediction system - coordinator-worker pattern with 5 prediction models

**Scope:** Phase 5 ONLY - distinct architecture deserves dedicated directory:
- **Coordinator:** Single instance orchestrator (Cloud Run Job)
- **Worker:** Auto-scaling prediction service (0-20 instances)
- **5 ML Systems:** Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble
- **ML Models:** XGBoost model deployment, training, versioning
- **Cost Management:** $60/day optimization strategies

**Contains:**
- `tutorials/` - Getting started guide (onboarding)
- `operations/` - Deployment, scheduling, troubleshooting, worker deep-dive
- `data-sources/` - How Phase 5 uses data
- `architecture/` - Parallelization strategy, scaling decisions

**Does NOT contain:**
- Phase 2-4 processors (go in `processors/`)
- Upstream data generation (Phase 4 in `processors/`)
- General ML infrastructure (would go in `infrastructure/`)

**Status:** ✅ 100% Complete (7 docs, 247KB)

**Key Distinction:** Phase 5 = coordinator-worker + ML systems (different pattern from standard processors)

**Why separate directory?**
- Distinct architecture (coordinator-worker vs standard processor)
- ML-specific concerns (model deployment, training, versioning)
- Large documentation set (7 comprehensive docs)
- Different operational model (auto-scaling, cost optimization)
- Better discoverability for ML/prediction-focused work

---

### `monitoring/` - Observability & Health Checks

**Focus:** Monitoring, alerting, and observability across all phases

**Scope:** Cross-phase monitoring and health checks:
- Grafana dashboards
- Daily health check procedures
- Alert configuration
- SLO/SLI definitions
- Incident response guides
- Performance monitoring

**Contains:**
- Grafana setup and configuration
- Daily health check guides
- Alert thresholds and escalation
- Dashboard query references
- Monitoring best practices

**Does NOT contain:**
- Phase-specific troubleshooting (goes in phase dirs)
- Infrastructure setup (goes in `infrastructure/`)
- Operational procedures (goes in phase dirs)

**Status:** 🆕 Created (2025-11-15)

**Key Distinction:** Monitoring = observing the system, not operating it

---

### `data-flow/` - Data Lineage & Mappings

**Focus:** How data transforms as it moves through the pipeline

**Scope:** Phase-to-phase data mappings:
- **Phase 1→2:** Scraper outputs (GCS JSON) → Raw tables
- **Phase 2→3:** Raw tables → Analytics tables
- **Phase 3→4:** Analytics → Precompute
- **Phase 4→5:** Precompute → Predictions
- **Phase 5→6:** Predictions → Web app API

**Contains:**
- Field mappings by phase transition
- Data transformation logic
- Schema evolution tracking
- End-to-end data lineage
- Example traces (scraper → API)

**Does NOT contain:**
- Operations guides (goes in phase dirs)
- Architecture decisions (goes in `architecture/`)
- Troubleshooting (goes in phase dirs)

**Status:** 📋 Placeholder (2025-11-15) - awaiting data mapping docs

**Key Distinction:** Data flow = what data, how it transforms; Operations = how to run it

---

## What Goes Where

### Decision Tree

```
I have documentation to add. What is it about?

┌─ System Design & Future Plans
│  └─ architecture/
│     Examples: ADRs, integration plans, roadmaps
│
├─ Phase 1 Scheduler & Workflows
│  └─ orchestration/
│     Examples: Cloud Scheduler jobs, workflow config, decision logic
│
├─ Cross-Phase Infrastructure
│  └─ infrastructure/
│     Examples: Pub/Sub topics, service accounts, shared services
│
├─ Phase 2-4 Processor Operations
│  └─ processors/
│     Examples: Processor guides, troubleshooting, deployment
│
├─ Phase 5 Prediction System
│  └─ predictions/
│     Examples: ML models, coordinator-worker, prediction operations
│
├─ Monitoring & Observability
│  └─ monitoring/
│     Examples: Grafana dashboards, health checks, alerts
│
└─ Data Transformations & Mappings
   └─ data-flow/
      Examples: Field mappings, schema evolution, lineage
```

---

### Specific Examples

| Your Doc Topic | Goes In | Filename Example |
|---------------|---------|------------------|
| How Cloud Scheduler triggers workflows | `orchestration/` | `02-phase1-overview.md` |
| Pub/Sub message format specification | `infrastructure/` | `02-pubsub-schema-management.md` |
| How to run Phase 2-4 processors | `processors/` | `01-phase2-operations-guide.md` |
| **How to deploy Phase 5 predictions** | `predictions/` | `operations/01-deployment-guide.md` |
| **Learning Phase 5 from scratch** | `predictions/` | `tutorials/01-getting-started.md` |
| **XGBoost model deployment** | `predictions/` | `operations/01-deployment-guide.md` |
| Setting up Grafana dashboard | `monitoring/` | `01-grafana-monitoring-guide.md` |
| Daily health check procedure | `monitoring/` | `02-grafana-daily-health-check.md` |
| Field mapping: raw → analytics | `data-flow/` | `02-phase2-to-phase3-mapping.md` |
| Event-driven architecture vision | `architecture/` | `04-event-driven-pipeline-architecture.md` |
| Phase 1→5 integration roadmap | `architecture/` | `01-phase1-to-phase5-integration-plan.md` |
| Troubleshooting Phase 1 scheduler | `orchestration/` | `04-troubleshooting.md` |
| BigQuery orchestration table schemas | `orchestration/` | `03-bigquery-schemas.md` |

---

### Edge Cases

**"My doc spans multiple directories!"**

Examples:
- **Pub/Sub verification that tests Phase 1→2 integration**
  - Goes in: `infrastructure/` (it's about Pub/Sub infrastructure)
  - Cross-reference from: `orchestration/` and `processors/` READMEs

- **Monitoring query that tracks Phase 2 processors**
  - Goes in: `monitoring/` (it's about observability)
  - Cross-reference from: `processors/README.md`

- **Deployment guide for processors that uses Pub/Sub**
  - Goes in: `processors/` (primary purpose is deploying processors)
  - Cross-reference to: `infrastructure/pubsub-*.md`

**Rule of thumb:** Place in the directory that matches the **primary purpose**, then add cross-references.

---

## Migration from Old Structure

### Old Structure (Before 2025-11-15)

```
docs/
├── architecture/          # Design docs (kept as-is)
└── orchestration/         # MIXED: Phase 1, Phase 2, Pub/Sub, Monitoring
    ├── 01-how-it-works.md              # Phase 1 overview
    ├── 02-phase1-overview.md           # Phase 1 architecture
    ├── 03-phase2-operations-guide.md   # Phase 2 processors
    ├── 04-grafana-monitoring-guide.md  # Monitoring
    ├── 05-grafana-daily-health-check-guide.md  # Monitoring
    ├── 06-pubsub-integration-verification-guide.md  # Infrastructure
    ├── 07-pubsub-schema-management.md  # Infrastructure
    ├── 08-phase1-bigquery-schemas.md   # Phase 1
    └── 09-phase1-troubleshooting.md    # Phase 1
```

### New Structure (After 2025-11-15)

```
docs/
├── architecture/          # Kept as-is ✅
│
├── orchestration/         # Phase 1 ONLY
│   ├── 01-how-it-works.md
│   ├── 02-phase1-overview.md
│   ├── 03-bigquery-schemas.md         # Renumbered from 08
│   └── 04-troubleshooting.md          # Renumbered from 09
│
├── infrastructure/        # 🆕 Cross-phase systems
│   ├── 01-pubsub-integration-verification.md
│   └── 02-pubsub-schema-management.md
│
├── processors/            # 🆕 Phase 2+ operations
│   └── 01-phase2-operations-guide.md
│
└── monitoring/            # 🆕 Observability
    ├── 01-grafana-monitoring-guide.md
    └── 02-grafana-daily-health-check.md
```

### Migration Mapping

| Old Location | New Location | Reason |
|-------------|--------------|--------|
| `orchestration/01-how-it-works.md` | `orchestration/01-how-it-works.md` | ✅ Phase 1 overview |
| `orchestration/02-phase1-overview.md` | `orchestration/02-phase1-overview.md` | ✅ Phase 1 architecture |
| `orchestration/08-phase1-bigquery-schemas.md` | `orchestration/03-bigquery-schemas.md` | ✅ Phase 1, renumbered |
| `orchestration/09-phase1-troubleshooting.md` | `orchestration/04-troubleshooting.md` | ✅ Phase 1, renumbered |
| `orchestration/03-phase2-operations-guide.md` | `processors/01-phase2-operations-guide.md` | 📦 Processor operations |
| `orchestration/06-pubsub-integration-verification-guide.md` | `infrastructure/01-pubsub-integration-verification.md` | 🔧 Cross-phase infra |
| `orchestration/07-pubsub-schema-management.md` | `infrastructure/02-pubsub-schema-management.md` | 🔧 Cross-phase infra |
| `orchestration/04-grafana-monitoring-guide.md` | `monitoring/01-grafana-monitoring-guide.md` | 📊 Observability |
| `orchestration/05-grafana-daily-health-check-guide.md` | `monitoring/02-grafana-daily-health-check.md` | 📊 Observability |

---

## Examples

### Example 1: Adding Phase 3 Analytics Documentation

**Scenario:** You've deployed Phase 3 analytics processors and need to document operations.

**Where:** `processors/` directory

**Steps:**
1. Check existing processors docs:
   ```bash
   ls docs/processors/
   # Shows: 01-phase2-operations-guide.md
   ```

2. Create next numbered file:
   ```bash
   # Create: 02-phase3-analytics-guide.md
   ```

3. Use standard metadata:
   ```markdown
   # Phase 3 Analytics Operations Guide

   **File:** `docs/processors/02-phase3-analytics-guide.md`
   **Created:** 2025-11-20 14:30 PST
   **Purpose:** Operations guide for Phase 3 analytics processors
   **Status:** Current
   ```

4. Update `processors/README.md` with reading order

**Why here?** Phase 3 analytics are data processors, same category as Phase 2.

---

### Example 2: Adding Pub/Sub Topic Configuration

**Scenario:** You're documenting how to create new Pub/Sub topics for phase transitions.

**Where:** `infrastructure/` directory

**Steps:**
1. Check existing infrastructure docs:
   ```bash
   ls docs/infrastructure/
   # Shows: 01-pubsub-integration-verification.md
   #        02-pubsub-schema-management.md
   ```

2. Create next numbered file:
   ```bash
   # Create: 03-pubsub-topic-management.md
   ```

**Why here?** Pub/Sub topics are shared infrastructure used across multiple phases.

---

### Example 3: Adding New Monitoring Dashboard

**Scenario:** You've created a Grafana dashboard for Phase 4 precompute monitoring.

**Where:** `monitoring/` directory

**Steps:**
1. Check existing monitoring docs:
   ```bash
   ls docs/monitoring/
   # Shows: 01-grafana-monitoring-guide.md
   #        02-grafana-daily-health-check.md
   ```

2. Decide:
   - If it's a new dashboard type: Create `03-phase4-dashboard.md`
   - If it extends existing guide: Update `01-grafana-monitoring-guide.md`

**Why here?** Grafana dashboards are monitoring/observability tools.

---

### Example 4: Adding Data Mapping Documentation

**Scenario:** You have field mappings showing how Phase 2 raw tables become Phase 3 analytics.

**Where:** `data-flow/` directory

**Steps:**
1. Check if directory exists:
   ```bash
   ls docs/data-flow/ 2>/dev/null || echo "Create it"
   ```

2. Create first mapping doc:
   ```bash
   # Create: 01-phase2-to-phase3-mapping.md
   ```

3. Add comprehensive field mappings:
   ```markdown
   # Phase 2 → Phase 3 Data Mapping

   ## nba_raw.nbac_player_boxscores → nba_analytics.player_game_summary

   | Raw Field | Analytics Field | Transformation |
   |-----------|-----------------|----------------|
   | pts | points | Direct copy |
   | reb | total_rebounds | Direct copy |
   | ...
   ```

**Why here?** Documents how data flows and transforms between phases.

---

## Best Practices

### 1. Keep Directories Focused

**Each directory has ONE clear purpose:**
- ✅ `orchestration/` = Phase 1 scheduler logic
- ✅ `infrastructure/` = Shared cross-phase systems
- ✅ `processors/` = Data processor operations
- ❌ Don't mix monitoring queries into `orchestration/`
- ❌ Don't mix processor ops into `infrastructure/`

### 2. Use Cross-References Liberally

**When docs relate across directories:**

```markdown
# In orchestration/02-phase1-overview.md

## Related Documentation

- **Pub/Sub Integration:** See `infrastructure/01-pubsub-integration-verification.md`
- **Monitoring:** See `monitoring/01-grafana-monitoring-guide.md`
- **Phase 2 Processors:** See `processors/01-phase2-operations-guide.md`
```

### 3. Update READMEs When Adding Docs

**Each directory has a README.md that:**
- Lists docs in reading order (not filename order)
- Explains directory purpose
- Provides "start here" guidance
- Links to related directories

### 4. Archive Old Docs Properly

**When a doc becomes outdated:**

```bash
# Create archive directory
mkdir -p docs/{directory}/archive/2025-11-15/

# Move old doc
mv docs/{directory}/old-doc.md docs/{directory}/archive/2025-11-15/

# Update README to remove reference
```

---

## Directory Structure at a Glance

```
docs/
│
├── architecture/          # Strategic: Design & future vision
│   ├── README.md         # Reading order, "start with 04"
│   ├── 00-quick-reference.md
│   ├── 01-phase1-to-phase5-integration-plan.md
│   ├── 04-event-driven-pipeline-architecture.md  ⭐ START HERE
│   ├── 05-implementation-status-and-roadmap.md
│   └── archive/
│
├── orchestration/         # Tactical: Phase 1 scheduler & workflows
│   ├── README.md
│   ├── 01-how-it-works.md
│   ├── 02-phase1-overview.md
│   ├── 03-bigquery-schemas.md
│   ├── 04-troubleshooting.md
│   └── archive/
│
├── infrastructure/        # Shared: Cross-phase plumbing
│   ├── README.md
│   ├── 01-pubsub-integration-verification.md
│   ├── 02-pubsub-schema-management.md
│   └── archive/
│
├── processors/            # Tactical: Phase 2+ processor operations
│   ├── README.md
│   ├── 01-phase2-operations-guide.md
│   ├── (future) 02-phase3-analytics-guide.md
│   ├── (future) 03-phase4-precompute-guide.md
│   └── archive/
│
├── monitoring/            # Observability: Cross-phase monitoring
│   ├── README.md
│   ├── 01-grafana-monitoring-guide.md
│   ├── 02-grafana-daily-health-check.md
│   └── archive/
│
├── data-flow/            # Reference: Data lineage & mappings
│   ├── README.md         # (to be created)
│   ├── (future) 01-phase1-to-phase2-mapping.md
│   ├── (future) 02-phase2-to-phase3-mapping.md
│   └── 99-end-to-end-example.md
│
└── [Root Guides]
    ├── DOCUMENTATION_GUIDE.md           # File organization WITHIN directories
    ├── DOCS_DIRECTORY_STRUCTURE.md      # THIS FILE - directory organization
    └── README.md                         # Master index
```

---

## Related Documentation

- **File Organization:** See `DOCUMENTATION_GUIDE.md` for numbering, naming, archiving within directories
- **Architecture Overview:** See `architecture/00-quick-reference.md` for system overview
- **Getting Started:** See `README.md` for project overview

---

## Maintenance

**Update this guide when:**
- Adding a new top-level directory (e.g., `docs/api/`)
- Changing directory purposes
- Major reorganization of existing directories
- Learning new patterns from actual usage

**Review schedule:** After organizing 2-3 directories, verify patterns work

---

## Version History

### v2.0 (2025-11-15)
- Major reorganization: Split orchestration into 5 focused directories
- Added `infrastructure/`, `processors/`, `monitoring/`, `data-flow/`
- Refined `orchestration/` to Phase 1 scheduler only
- Created comprehensive decision tree
- Added migration mapping from old structure

### v1.0 (2025-11-15)
- Initial split from `DOCS_ORGANIZATION.md`
- Documented architecture + orchestration directories
- Established directory purpose patterns

---

**Guide Status:** Active
**Next Review:** After adding data-flow mappings
**Maintained By:** Documentation standards

---

*This guide should be consulted when deciding where to place new documentation. Keep it updated as the project evolves.*
