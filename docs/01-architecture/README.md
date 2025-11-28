# Architecture Documentation

**File:** `docs/architecture/README.md`
**Last Updated:** 2025-11-25
**Purpose:** Architecture, design decisions, and implementation roadmap for NBA data pipeline
**Status:** Current
**Audience:** Engineers building and understanding the system

---

## 📖 Reading Order (Start Here!)

**New to the system? Read these in order:**

### 0. **00-quick-reference.md** 💡 QUICK START (2-3 minutes)
   - **Created:** 2025-11-15
   - **At-a-glance overview** of entire pipeline
   - System diagram, current status, next steps
   - Key concepts in bullet points
   - **Start here for quick orientation**

### 1. **04-event-driven-pipeline-architecture.md** ⭐ COMPREHENSIVE (30-45 minutes)
   - **Created:** 2025-11-14 22:33 PST, Updated 2025-11-15
   - **Complete 6-phase pipeline architecture**
   - Foundational design from scrapers → web app
   - Addresses all architectural concerns with detailed explanations
   - **Read this to understand the complete vision**

### 2. **[SYSTEM_STATUS.md](../SYSTEM_STATUS.md)** 📊 CURRENT STATUS (5 minutes)
   - **Single source of truth** for deployment status
   - Current reality: ~70% complete
   - Phase-by-phase status and next steps
   - **Read this to understand where we are today**

   > Note: `05-implementation-status-and-roadmap.md` is preserved for historical context (original planning from 2025-11-15)

### 3. **01-phase1-to-phase5-integration-plan.md** 🔧 INTEGRATION DETAILS (15 minutes) *(Historical)*
   - **Created:** 2025-11-14 22:03 PST
   - Detailed Phase 2→3 implementation specifics
   - Dependency coordination, idempotency solutions
   - **Historical context** - Phase 2→3 now implemented

### 4. **02-phase1-to-phase5-granular-updates.md** ⚡ PERFORMANCE (15 minutes)
   - **Created:** 2025-11-14 22:16 PST, Updated 2025-11-15
   - **Entity-level granularity design** (Sprint 8 enhancement)
   - Incremental updates (1 player vs 450 = 60x faster)
   - Real-world scenarios and performance comparisons
   - **Performance optimization for future**

### 5. **03-pipeline-monitoring-and-error-handling.md** 📡 OBSERVABILITY (20 minutes)
   - **Created:** 2025-11-14 22:22 PST, Updated 2025-11-15
   - **End-to-end tracking and recovery**
   - Correlation ID design, pipeline_execution_log schema
   - Monitoring queries (see `examples/monitoring/`)
   - DLQ recovery procedures (see `examples/recovery/`)
   - **Observability and error handling design**

### 6. **06-change-detection-and-event-granularity.md** 🎯 FUTURE OPTIMIZATION (15 minutes)
   - **Created:** 2025-11-15
   - **Change detection patterns for fine-grained updates**
   - When to optimize vs keep it simple
   - Metrics to watch, decision framework
   - Field-level change metadata, multiple event types
   - **Read when considering optimizations beyond entity-level**

### 7. **07-change-detection-current-state-investigation.md** 🔍 INVESTIGATION (20 minutes)
   - **Created:** 2025-11-18
   - **Investigation of actual current implementation**
   - Queries to check Phase 2/3 behavior
   - Test scenarios for single-entity changes
   - Decision matrix based on findings
   - **Companion to 06 - answers "what's really happening today?"**

### 8. **08-cross-date-dependency-management.md** 🔄 DEPENDENCIES (30-40 minutes)
   - **Created:** 2025-11-18
   - **Cross-date dependencies for backfills and Phase 4**
   - Game-based vs calendar-based lookback windows
   - Early season handling (degraded quality scores)
   - Backfill orchestration order (phase-by-phase, not date-by-date)
   - Dependency check queries
   - **Critical for backfill operations and Phase 4 processors**

### 9. **pipeline-integrity.md** 🛡️ PIPELINE SAFETY (15 minutes) ⚠️ *Awaiting Field Testing*
   - **Created:** 2025-11-28
   - **Status:** Production-ready code, awaiting field testing
   - **Prevents cascading failures and data gaps**
   - Cascade control for safe backfills (`--skip-downstream-trigger`)
   - Defensive checks (upstream status, gap detection)
   - Backfill strategy for 4 seasons
   - **Read before doing historical backfills or investigating pipeline failures**
   - Detailed docs: `docs/08-projects/current/pipeline-integrity/`

---

## 🗂️ Document Organization

### File Naming Convention

**Active docs use chronological numbering (01-99):**
- Files are numbered in creation order
- Prefix is **chronological**, not pedagogical
- Reading order defined in this README (not by filename)
- Archive old docs when superseded

**Why chronological?**
- ✅ New docs just increment the highest number (no context needed)
- ✅ Shows historical development of architecture
- ✅ Never requires renaming existing files
- ✅ README provides logical reading order

### Directory Structure

```
docs/architecture/
├── README.md                                    (you are here)
├── 00-quick-reference.md                        (2-page overview)
├── 01-phase1-to-phase5-integration-plan.md     (historical - Phase 2→3 now implemented)
├── 02-phase1-to-phase5-granular-updates.md     (entity-level design)
├── 03-pipeline-monitoring-and-error-handling.md (observability design)
├── 04-event-driven-pipeline-architecture.md     (⭐ COMPREHENSIVE - start here)
├── 05-implementation-status-and-roadmap.md      (historical - original planning)
├── 06-change-detection-and-event-granularity.md (future optimization)
├── 07-change-detection-current-state-investigation.md (investigation)
├── 08-cross-date-dependency-management.md       (critical for backfills)
│
└── archive/
    ├── 2025-11-25/                              (archived implementation task docs)
    │   ├── 09-phase2-phase3-implementation-roadmap.md
    │   ├── 10-week1-schema-and-code-changes.md
    │   ├── 11-phase3-phase4-implementation-plan.md
    │   └── historical-dependency-checking-plan.md
    ├── 2025-11-15/                              (reorganization artifacts)
    ├── 2025-11-14/                              (session artifacts)
    └── 2024-10-14/                              (old architecture)
```

---

## 📝 Adding New Documents

**When creating a new architecture doc:**

```bash
# Step 1: Find the highest number
ls docs/architecture/*.md | grep -oE '^[0-9]+' | sort -n | tail -1
# Example output: 05

# Step 2: Create new doc with next number
# New file: 06-your-new-doc-name.md

# Step 3: Update this README
# Add to "Reading Order" section if it's foundational
# Or add to "Deep Dive Documents" if it's a detail doc
```

**No renaming needed!** Just increment and go.

---

## 📚 Document Categories

### Vision & Design (Read First)
- **04-event-driven-pipeline-architecture.md** - Complete 6-phase vision

### Current Status (Read Second)
- **05-implementation-status-and-roadmap.md** - Gaps and 8-sprint plan

### Implementation Details (Read Third+)
- **01-phase1-to-phase5-integration-plan.md** - Phase 2→3 integration
- **02-phase1-to-phase5-granular-updates.md** - Entity-level optimization
- **03-pipeline-monitoring-and-error-handling.md** - Observability

### Investigation & Analysis
- **06-change-detection-and-event-granularity.md** - Design patterns (future)
- **07-change-detection-current-state-investigation.md** - Current state (what's implemented)
- **08-cross-date-dependency-management.md** - Cross-date dependencies for backfills

### Future Topics (Not Yet Created)
Potential future docs (will use 09+):
- Phase 6 Publishing Architecture (detailed)
- Correlation ID Implementation Guide (detailed)
- Phase 3→4 Integration Plan (detailed)
- Phase 4→5 Integration Plan (detailed)
- Entity-Level Granularity Migration Plan (step-by-step guide)
- Performance Tuning and Optimization Guide

---

## 🔗 Related Documentation

### Code Examples (NEW 2025-11-15)
- **Pub/Sub Integration:** `../../examples/pubsub_integration/`
  - `raw_data_publisher.py` - RawDataPubSubPublisher reference implementation
  - `message_examples.json` - Example messages for all phases
- **Monitoring Queries:** `../../examples/monitoring/`
  - `pipeline_health_queries.sql` - Grafana dashboard queries
- **Recovery Scripts:** `../../examples/recovery/`
  - `replay_dlq.sh` - DLQ health check and replay

### Operational Guides
- **Phase 1 Operations:** `../orchestration/phase1_monitoring_operations_guide.md`
- **Phase 2 Operations:** `../orchestration/phase2_operations_guide.md`
- **Grafana Monitoring:** `../orchestration/grafana-monitoring-guide.md`
- **Pub/Sub Status:** `../orchestration/pubsub-integration-status-2025-11-15.md`

### Technical Specifications
- **BigQuery Schemas:** `../../schemas/bigquery/`

### Session Notes
- **Implementation Sessions:** `../sessions/` (detailed logs)

---

## 🗄️ Archive Policy

### When to Archive

**Move to archive/ when:**
- Status reports superseded by new milestone
- Handoff documents completed
- Old architecture replaced by new design
- Document becomes historical reference only

### Archive Structure

```
archive/
├── YYYY-MM-DD/          (session artifacts)
│   └── doc-name.md      (preserve original filename)
└── old/                 (superseded docs)
```

**Currently archived:** See `archive/` directory for session artifacts and superseded docs.

**For reorganization details:** See `archive/2025-11-15/architecture-reorganization-handoff.md`

---

## 🎯 Quick Reference

**Current Status:** ~70% Complete (as of 2025-11-25)

| Phase | Status |
|-------|--------|
| Phase 1-3 | ✅ Production |
| Phase 4 | ⏳ Schemas deployed, code updates pending |
| Phase 5 | ⏳ Partial implementation |
| Phase 6 | ❌ Not started |

**For detailed status:** See [SYSTEM_STATUS.md](../SYSTEM_STATUS.md)

---

## 💡 Key Concepts

**Event-Driven Architecture:**
- Each phase triggers the next via Pub/Sub
- Automatic retries, Dead Letter Queues
- Decoupled, scalable, observable

**Opportunistic Triggering:**
- Phase 3 triggered on ANY Phase 2 completion
- Checks dependencies each time (self-healing retries)
- Idempotency prevents duplicate work

**Entity-Level Granularity:**
- Process 1 player instead of 450 (60x faster for injury updates)
- Progressive enhancement: date-level → game-level → entity-level

**Correlation ID:**
- Flows through all 6 phases
- Enables end-to-end debugging
- Detects stuck pipelines

---

## 🔍 Finding Information

**"Where do I start?"**
→ Read **04-event-driven-pipeline-architecture.md**

**"What's working today?"**
→ See [SYSTEM_STATUS.md](../SYSTEM_STATUS.md)

**"How do I optimize for incremental updates?"**
→ See **02-phase1-to-phase5-granular-updates.md** "Entity-Level Granularity"

**"How do I monitor the pipeline?"**
→ See **03-pipeline-monitoring-and-error-handling.md** "Monitoring & Alerting"

**"What are the next steps?"**
→ See [SYSTEM_STATUS.md](../SYSTEM_STATUS.md)

---

## 📞 Questions?

**For architecture questions:**
- Review this README's reading order
- Start with 04 (vision), then 05 (status)
- Deep dive into 01-03 as needed

**For implementation help:**
- Check roadmap in 05 for sprint tasks
- Reference implementation plan in 01
- See operational guides in `../orchestration/`

**For current system operations:**
- See operational guides: `../orchestration/phase1_operations_guide.md`
- See monitoring guide: `../orchestration/grafana-monitoring-guide.md`

---

**Document Status:** Current and maintained
**Last Updated:** 2025-11-25
**Changes (2025-11-25):**
- Updated status to ~70% complete
- Archived implementation task docs (09-11) to `archive/2025-11-25/`
- Added historical banners to 01, 05
- Simplified status table (now points to SYSTEM_STATUS.md)

**Next Review:** After Phase 4 deployment

---

*This README is the definitive index for architecture documentation. Keep it updated as new docs are added.*
