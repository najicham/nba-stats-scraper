# Quick Start Guide - v1.0 Implementation

**For:** Developer starting v1.0 implementation
**Created:** 2025-11-28 9:06 PM PST
**Last Updated:** 2025-11-28 9:06 PM PST
**Time to read:** 5 minutes

---

## 📚 Document Reading Order

Read these documents in this order before starting:

1. **START HERE:** This guide (5 min)
2. **ARCHITECTURE-DECISIONS.md** (10 min) - Key decisions and rationale
3. **V1.0-IMPLEMENTATION-PLAN.md** (20 min) - Detailed week-by-week plan
4. **UNIFIED-ARCHITECTURE-DESIGN.md** (30 min) - Complete technical spec
5. **IMPLEMENTATION-FULL.md** (15 min) - Phase 4→5 specific code

**Total reading time:** ~80 minutes

---

## 🎯 What We're Building (30-second summary)

**Current State:**
- Phases 1-2: ✅ Working (4 seasons backfilled)
- Phases 3-5: ❌ Never run in production

**What We're Building:**
- Complete event-driven pipeline (Phase 1→2→3→4→5)
- Unified message format across all phases
- Correlation ID tracing (scraper → prediction)
- Backfill mode (skip downstream triggers)
- Orchestrators for Phase 3→4 and Phase 4 internal

**Timeline:** 3-4 weeks, ~68 hours

**Scope:** v1.0 = batch processing only (defer change detection to v1.1)

---

## 🏗️ Architecture at a Glance

```
Phase 1 (Scrapers)
  ↓ Pub/Sub: nba-phase1-scrapers-complete
Phase 2 (Raw Processing) - 21 processors
  ↓ Pub/Sub: nba-phase2-raw-complete (21 messages)
Phase 3 (Analytics) - 5 processors
  ↓ Each publishes when done
  ↓ Orchestrator tracks all 5
  ↓ When ALL complete → trigger Phase 4
Phase 4 (Precompute) - 5 processors
  ↓ Level 1 (3 processors, parallel)
  ↓ Level 2 (1 processor, depends on Level 1)
  ↓ Level 3 (1 processor, depends on all)
  ↓ Orchestrator manages cascade
  ↓ Pub/Sub: nba-phase4-precompute-complete
Phase 5 (Predictions)
  ↓ /trigger endpoint (PRIMARY, from Pub/Sub)
  ↓ /start endpoint (BACKUP, from scheduler at 6 AM)
  ↓ /retry endpoints (6:15 AM, 6:30 AM)
  ↓ Fan-out to 450 workers
  ↓ Predictions ready!
```

---

## 🔑 Key Decisions

### 1. No Orchestrator for Phase 2→3
- Each Phase 3 processor depends on DIFFERENT Phase 2 tables
- Dependency checks handle coordination
- Multiple triggers are okay (deduplication prevents waste)

### 2. YES Orchestrators for Phase 3→4 and Phase 4 Internal
- Cloud Functions + Firestore
- Tracks completion, triggers next phase when ready
- Clean, efficient, debuggable

### 3. Correlation ID Everywhere
- Phase 1 sets it: `correlation_id = execution_id`
- Phases 2-5 propagate it
- Enables tracing: prediction → scraper run

### 4. Backfill Mode Support
- New fields: `skip_downstream_trigger`, `backfill_mode`
- Load historical data without triggering predictions
- Manual override for testing

### 5. Defer Change Detection to v1.1
- v1.0 = batch processing only (simple, testable)
- v1.1 = add change detection (process only changed entities)
- Focus on getting pipeline working first

---

## 📋 Week-by-Week Overview

### Week 1: Foundation
- Create UnifiedPubSubPublisher
- Update Phase 1 (add unified fields)
- Update Phase 2 (extract correlation_id, publish unified format)
- Test: Phase 1→2 with backfill data

### Week 2: Phase 3 + Orchestrator
- Update Phase 3 (unified format)
- Build Phase 3→4 orchestrator (Cloud Function + Firestore)
- Test: Phase 1→2→3→4 triggered correctly

### Week 3: Phase 4-5
- Update Phase 4 (unified format)
- Build Phase 4 internal orchestrator
- Update Phase 5 (/trigger, /start, /retry endpoints)
- Test: Complete pipeline Phase 1→2→3→4→5

### Week 4: Deploy & Monitor
- Deploy all services
- Create Pub/Sub topics
- Create orchestrators
- Monitor first overnight run
- Create dashboards

---

## 🚀 Getting Started (First Day)

### Step 1: Environment Setup (30 min)

```bash
# Clone repo (if not already)
cd ~/code/nba-stats-scraper

# Check GCP authentication
gcloud auth list
gcloud config set project nba-props-platform

# Install dependencies
pip install -r requirements.txt

# Run existing tests to ensure nothing broken
pytest tests/ -v
```

### Step 2: Read Documentation (80 min)

- Read in order listed at top of this guide
- Take notes on unclear parts
- Prepare questions

### Step 3: Create First Component (3 hours)

**Task:** Create UnifiedPubSubPublisher class

```bash
# Create new file
touch shared/utils/unified_pubsub_publisher.py

# Create test file
touch tests/shared/test_unified_pubsub_publisher.py
```

**Implementation:** See V1.0-IMPLEMENTATION-PLAN.md Week 1 Day 1

**Test:**
```bash
pytest tests/shared/test_unified_pubsub_publisher.py -v
```

### Step 4: Update Phase 1 (4 hours)

**Task:** Add unified format fields to ScraperPubSubPublisher

**Files to modify:**
- `scrapers/utils/pubsub_utils.py`

**Test:**
```bash
# Run a test scraper
python -m scrapers.bdl.games_scraper --game_date=2025-01-15 --test_mode=true

# Check Pub/Sub message in console
gcloud pubsub topics publish nba-phase1-scrapers-complete \
    --message="test" \
    --project=nba-props-platform

# View message
gcloud pubsub subscriptions pull nba-phase2-raw-sub \
    --limit=1 \
    --project=nba-props-platform
```

---

## 🧪 Testing Strategy

### Unit Tests
- Test each new class/function in isolation
- Target: >90% coverage
- Use pytest + unittest.mock

### Integration Tests
- Test Phase 1→2 end-to-end
- Test Phase 1→2→3 end-to-end
- Test full pipeline Phase 1→2→3→4→5
- Use test data (specific game dates)

### Manual Testing
- Test backfill mode (skip_downstream_trigger)
- Test correlation_id propagation
- Test orchestrator tracking (Firestore console)
- Test failure scenarios (processor fails, Pub/Sub fails)

---

## 🔍 Debugging Tips

### Check Pub/Sub Message
```bash
# Pull message from subscription (doesn't ACK)
gcloud pubsub subscriptions pull SUBSCRIPTION_NAME \
    --limit=1 \
    --project=nba-props-platform
```

### Check Processor Run History
```sql
SELECT *
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = '2025-01-15'
  AND processor_name LIKE '%Player%'
ORDER BY processed_at DESC
LIMIT 10
```

### Check Orchestrator State (Firestore)
```bash
# View Firestore documents
gcloud firestore databases list --project=nba-props-platform

# Or use Firebase console:
# https://console.firebase.google.com/project/nba-props-platform/firestore
```

### Check Cloud Run Logs
```bash
gcloud run services logs read SERVICE_NAME \
    --project=nba-props-platform \
    --region=us-west2 \
    --limit=50
```

### Trace Correlation ID
```sql
-- Find all runs with same correlation_id
SELECT
    processor_name,
    phase,
    data_date,
    status,
    processed_at,
    correlation_id
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE correlation_id = 'abc-123-correlation-id'
ORDER BY processed_at
```

---

## ⚠️ Common Pitfalls

### 1. Forgetting Backfill Mode
**Symptom:** Backfilling historical data triggers predictions for old games

**Fix:** Always set `skip_downstream_trigger=true` when backfilling

### 2. Not Propagating Correlation ID
**Symptom:** Can't trace predictions back to scraper

**Fix:** Extract from upstream message, include in downstream message

### 3. Skipping Deduplication Check
**Symptom:** Processor runs twice for same date

**Fix:** Call `self._already_processed()` at start of run()

### 4. Ignoring Orchestrator State
**Symptom:** Phase 4 triggers before Phase 3 complete

**Fix:** Check Firestore state, ensure all dependencies tracked

### 5. Not Testing with Real Data
**Symptom:** Works with test data, fails with production data

**Fix:** Test with actual historical game dates (2024-01-15, etc.)

---

## 📊 Progress Tracking

Use this checklist to track your progress:

**Week 1:**
- [ ] UnifiedPubSubPublisher created and tested
- [ ] Phase 1 updated (unified format + correlation_id)
- [ ] Phase 2 updated (extract correlation_id, publish unified)
- [ ] End-to-end test Phase 1→2 passing
- [ ] Backfill mode tested

**Week 2:**
- [ ] Phase 3 updated (unified format)
- [ ] Phase 3→4 orchestrator deployed
- [ ] Orchestrator tracks all 5 Phase 3 processors
- [ ] Phase 4 triggered when all 5 complete
- [ ] End-to-end test Phase 1→2→3→4 passing

**Week 3:**
- [ ] Phase 4 updated (unified format)
- [ ] Phase 4 internal orchestrator deployed
- [ ] Phase 5 /trigger endpoint working
- [ ] Phase 5 /start backup working
- [ ] Phase 5 /retry endpoints working
- [ ] End-to-end test Phase 1→5 passing

**Week 4:**
- [ ] All unit tests passing (>90% coverage)
- [ ] All integration tests passing
- [ ] Production deployment successful
- [ ] First overnight run completed
- [ ] Monitoring dashboards created
- [ ] Alerts configured

---

## 🆘 When You're Stuck

### 1. Check Documentation
- UNIFIED-ARCHITECTURE-DESIGN.md for technical details
- V1.0-IMPLEMENTATION-PLAN.md for step-by-step instructions
- ARCHITECTURE-DECISIONS.md for rationale

### 2. Look at Existing Code
- Phase 2 has similar patterns (ProcessorBase)
- Phase 3 has analytics patterns (AnalyticsProcessorBase)
- RunHistoryMixin shows deduplication implementation

### 3. Test in Isolation
- Create small test script
- Test one component at a time
- Use mocks for dependencies

### 4. Check GCP Console
- Pub/Sub: View messages in topics
- Cloud Run: View logs in real-time
- Firestore: View orchestrator state
- BigQuery: Query processor_run_history

### 5. Ask Questions
- Review code comments
- Check previous handoff documents
- Consult with team members

---

## 📈 Success Criteria

**You'll know it's working when:**

1. **Phase 1→2:**
   - Scraper publishes message with correlation_id
   - Phase 2 receives and processes
   - Phase 2 publishes with same correlation_id
   - Backfill mode skips downstream

2. **Phase 2→3:**
   - Each Phase 2 processor publishes
   - Phase 3 receives multiple triggers
   - Deduplication prevents duplicate work
   - All 5 Phase 3 processors complete

3. **Phase 3→4:**
   - Orchestrator tracks all 5 Phase 3 processors
   - Firestore shows completion state
   - Phase 4 triggered ONCE when all complete

4. **Phase 4 Internal:**
   - Level 1 processors run in parallel
   - Level 2 waits for Level 1
   - Level 3 waits for all
   - Orchestrator manages cascade

5. **Phase 4→5:**
   - ml_feature_store_v2 publishes completion
   - Phase 5 /trigger receives event
   - Validates Phase 4 ready
   - Generates predictions

6. **End-to-End:**
   - Trace correlation_id from scraper → prediction
   - Latency <60 minutes
   - >95% predictions generated
   - Backfill doesn't trigger predictions

---

## 🎓 Key Concepts to Understand

### Event-Driven Architecture
- Processors triggered by events (Pub/Sub messages), not time
- Faster, more efficient, scales better
- Requires deduplication (at-least-once delivery)

### Correlation ID
- Unique ID from original scraper run
- Propagated through entire pipeline
- Enables tracing and debugging

### Deduplication
- Check if already processed before running
- Uses processor_run_history table
- Prevents duplicate work on retries

### Orchestration
- Tracks dependencies across processors
- Triggers next phase when ready
- Uses Firestore for atomic state

### Backfill Mode
- Process historical data without downstream triggers
- Essential for loading past seasons
- Controlled via skip_downstream_trigger flag

---

## 🔗 Useful Links

**GCP Console:**
- Pub/Sub Topics: https://console.cloud.google.com/cloudpubsub/topic/list?project=nba-props-platform
- Cloud Run: https://console.cloud.google.com/run?project=nba-props-platform
- Firestore: https://console.firebase.google.com/project/nba-props-platform/firestore
- BigQuery: https://console.cloud.google.com/bigquery?project=nba-props-platform

**Code References:**
- Phase 1 Publisher: `/scrapers/utils/pubsub_utils.py`
- Phase 2 Base: `/data_processors/raw/processor_base.py`
- Phase 3 Base: `/data_processors/analytics/analytics_base.py`
- Phase 4 Base: `/data_processors/precompute/precompute_base.py`
- Phase 5 Coordinator: `/predictions/coordinator/coordinator.py`
- RunHistoryMixin: `/shared/processors/mixins/run_history_mixin.py`

---

**Ready to start?** Begin with Week 1 Day 1 in V1.0-IMPLEMENTATION-PLAN.md!

**Questions?** Review ARCHITECTURE-DECISIONS.md for rationale behind design choices.

**Good luck!** 🚀
