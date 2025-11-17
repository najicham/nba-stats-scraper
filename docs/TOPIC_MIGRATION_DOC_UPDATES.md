# Topic Name Migration - Documentation Updates

**Created:** 2025-11-16
**Status:** Action Required
**Purpose:** Track all documentation updates needed for new topic naming convention

---

## **Topic Naming Changes**

### **Old Convention (Content-Based)**
```
Phase 1 → 2: nba-scraper-complete
Phase 2 → 3: nba-raw-data-complete
Phase 3 → 4: nba-analytics-complete
Phase 4 → 5: nba-precompute-complete
Phase 5 → 6: nba-predictions-complete
```

### **New Convention (Hybrid: Phase + Content)**
```
Phase 1 → 2: nba-phase1-scrapers-complete
Phase 2 → 3: nba-phase2-raw-complete
Phase 3 → 4: nba-phase3-analytics-complete
Phase 4 → 5: nba-phase4-precompute-complete
Phase 5 → 6: nba-phase5-predictions-complete
```

### **New: Fallback Triggers (Safety Nets)**
```
Phase 2 Fallback: nba-phase2-fallback-trigger
Phase 3 Fallback: nba-phase3-fallback-trigger
Phase 4 Fallback: nba-phase4-fallback-trigger
Phase 5 Fallback: nba-phase5-fallback-trigger
Phase 6 Fallback: nba-phase6-fallback-trigger
```

### **New: Dead Letter Queues (All Phases)**
```
Phase 1 DLQ: nba-phase1-scrapers-complete-dlq
Phase 2 DLQ: nba-phase2-raw-complete-dlq
Phase 3 DLQ: nba-phase3-analytics-complete-dlq
Phase 4 DLQ: nba-phase4-precompute-complete-dlq
Phase 5 DLQ: nba-phase5-predictions-complete-dlq
```

---

## **Documentation Files Needing Updates**

### **Priority 1: Core Architecture Docs (CRITICAL)**

These are the authoritative source of truth - update FIRST:

#### 1. `docs/architecture/04-event-driven-pipeline-architecture.md`
**Impact:** HIGH - This is the main architecture doc
**Changes:**
- [ ] Update all topic names in pipeline diagram (lines ~118-156)
- [ ] Update Phase 2→3 examples (lines ~193-240)
- [ ] Update message format examples (lines ~313-400)
- [ ] Add fallback trigger documentation
- [ ] Update DLQ section with all phase DLQs

#### 2. `docs/architecture/05-implementation-status-and-roadmap.md`
**Impact:** HIGH - Tracks implementation progress
**Changes:**
- [ ] Update Gap #1 topic names (line ~123)
- [ ] Update Gap #2 topic names (line ~153)
- [ ] Update Sprint 1 tasks with correct topic names (lines ~334-341)
- [ ] Update Sprint 2 tasks (lines ~382-387)
- [ ] Update all code examples with new topics

#### 3. `docs/architecture/03-pipeline-monitoring-and-error-handling.md`
**Impact:** HIGH - Monitoring and DLQ handling
**Changes:**
- [ ] Update all DLQ topic names (lines ~104-108)
- [ ] Update DLQ monitoring queries (lines ~1566-1582)
- [ ] Update recovery procedures with new topic names
- [ ] Add fallback trigger monitoring section

#### 4. `docs/architecture/01-phase1-to-phase5-integration-plan.md`
**Impact:** MEDIUM - Integration planning doc
**Changes:**
- [ ] Update Phase 1→2 topic name (line ~35)
- [ ] Update Phase 2→3 topic name (lines ~101, 390, 400)
- [ ] Update all example code snippets

#### 5. `docs/architecture/00-quick-reference.md`
**Impact:** MEDIUM - Quick reference guide
**Changes:**
- [ ] Update all topic names in quick reference table
- [ ] Add fallback trigger reference
- [ ] Update DLQ reference

---

### **Priority 2: Operations & Processor Docs (HIGH)**

#### 6. `docs/processors/01-phase2-operations-guide.md`
**Impact:** HIGH - Phase 2 operations
**Changes:**
- [ ] Update Phase 1→2 topic: `nba-scraper-complete` → `nba-phase1-scrapers-complete` (lines ~108, 134)
- [ ] Update Phase 2→3 topic: `nba-raw-data-complete` → `nba-phase2-raw-complete` (line ~89, 637)
- [ ] Update DLQ references (lines ~144, 317, 323, 506, 509)
- [ ] Add Phase 2 fallback trigger documentation
- [ ] Update all gcloud commands with new topic names (lines ~418, 523, 753)

#### 7. `docs/processors/02-phase3-operations-guide.md`
**Impact:** HIGH - Phase 3 operations
**Changes:**
- [ ] Update Phase 2→3 topic: `nba-raw-data-complete` → `nba-phase2-raw-complete` (line ~100)
- [ ] Update Phase 3→4 topic: `nba-analytics-complete` → `nba-phase3-analytics-complete`
- [ ] Update fallback trigger documentation (already mentions phase3-fallback-trigger)
- [ ] Verify all Pub/Sub references are correct

#### 8. `docs/processors/03-phase3-scheduling-strategy.md`
**Impact:** HIGH - Phase 3 scheduling
**Changes:**
- [ ] Update Phase 2→3 topic names in Cloud Scheduler examples
- [ ] Update subscription names
- [ ] Add Phase 2 fallback trigger schedule

#### 9. `docs/processors/PHASE3_DEPLOYMENT_READINESS.md`
**Impact:** HIGH - Deployment checklist
**Changes:**
- [ ] Update Gap #1 topic name from `nba-raw-data-complete` → `nba-phase2-raw-complete`
- [ ] Update all checklist items with correct topics
- [ ] Update code examples

---

### **Priority 3: Infrastructure Docs (MEDIUM)**

#### 10. `docs/infrastructure/01-pubsub-integration-verification.md`
**Impact:** MEDIUM - Pub/Sub verification procedures
**Changes:**
- [ ] Update Phase 1→2 topic: `nba-scraper-complete` → `nba-phase1-scrapers-complete` (multiple lines)
- [ ] Update DLQ references (lines ~171, 299, 314, 315, 321, 590, 616, 620, 773, 840, 859)
- [ ] Add verification procedures for fallback triggers

#### 11. `docs/infrastructure/02-pubsub-schema-management.md`
**Impact:** MEDIUM - Message schema docs
**Changes:**
- [ ] Update all topic names in examples (lines ~101, 186, 305, 340, 344)
- [ ] Update schema validation examples
- [ ] Add fallback trigger message schemas

---

### **Priority 4: Archive Docs (LOW - Optional)**

These are historical/archived docs - update for completeness but not critical:

#### 12-16. Archive docs
- `docs/orchestration/archive/2025-11-15/pubsub-integration-status-2025-11-15.md`
- `docs/archive/2025-11-12/pubsub/COMPLETE_IMPLEMENTATION_GUIDE.md`
- `docs/archive/2025-11-12/pubsub/README_ARTIFACTS_PACKAGE.md`
- `docs/archive/2025-11-12/pubsub/EXECUTIVE_SUMMARY.md`
- `docs/archive/2025-10-14/root-level/ARCHITECTURE.md`

**Changes:**
- [ ] Add deprecation notices at top
- [ ] Link to current docs for updated info
- [ ] Optional: Update topic names for historical accuracy

---

## **Code Files Needing Updates**

### **Critical Code Updates**

#### 1. `scrapers/utils/pubsub_utils.py`
**Impact:** CRITICAL - Phase 1 publishing
**Changes:**
- [ ] Import from `shared.config.pubsub_topics`
- [ ] Replace hardcoded `"nba-scraper-complete"` with `TOPICS.PHASE1_SCRAPERS_COMPLETE`
- [ ] Prepare for dual publishing (migration period)

#### 2. `data_processors/raw/processor_base.py`
**Impact:** CRITICAL - Phase 2 processing
**Changes:**
- [ ] Import from `shared.config.pubsub_topics`
- [ ] Add publishing after `save_data()` using `TOPICS.PHASE2_RAW_COMPLETE`

#### 3. `data_processors/analytics/main_analytics_service.py`
**Impact:** HIGH - Phase 3 service
**Changes:**
- [ ] Verify subscription pointing to correct topic
- [ ] Update any hardcoded topic references

---

## **Global Search & Replace Guide**

**Use with caution!** These are suggested patterns, but verify each replacement:

```bash
# Phase 1 topic
find docs -type f -name "*.md" -exec sed -i 's/nba-scraper-complete/nba-phase1-scrapers-complete/g' {} \;

# Phase 2 topic
find docs -type f -name "*.md" -exec sed -i 's/nba-raw-data-complete/nba-phase2-raw-complete/g' {} \;

# Phase 3 topic
find docs -type f -name "*.md" -exec sed -i 's/nba-analytics-complete/nba-phase3-analytics-complete/g' {} \;

# Phase 4 topic
find docs -type f -name "*.md" -exec sed -i 's/nba-precompute-complete/nba-phase4-precompute-complete/g' {} \;

# Phase 5 topic
find docs -type f -name "*.md" -exec sed -i 's/nba-predictions-complete/nba-phase5-predictions-complete/g' {} \;
```

**⚠️ WARNING:** Test these commands on a few files first, or create a git branch before bulk updates!

---

## **New Documentation to Add**

### **1. Centralized Config Usage Guide**

Create: `docs/development/pubsub-topics-usage.md`

**Content:**
- How to import and use `TOPICS` constants
- Examples for each phase
- Best practices (never hardcode topic names)
- Migration guide from hardcoded strings

### **2. Fallback Trigger Guide**

Create: `docs/infrastructure/03-fallback-triggers-guide.md`

**Content:**
- What are fallback triggers?
- When do they fire?
- How to configure Cloud Scheduler
- Testing fallback scenarios
- Monitoring fallback usage

---

## **Validation Checklist**

After updates, verify:

- [ ] All architecture docs have consistent topic names
- [ ] All code uses `TOPICS.*` constants (no hardcoded strings)
- [ ] All gcloud commands use new topic names
- [ ] DLQ monitoring covers all phases
- [ ] Fallback triggers documented for all phases
- [ ] Message schema examples match new topics
- [ ] Test commands in docs work with new topics

---

## **Recommended Update Order**

1. **Day 1: Architecture Docs** (Priority 1)
   - Update 04-event-driven-pipeline-architecture.md
   - Update 05-implementation-status-and-roadmap.md
   - Update 03-pipeline-monitoring-and-error-handling.md

2. **Day 1: Operations Docs** (Priority 2)
   - Update 01-phase2-operations-guide.md
   - Update 02-phase3-operations-guide.md
   - Update 03-phase3-scheduling-strategy.md
   - Update PHASE3_DEPLOYMENT_READINESS.md

3. **Day 2: Infrastructure & Remaining Docs**
   - Update infrastructure docs
   - Update remaining processor docs
   - Add new documentation

4. **Day 2: Archive Cleanup** (if time permits)
   - Add deprecation notices to archived docs
   - Link to current docs

---

## **Progress Tracking**

**Status:** Not started
**Priority 1 Completed:** 0/5
**Priority 2 Completed:** 0/4
**Priority 3 Completed:** 0/2
**Code Updates Completed:** 0/3

**Last Updated:** 2025-11-16
**Updated By:** Claude Code

---

**Next Action:** Start with Priority 1 docs (architecture) to establish correct naming convention across the system.
