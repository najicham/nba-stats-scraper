# Orchestration Documentation

**Last Updated:** 2025-11-15
**Purpose:** Phase 1 orchestration system - scheduler, workflows, and daily operations
**Audience:** Engineers operating and troubleshooting the Phase 1 orchestration system

---

## 📖 Reading Order (Start Here!)

**New to Phase 1 orchestration? Read these in order:**

### 1. **01-how-it-works.md** ⭐ START HERE
   - **Created:** 2025-11-11 20:02 PST
   - **Simple explanation of orchestration deployment and operation**
   - **Why read this:** Get the big picture of how Phase 1 scheduler works (5-10 min read)
   - **Status:** Current

### 2. **02-phase1-overview.md**
   - **Created:** 2025-11-13 10:06 PST
   - **Phase 1 architecture overview and deployment status**
   - **Why read this:** Learn Phase 1 system components: scheduler, workflows, decision engine
   - **Status:** Production Deployed

### 3. **03-bigquery-schemas.md**
   - **Created:** 2025-11-13 10:06 PST
   - **BigQuery table schemas for Phase 1 orchestration**
   - **Why read this:** Understand orchestration tables (daily_expected_schedule, workflow_decisions, etc.)
   - **Status:** Production reference

### 4. **04-troubleshooting.md**
   - **Created:** 2025-11-13 10:06 PST
   - **Manual operations and troubleshooting procedures**
   - **Why read this:** Fix common Phase 1 issues, manual workflow triggers
   - **Status:** Current

---

## 🗂️ What Goes in This Directory

**Orchestration** = Phase 1 scheduler, workflows, and time-based execution

**Belongs here:**
- ✅ Cloud Scheduler jobs (daily-schedule-locker, master-controller-hourly, etc.)
- ✅ Workflow configuration (`config/workflows.yaml`)
- ✅ Decision engine logic (RUN/SKIP/ABORT)
- ✅ BigQuery orchestration tables (daily_expected_schedule, workflow_decisions, etc.)
- ✅ Workflow execution tracking
- ✅ Phase 1 troubleshooting

**Does NOT belong here:**
- ❌ Phase 2 processor operations → See `docs/processors/`
- ❌ Pub/Sub infrastructure → See `docs/infrastructure/`
- ❌ Grafana monitoring → See `docs/monitoring/`
- ❌ Data mappings → See `docs/data-flow/`

**Key distinction:** Orchestration = time-based scheduling (Cloud Scheduler), not event-based processing (Pub/Sub)

---

## 🔗 Related Documentation

**Moved to Other Directories (2025-11-15 Reorganization):**

These docs were previously in `orchestration/` but have been moved to focused directories:

**Infrastructure (Cross-Phase Pub/Sub):**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub testing
- `docs/infrastructure/02-pubsub-schema-management.md` - Message schemas

**Processors (Phase 2+ Operations):**
- `docs/processors/01-phase2-operations-guide.md` - Phase 2 processor operations

**Monitoring (Observability):**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `docs/monitoring/02-grafana-daily-health-check.md` - Quick daily health check

**System Design:**
- `docs/architecture/` - Overall pipeline architecture
- `docs/data-flow/` - Data transformation mappings (future)

---

## 📋 Phase 1 System Components

### Cloud Scheduler Jobs
1. **daily-schedule-locker** (5:00 AM ET)
   - Locks expected schedule for the day
   - Writes to `daily_expected_schedule` table

2. **master-controller-hourly** (6:00 AM - 11:00 PM, hourly)
   - Evaluates workflows (RUN/SKIP/ABORT decisions)
   - Writes to `workflow_decisions` table

3. **workflow-executor** (5 min after controller, hourly)
   - Executes scrapers for RUN decisions
   - Writes to `workflow_executions` table

4. **cleanup-processor** (15 min after executor, hourly)
   - Self-healing for missed Pub/Sub messages
   - Writes to `cleanup_operations` table

### BigQuery Tables (nba_orchestration dataset)
- `daily_expected_schedule` - Expected workflows for the day
- `workflow_decisions` - RUN/SKIP/ABORT decisions
- `workflow_executions` - Execution results
- `scraper_execution_log` - Individual scraper runs
- `cleanup_operations` - Self-healing operations

### Key Scripts
- `./bin/orchestration/quick_health_check.sh` - Daily health check (START HERE)
- `./bin/orchestration/check_system_status.sh` - Detailed system status
- See `bin/orchestration/README.md` for full script reference

---

## 📝 Adding New Documentation

**To add Phase 1 orchestration documentation:**

1. **Verify it's Phase 1** - Is this about scheduler/workflows?
   - If it's about processors → `docs/processors/`
   - If it's about Pub/Sub → `docs/infrastructure/`
   - If it's about monitoring → `docs/monitoring/`

2. **Find next number:** `ls *.md | tail -1` → Currently at 04, next is 05

3. **Create file:** `05-new-orchestration-doc.md`

4. **Use standard metadata header**

5. **Update this README** with the new document

**See:** `docs/DOCUMENTATION_GUIDE.md` for file organization standards

---

## 🗄️ Archive Policy

**Move to `archive/` when:**
- Session artifacts completed
- Status reports superseded
- Old approaches replaced
- Historical reference only

**Archive structure:**
```
archive/
├── YYYY-MM-DD/     (session artifacts)
└── old/            (superseded docs)
```

---

**Directory Status:** Active
**File Organization:** Chronological numbering (01-99)
**Next Available Number:** 05

---

## 🚀 Quick Reference

**Daily Health Check:** Run `./bin/orchestration/quick_health_check.sh`

**Key Metrics (typical day with 19 games):**
- 38 workflow executions
- 500+ scraper runs (many "no_data" status = normal)
- 97-99% success rate expected

**Common Issues:**
- "no_data" status = successful run with no new data (not an error)
- Failed scrapers: Check `scraper_execution_log` for error details
- Missing executions: Compare `workflow_decisions` vs `workflow_executions`

**See:** `04-troubleshooting.md` for detailed troubleshooting procedures
