# Monitoring Documentation

**Last Updated:** 2025-11-15
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

### Health Checks
- Quick daily health check script
- System status verification
- Missing execution detection

---

## 🔗 Related Documentation

**Operational Guides (What to Do When Alerts Fire):**
- **Phase 1 Troubleshooting:** `docs/orchestration/04-troubleshooting.md`
- **Phase 2 Operations:** `docs/processors/01-phase2-operations-guide.md`

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
**File Organization:** Chronological numbering (01-99)
**Next Available Number:** 03

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

**Key Metrics:**
- Workflow execution rate: >95% expected
- Scraper success rate: 97-99% typical
- Phase 2 delivery: 100% expected
- Discovery completion: <12 attempts expected
