# Handoff: Phase 3 Topics Deployed - Ready for Code Updates

**Date:** 2025-11-16
**Session Focus:** Topic naming convention + infrastructure deployment + documentation updates
**Status:** Infrastructure complete, code updates needed
**Next Session:** Update scrapers for dual publishing + create Phase 2 publisher

---

## ✅ What We Accomplished This Session

### **1. Established Topic Naming Convention (Hybrid Approach)**

**Decision:** `nba-phase{N}-{content}-complete` format

```
Phase 1 → 2:  nba-phase1-scrapers-complete
Phase 2 → 3:  nba-phase2-raw-complete
Phase 3 → 4:  nba-phase3-analytics-complete
Phase 4 → 5:  nba-phase4-precompute-complete
Phase 5 → 6:  nba-phase5-predictions-complete

DLQs: Add -dlq suffix (e.g., nba-phase1-scrapers-complete-dlq)
Fallbacks: nba-phase{N}-fallback-trigger (triggers Phase N if events fail)
```

**Why hybrid:** Combines phase number (where) + content type (what) for maximum clarity

---

### **2. Infrastructure Deployed (11 Topics, 7 Subscriptions)**

**Phase 1 → 2 (Migration Ready):**
```
✅ nba-phase1-scrapers-complete          (NEW topic)
✅ nba-phase1-scrapers-complete-dlq      (NEW DLQ)
✅ nba-scraper-complete                   (OLD - still working)
✅ nba-scraper-complete-dlq               (OLD)

Subscriptions:
✅ nba-processors-sub → nba-scraper-complete (OLD - Phase 2 receiving)
✅ nba-processors-sub-v2 → nba-phase1-scrapers-complete (NEW - Phase 2 ready)
✅ nba-phase1-scrapers-complete-dlq-sub (DLQ monitoring)
```

**Phase 2 → 3 (Ready for Publishing):**
```
✅ nba-phase2-raw-complete                (NEW topic)
✅ nba-phase2-raw-complete-dlq            (NEW DLQ)

Subscriptions:
✅ nba-phase3-analytics-sub → nba-phase2-raw-complete
   (Push to: https://nba-analytics-processors-f7p3g7f6ya-wl.a.run.app/process)
✅ nba-phase2-raw-complete-dlq-sub (DLQ monitoring)
```

**Fallback Triggers (All Phases):**
```
✅ nba-phase2-fallback-trigger  (triggers Phase 2 if Phase 1 fails)
✅ nba-phase3-fallback-trigger  (triggers Phase 3 if Phase 2 fails)
✅ nba-phase4-fallback-trigger  (triggers Phase 4 if Phase 3 fails)
✅ nba-phase5-fallback-trigger  (triggers Phase 5 if Phase 4 fails)
✅ nba-phase6-fallback-trigger  (triggers Phase 6 if Phase 5 fails)
```

**BigQuery Schemas:**
```
✅ nba_analytics dataset exists
✅ 5 tables exist (player_game_summary, team_offense_game_summary, etc.)
✅ All partitioned by game_date (critical for performance)
```

---

### **3. Configuration Files Created**

**Centralized Topic Config:**
```
✅ shared/config/pubsub_topics.py (200+ lines)
   - All topic names as constants (TOPICS.PHASE1_SCRAPERS_COMPLETE, etc.)
   - Helper methods: get_all_topics(), get_phase_topics(N)
   - Single source of truth - NEVER hardcode topic names!
```

**Infrastructure Scripts:**
```
✅ bin/infrastructure/create_phase2_phase3_topics.sh (EXECUTED)
✅ bin/infrastructure/create_all_fallback_triggers.sh (EXECUTED)
✅ bin/infrastructure/migrate_phase1_topic.sh (Step 1 complete)
✅ bin/infrastructure/README.md (usage guide)
```

**Documentation:**
```
✅ docs/TOPIC_MIGRATION_DOC_UPDATES.md (16 docs need updates)
✅ docs/INFRASTRUCTURE_DEPLOYMENT_SUMMARY.md (complete summary)
✅ SCRAPER_UPDATE_PLAN.md (detailed scraper update guide)
✅ THIS FILE (handoff for next session)
```

---

### **4. Documentation Updated (5 Priority 1 Docs)**

```
✅ docs/architecture/04-event-driven-pipeline-architecture.md
✅ docs/architecture/05-implementation-status-and-roadmap.md
✅ docs/processors/01-phase2-operations-guide.md
✅ docs/processors/02-phase3-operations-guide.md
✅ docs/processors/PHASE3_DEPLOYMENT_READINESS.md
```

All topic names updated to new convention.

**Remaining docs to update:** 11 docs (Priority 2 & 3) - see `docs/TOPIC_MIGRATION_DOC_UPDATES.md`

---

## 🎯 Current State

### **Phase 1 → 2 (Working, Migration in Progress)**
- **Status:** Dual infrastructure exists
- **Scrapers:** Still publishing to OLD topic only (`nba-scraper-complete`)
- **Phase 2:** Listening to BOTH old and new topics
- **Next:** Update scrapers for dual publishing

### **Phase 2 → 3 (Infrastructure Ready, Code Needed)**
- **Status:** Infrastructure deployed, waiting for Phase 2 code
- **Phase 2:** NOT publishing yet (Gap #1 - CRITICAL)
- **Phase 3:** Service deployed, subscription ready
- **Next:** Create Phase 2 publisher utility

### **Phase 3 → 4 (Future)**
- **Status:** Not deployed yet (Phase 4 doesn't exist)
- **Fallback triggers:** Created for future use

---

## 🚀 Next Steps (Exact Order)

### **Step 1: Update Scrapers for Dual Publishing** (30 min)

**File to update:** `scrapers/utils/pubsub_utils.py` (ONLY THIS FILE!)

**Changes needed:**
1. Add import:
   ```python
   from shared.config.pubsub_topics import TOPICS
   ```

2. Update `__init__` method (lines 52-66):
   - Add `dual_publish=True` parameter
   - Create paths for BOTH old and new topics
   - Use `TOPICS.PHASE1_SCRAPERS_COMPLETE` for new topic

3. Update `publish_completion_event` method (lines 148-183):
   - Publish to NEW topic (always)
   - Also publish to OLD topic if `dual_publish=True`
   - Don't fail if old topic publish fails

**Full details:** See `SCRAPER_UPDATE_PLAN.md`

**Why only one file?**
- All 26+ scrapers inherit from `ScraperBase`
- `ScraperBase` automatically uses `ScraperPubSubPublisher`
- Zero changes to individual scrapers!

**Test before deploy:**
```bash
python -c "
from scrapers.utils.pubsub_utils import ScraperPubSubPublisher
publisher = ScraperPubSubPublisher()
message_id = publisher.publish_completion_event(
    scraper_name='test_dual',
    execution_id='test-123',
    status='success',
    record_count=1
)
print(f'Test: {message_id}')
"
```

**Deploy:**
```bash
cd scrapers
gcloud run deploy nba-scrapers \
  --source . \
  --region us-west2 \
  --project nba-props-platform
```

---

### **Step 2: Verify Dual Publishing** (24 hours monitoring)

**Check both topics receiving messages:**
```bash
# Check new topic
gcloud pubsub subscriptions pull nba-processors-sub-v2 --limit=5 --auto-ack

# Check old topic
gcloud pubsub subscriptions pull nba-processors-sub --limit=5 --auto-ack
```

**Verify Phase 2 processing from both subscriptions:**
```bash
# Phase 2 logs
gcloud run services logs read nba-processors --region=us-west2 --limit=20
```

**Monitor for errors:**
```bash
# Check DLQ depth (should be 0)
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

---

### **Step 3: Create Phase 2 Publisher Utility** (1 hour)

**New file:** `shared/utils/pubsub_publishers.py`

**Content:**
```python
from shared.config.pubsub_topics import TOPICS
from google.cloud import pubsub_v1

class RawDataPubSubPublisher:
    """Publishes Phase 2 completion events to trigger Phase 3."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(
            project_id,
            TOPICS.PHASE2_RAW_COMPLETE  # "nba-phase2-raw-complete"
        )

    def publish_raw_data_loaded(
        self,
        source_table: str,
        game_date: str,
        record_count: int,
        execution_id: str,
        correlation_id: str = None,
        success: bool = True
    ) -> str:
        """Publish Phase 2 completion event."""
        message_data = {
            'event_type': 'raw_data_loaded',
            'source_table': source_table,
            'game_date': game_date,
            'record_count': record_count,
            'execution_id': execution_id,
            'correlation_id': correlation_id or execution_id,
            'timestamp': datetime.utcnow().isoformat(),
            'phase': 2,
            'success': success
        }

        future = self.publisher.publish(
            self.topic_path,
            json.dumps(message_data).encode('utf-8')
        )

        message_id = future.result(timeout=5.0)
        logger.info(f"✅ Published raw_data_loaded: {source_table} for {game_date}")
        return message_id
```

**Pattern to copy:** `scrapers/utils/pubsub_utils.py` (already working for Phase 1)

---

### **Step 4: Update Phase 2 Base Class** (30 min)

**File:** `data_processors/raw/processor_base.py`

**Add after line 144 (after `save_data()` completes):**

```python
def save_data(self):
    """Save to BigQuery (existing code)"""
    # ... existing save logic ...

    # NEW: Publish completion event (non-blocking)
    self._publish_completion_event()

def _publish_completion_event(self):
    """Publish Phase 2 completion event to trigger Phase 3."""
    try:
        from shared.utils.pubsub_publishers import RawDataPubSubPublisher

        # Only publish if we have the required info
        game_date = self.opts.get('date') or self.opts.get('game_date')
        if not game_date:
            logger.debug("No game_date in opts, skipping publish")
            return

        # Initialize publisher
        project_id = self.bq_client.project
        publisher = RawDataPubSubPublisher(project_id=project_id)

        # Publish event
        publisher.publish_raw_data_loaded(
            source_table=self.table_name,
            game_date=str(game_date),
            record_count=self.stats.get('rows_inserted', 0),
            execution_id=self.run_id,
            correlation_id=self.opts.get('correlation_id'),
            success=True
        )

        logger.info(f"Published Phase 2 completion: {self.table_name}")

    except Exception as e:
        # Log but DON'T fail the processor (non-blocking)
        logger.warning(f"Failed to publish completion event: {e}")
```

**Critical:** Publishing must NOT fail the processor! Always catch exceptions.

---

### **Step 5: Test Phase 2 → 3 Flow** (1 hour)

**Test with mock message:**
```bash
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message='{
    "event_type":"raw_data_loaded",
    "source_table":"nbac_gamebook_player_stats",
    "game_date":"2024-11-14",
    "record_count":450,
    "execution_id":"test-123",
    "timestamp":"2024-11-14T22:30:00Z",
    "phase":2,
    "success":true
  }'
```

**Verify Phase 3 receives and processes:**
```bash
# Check Phase 3 analytics service logs
gcloud run services logs read nba-analytics-processors \
  --region=us-west2 \
  --limit=20
```

**Expected Phase 3 behavior:**
- Receives message from `nba-phase3-analytics-sub`
- Checks dependencies (`nbac_gamebook_player_stats` exists for 2024-11-14?)
- Either processes (if deps ready) or skips gracefully (if deps missing)
- No errors

---

### **Step 6: Deploy Phase 2 with Publishing** (1 hour)

**After testing with mocks:**

```bash
cd data_processors/raw
gcloud run deploy nba-processors \
  --source . \
  --region us-west2 \
  --project nba-props-platform
```

**Trigger real Phase 2 processor:**
```bash
# Manually trigger one processor to test
# (Use your existing manual trigger method)
```

**Verify end-to-end:**
1. Phase 1 scraper runs → publishes to Phase 1 topic
2. Phase 2 receives → processes → publishes to Phase 2 topic
3. Phase 3 receives → checks deps → processes (or skips)
4. Data appears in `nba_analytics.*` tables

---

### **Step 7: Finalize Phase 1 Migration** (After 24 hours)

**After verifying dual publishing works:**

```bash
./bin/infrastructure/migrate_phase1_topic.sh finalize
```

**This will:**
1. Prompt you to disable dual publishing in scrapers
2. Delete old `nba-processors-sub` subscription
3. Mark old topics for deletion (7-day safety period)

---

## 📊 Success Criteria

### **Scrapers (Phase 1)**
- ✅ Publishing to `nba-phase1-scrapers-complete` (new)
- ✅ Publishing to `nba-scraper-complete` (old, during migration)
- ✅ Phase 2 receiving from both subscriptions
- ✅ No errors in scraper logs

### **Phase 2 → 3 Integration**
- ✅ Phase 2 publishes to `nba-phase2-raw-complete`
- ✅ Phase 3 receives events via `nba-phase3-analytics-sub`
- ✅ Phase 3 checks dependencies correctly
- ✅ Data appears in `nba_analytics.*` tables
- ✅ No data loss
- ✅ DLQ depth = 0 (no systematic failures)

---

## 🔧 Key Files Reference

**Configuration:**
- `shared/config/pubsub_topics.py` - Single source of truth for topic names

**Phase 1 (Scrapers):**
- `scrapers/utils/pubsub_utils.py` - UPDATE for dual publishing
- `scrapers/scraper_base.py` - No changes needed (uses pubsub_utils)

**Phase 2 (Raw Processors):**
- `shared/utils/pubsub_publishers.py` - CREATE Phase 2 publisher
- `data_processors/raw/processor_base.py` - UPDATE to publish after save_data()

**Phase 3 (Analytics):**
- `data_processors/analytics/main_analytics_service.py` - Already deployed ✅
- `data_processors/analytics/analytics_base.py` - Already has dependency checking ✅

**Infrastructure Scripts:**
- `bin/infrastructure/migrate_phase1_topic.sh` - Phase 1 migration tool
- `bin/infrastructure/create_phase2_phase3_topics.sh` - Already executed ✅
- `bin/infrastructure/create_all_fallback_triggers.sh` - Already executed ✅

**Documentation:**
- `SCRAPER_UPDATE_PLAN.md` - Detailed scraper update guide
- `docs/INFRASTRUCTURE_DEPLOYMENT_SUMMARY.md` - Infrastructure summary
- `docs/TOPIC_MIGRATION_DOC_UPDATES.md` - Doc update tracker

---

## ⚠️ Important Notes

1. **Never hardcode topic names** - Always use `TOPICS.*` constants from `shared/config/pubsub_topics.py`

2. **Publishing must not fail processors** - All Pub/Sub publishing should be wrapped in try/except, log errors but don't throw

3. **Dual publishing is temporary** - After 24-48 hours verification, disable and clean up

4. **DLQ monitoring is critical** - Set up alerts for DLQ depth > 0

5. **Test with mocks first** - Don't test directly in production without mock validation

---

## 🚨 If Something Goes Wrong

**Scraper publishing fails:**
- Check scraper logs for Pub/Sub errors
- Verify topic exists: `gcloud pubsub topics describe nba-phase1-scrapers-complete`
- Verify IAM permissions for scraper service account

**Phase 2 → 3 events not flowing:**
- Check subscription exists: `gcloud pubsub subscriptions describe nba-phase3-analytics-sub`
- Check Phase 3 service logs: `gcloud run services logs read nba-analytics-processors`
- Verify push endpoint URL is correct

**Messages stuck in DLQ:**
- Pull messages to inspect: `gcloud pubsub subscriptions pull [DLQ-SUB] --limit=10`
- Check Phase 3 service for errors processing those specific messages
- Fix issue, then replay from DLQ

**Rollback Phase 1 migration:**
- Revert `scrapers/utils/pubsub_utils.py` to original
- Redeploy scrapers
- Old flow continues working (no data loss)

---

## 📝 Prompt for Next Chat Session

```
I'm continuing Phase 3 deployment for the NBA stats scraper. We just completed:

1. ✅ Created new topic naming convention (nba-phase{N}-{content}-complete)
2. ✅ Deployed all infrastructure (11 topics, 7 subscriptions)
3. ✅ Updated Priority 1 documentation (5 docs)
4. ✅ Created Phase 1 migration infrastructure (dual publishing ready)
5. ✅ Created centralized config (shared/config/pubsub_topics.py)

Current state:
- Phase 1→2: Working, ready for dual publishing migration
- Phase 2→3: Infrastructure ready, code updates needed
- All fallback triggers created for safety nets

Next steps:
1. Update scrapers/utils/pubsub_utils.py for dual publishing (only 1 file!)
2. Create Phase 2 publisher utility (shared/utils/pubsub_publishers.py)
3. Update Phase 2 base class to publish completion events
4. Test Phase 2→3 flow end-to-end

Please read:
- docs/HANDOFF-2025-11-16-phase3-topics-deployed.md (complete context)
- SCRAPER_UPDATE_PLAN.md (scraper update details)
- shared/config/pubsub_topics.py (topic name constants)

Let's start with updating the scraper publisher for dual publishing.
```

---

**Session Complete:** 2025-11-16
**Next Session:** Code updates for Phase 1 dual publishing + Phase 2→3 integration
**Files to Review:** See prompt above
**Estimated Time Remaining:** 4-6 hours (spread over 2-3 days for migration verification)
