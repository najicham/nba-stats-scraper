# Architecture Documentation

**Last Updated:** 2025-11-15 (Major content reorganization and reduction)
**Purpose:** Architecture, design decisions, and implementation roadmap for NBA data pipeline
**Audience:** Engineers building and understanding the system
**Recent Changes:** Condensed docs by ~30%, removed duplication, consolidated roadmaps, created examples/ directory

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

### 2. **05-implementation-status-and-roadmap.md** 📊 CURRENT STATUS (15-20 minutes)
   - **Created:** 2025-11-14 22:41 PST, Updated 2025-11-15
   - **Current reality: ~45% complete** (verified 2025-11-15)
   - Gap analysis (what works vs what's missing)
   - Prioritized 8-sprint roadmap (~73 hours total)
   - **Read this to understand where we are and what's next**

### 3. **01-phase1-to-phase5-integration-plan.md** 🔧 INTEGRATION DETAILS (15 minutes)
   - **Created:** 2025-11-14 22:03 PST, Updated 2025-11-15
   - **Detailed Phase 2→3 implementation specifics**
   - Dependency coordination, idempotency solutions
   - Code references to `examples/` directory
   - **Deep dive into first critical integration**

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
├── 00-quick-reference.md                        (2-page overview - NEW 2025-11-15)
├── 01-phase1-to-phase5-integration-plan.md     (created first, condensed 2025-11-15)
├── 02-phase1-to-phase5-granular-updates.md     (created second, condensed 2025-11-15)
├── 03-pipeline-monitoring-and-error-handling.md (created third, updated 2025-11-15)
├── 04-event-driven-pipeline-architecture.md     (created fourth - COMPREHENSIVE)
├── 05-implementation-status-and-roadmap.md      (created fifth - CURRENT STATUS)
├── 06-change-detection-and-event-granularity.md (created sixth - FUTURE OPTIMIZATION)
├── 07-change-detection-current-state-investigation.md (created seventh - INVESTIGATION)
├── 08-cross-date-dependency-management.md (created eighth - DEPENDENCIES)
├── ... future docs use 09, 10, 11, etc.
│
└── archive/
    ├── 2025-11-15/                              (reorganization artifacts - NEW)
    │   └── (future: documentation-cleanup-handoff.md)
    ├── 2025-11-14/                              (session artifacts)
    │   ├── HANDOFF_ORCHESTRATION_REVIEW.md      (session handoff)
    │   └── orchestration-documents-review.md    (doc assessment)
    └── 2024-10-14/                              (old architecture)
        ├── infrastructure-decisions.md
        ├── service-architecture.md
        ├── system-architecture.md
        └── system-overview.md
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

### Current Implementation Status (as of 2025-11-15)

| Component | Status | Completeness | Last Verified |
|-----------|--------|--------------|---------------|
| Phase 1→2 Reception | ✅ Working | 100% | 2025-11-15 |
| Phase 2 Processing | ✅ Working | 100% | 2025-11-15 |
| Phase 2→3 Publishing | ❌ Missing | 0% | Sprint 1: ~5hrs |
| Phase 3 Analytics | ✅ Partial | 90% | 2025-11-15 |
| Phase 3→4 Integration | ❌ Missing | 10% | Sprint 3: ~8hrs |
| Phase 4 Precompute | ⚠️ Skeleton | 10% | Sprint 3: ~8hrs |
| Phase 5 Predictions | ⚠️ Standalone | 40% | Sprint 6: ~9hrs |
| Phase 6 Publishing | ❌ Not Started | 0% | Sprint 7: ~16hrs |
| Correlation ID Tracking | ❌ Missing | 0% | Sprint 2: ~8hrs |
| Unified Pipeline Log | ❌ Missing | 0% | Sprint 2: ~3hrs |
| Monitoring Dashboard | ⚠️ Basic | 30% | Sprint 4: ~8hrs |

**Overall: ~45% Complete**

**Verified 2025-11-15:** Phase 1→2 fully operational (1,482 events in 3hrs, 100% delivery)

### Next Milestones

**Sprint 1 (Week 1):** Phase 2→3 Pub/Sub Connection (~2 hours)
- Enable automatic Phase 3 triggering
- Critical gap, highest ROI

**Sprint 2 (Week 1-2):** Correlation ID Tracking (~6 hours)
- End-to-end pipeline tracing
- Foundation for observability

**Sprint 3 (Week 2):** Phase 3→4 Connection (~8 hours)
- Extend pattern to precompute layer

See **05-implementation-status-and-roadmap.md** for complete 8-sprint plan.

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
→ See **05-implementation-status-and-roadmap.md** "What We Have" section

**"How do I implement Phase 2→3?"**
→ See **01-phase1-to-phase5-integration-plan.md** "Proposed Solutions"

**"How do I optimize for incremental updates?"**
→ See **02-phase1-to-phase5-granular-updates.md** "Entity-Level Granularity"

**"How do I monitor the pipeline?"**
→ See **03-pipeline-monitoring-and-error-handling.md** "Monitoring & Alerting"

**"What are the next steps?"**
→ See **05-implementation-status-and-roadmap.md** "Prioritized Roadmap"

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
**Recent Reorganization:** 2025-11-15 (content reduction, duplication removal, examples extraction)
**Changes Summary:**
- Created `00-quick-reference.md` for fast orientation
- Created `06-change-detection-and-event-granularity.md` for future optimization patterns
- Condensed docs 01-02 by ~30% (removed duplicate explanations)
- Consolidated all roadmaps to doc 05 only
- Extracted code examples to `examples/` directory
- Updated all status headers to reflect actual implementation
- Fixed README status table with accurate percentages
- Enhanced `examples/pubsub_integration/message_examples.json` with future patterns

**Next Review:** After Sprint 1 completion (Phase 2→3 integration)

---

*This README is the definitive index for architecture documentation. Keep it updated as new docs are added.*
