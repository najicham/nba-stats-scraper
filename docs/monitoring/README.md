# Monitoring Documentation

**Last Updated:** 2025-11-18
**Purpose:** Observability, monitoring, and health checks across all pipeline phases
**Audience:** Engineers monitoring system health and investigating issues

---

## 📖 Reading Order (Start Here!)

**New to monitoring? Read these in order:**

### 1. **02-grafana-daily-health-check.md** ⭐ START HERE
   - **Created:** 2025-11-14 16:24 PST
   - **Quick 6-panel dashboard for daily health checks**
   - **Why read this:** Get daily system status in 2-3 minutes
   - **Status:** Current (production monitoring)

### 2. **01-grafana-monitoring-guide.md**
   - **Created:** 2025-11-14 16:26 PST
   - **Comprehensive monitoring queries and dashboard insights**
   - **Why read this:** Deep dive into all available metrics and queries
   - **Status:** Current (reference guide)

### 3. **03-grafana-phase2-phase3-pipeline-monitoring.md**
   - **Phase 2-3 pipeline monitoring**
   - **Why read this:** Monitor data flow between phases
   - **Status:** Current

### 4. **04-observability-gaps-and-improvement-plan.md** ⭐ NEW
   - **Created:** 2025-11-18
   - **Current observability capabilities, gaps, and improvement roadmap**
   - **Why read this:** Understand what visibility exists today and what's missing
   - **Status:** Current (living document for platform improvements)

### 5. **OBSERVABILITY_QUICK_REFERENCE.md** 📋 QUICK LOOKUP
   - **Created:** 2025-11-18
   - **One-page checklist: What's logged vs what's missing**
   - **Why read this:** Fast reference when debugging or planning improvements
   - **Status:** Current (companion to doc #4)

### 6. **05-data-completeness-validation.md** ⭐ VALIDATION QUERIES
   - **Created:** 2025-11-18
   - **Complete data validation procedures for daily ops and backfills**
   - **Why read this:** Validate completeness, find gaps, reconcile row counts
   - **Key Queries:** Daily completeness, backfill range validation, row count reconciliation, missing entities
   - **Status:** Current (ready to use)

### 7. **06-alerting-strategy-and-escalation.md** 🚨 ALERTING & ON-CALL (30-40 min)
   - **Created:** 2025-11-18 15:30 PST
   - **Alert severity matrix, escalation paths, and on-call runbooks**
   - **Why read this:** Respond to incidents, configure alerts, prevent alert fatigue
   - **Key Content:** Severity levels (Critical/High/Medium/Low), escalation tree, DLQ alerts, backfill monitoring, runbooks
   - **Status:** Current (ready for on-call setup)

### 8. **07-single-entity-debugging.md** 🔍 ENTITY DEBUGGING (20-25 min)
   - **Created:** 2025-11-18 15:45 PST
   - **Trace individual players, teams, or games through entire pipeline**
   - **Why read this:** Debug "Why doesn't LeBron have data?", trace missing entities
   - **Key Queries:** Player trace, team trace, game trace, historical data checks
   - **Status:** Current (ready to use)

---

## 🗂️ What Goes in This Directory

**Monitoring** = Observability and health checks across all pipeline phases

**Belongs here:**
- ✅ Grafana dashboard configuration
- ✅ Health check procedures (daily, hourly, etc.)
- ✅ BigQuery monitoring queries
- ✅ Alert thresholds and escalation
- ✅ SLO/SLI definitions
- ✅ Performance monitoring
- ✅ Incident response guides

**Does NOT belong here:**
- ❌ Phase-specific troubleshooting (goes in phase directories)
- ❌ Operational procedures (goes in phase directories)
- ❌ Infrastructure setup (goes in `infrastructure/`)
- ❌ Data quality validation (goes in `data-flow/` or phase dirs)

**Rule of thumb:** If it's about observing/monitoring the system, it goes here. If it's about operating/fixing, it goes in the phase directory.

---

## 📋 Current Topics

### Grafana Dashboards
- Daily health check (6-panel quick view)
- Comprehensive monitoring (detailed metrics)
- Phase 1 orchestration tracking
- Phase 2 processor health

### Monitoring Queries
- Workflow execution status
- Scraper success/failure rates
- Expected vs actual execution comparison
- Discovery mode progress tracking
- Processor delivery rates

### Observability Improvements
- Gap analysis: What's logged vs what's missing
- Proposed improvements: processor_execution_log, dependency_check_log
- Implementation roadmap with effort estimates
- Quality metadata tracking strategy

### Data Completeness Validation
- Daily completeness checks (single date validation)
- Backfill range completeness (date range validation)
- Row count reconciliation (cross-phase verification)
- Missing entity detection (find specific gaps)
- Recovery procedures

### Alerting & Escalation
- Alert severity matrix (Critical, High, Medium, Low)
- Escalation paths and on-call rotation
- Phase-specific alerts (DLQ, backfill, processing)
- On-call runbooks (decision trees)
- Alert fatigue prevention strategies

### Entity-Level Debugging
- Player trace queries (follow individual player)
- Team trace queries (follow team through pipeline)
- Game trace queries (full game processing)
- "Why didn't entity process?" diagnostic checklists
- Historical data availability checks

### Health Checks
- Quick daily health check script
- System status verification
- Missing execution detection
- Data completeness validation

---

## 🔗 Related Documentation

**Operational Guides (What to Do When Monitoring Shows Issues):**
- **Phase 1 Troubleshooting:** `docs/orchestration/04-troubleshooting.md`
- **Phase 2 Operations:** `docs/processors/01-phase2-operations-guide.md`
- **Backfill Operations:** `docs/operations/01-backfill-operations-guide.md`
- **Cross-Date Dependencies:** `docs/architecture/08-cross-date-dependency-management.md`

**Infrastructure:**
- **Pub/Sub Health:** `docs/infrastructure/` - Integration verification

**System Design:**
- **Architecture:** `docs/architecture/` - Overall system design
- **Data Flow:** `docs/data-flow/` - Data transformation tracking

---

## 📝 Adding New Documentation

**To add monitoring documentation:**

1. **Check scope** - Is this cross-phase monitoring or phase-specific?
   - Cross-phase → Add here
   - Phase-specific troubleshooting → Add to phase directory

2. **Find next number:** `ls *.md | tail -1` → Currently at 02, next is 03

3. **Create file:** `03-new-monitoring-doc.md`

4. **Use standard metadata header**

5. **Update this README** with the new document

**Common topics for this directory:**
- New Grafana dashboard guides
- Alert configuration docs
- SLO/SLI definitions
- Performance baseline docs

**See:** `docs/DOCUMENTATION_GUIDE.md` for file organization standards

---

## 🗄️ Archive Policy

**Move to `archive/` when:**
- Dashboard configurations superseded
- Monitoring queries replaced by better versions
- Alert thresholds updated (keep old versions for reference)
- Historical baseline docs (no longer current)

**Archive structure:**
```
archive/
├── YYYY-MM-DD/     (session artifacts)
└── old/            (superseded configs)
```

---

**Directory Status:** Active
**File Organization:** Chronological numbering (01-99) + Quick reference cards
**Next Available Number:** 05
**Quick References:** OBSERVABILITY_QUICK_REFERENCE.md (one-page lookup)

---

## 🚀 Quick Reference

**Daily Health Check:** See `02-grafana-daily-health-check.md`
- 6 panels: Workflows today, scraper status, execution rate, Phase 2 delivery, failures, discovery
- Takes 2-3 minutes
- Answers: "Is the system healthy?"

**Comprehensive Monitoring:** See `01-grafana-monitoring-guide.md`
- All available BigQuery monitoring queries
- Detailed metric explanations
- Advanced troubleshooting insights

**Observability Gaps & Improvements:** See `04-observability-gaps-and-improvement-plan.md`
- What visibility exists today (Phase 1 excellent, Phase 2-5 gaps)
- Missing capabilities: processor execution log, dependency checks
- Prioritized improvement plan with effort estimates
- Use this when planning monitoring enhancements
- **Quick Reference:** `OBSERVABILITY_QUICK_REFERENCE.md` (one-page checklist)

**Key Metrics:**
- Workflow execution rate: >95% expected
- Scraper success rate: 97-99% typical
- Phase 2 delivery: 100% expected
- Discovery completion: <12 attempts expected
