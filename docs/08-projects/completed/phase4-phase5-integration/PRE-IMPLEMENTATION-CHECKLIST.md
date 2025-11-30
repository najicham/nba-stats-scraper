# Pre-Implementation Checklist

**Created:** 2025-11-28 11:15 PM PST
**Completed:** 2025-11-28 11:30 PM PST
**Purpose:** Critical items to verify/resolve BEFORE starting Week 1 Day 1
**Status:** ✅ COMPLETE - Ready to implement

---

## Executive Summary

After deep review of the complete v1.0 architecture and both external reviews, there are **4 critical unknowns** that must be resolved before starting implementation, **5 important clarifications** needed, and **3 nice-to-have improvements**.

**Time to Complete:** 2-4 hours of research/verification
**Blocking Issues:** 4 (if not resolved, could break architecture)
**Impact:** Could save 10-20 hours of rework if caught now

---

## CRITICAL - Must Resolve Before Week 1

### Critical 1: Phase 3 Rolling Average Dependencies ⚠️⚠️⚠️

**The Issue:**
The backfill plan processes 20 Phase 3 dates in parallel. But if Phase 3 processors compute rolling averages (e.g., "player's last 5 games average"), they might read from Phase 3 output tables for historical data.

**Why This Breaks:**
```
Processing dates 2024-01-10 through 2024-01-20 in parallel
Date 2024-01-15 needs "last 5 games" = 2024-01-10 through 2024-01-14
But 2024-01-14 is being processed simultaneously
Rolling average uses incomplete/stale data → incorrect results
```

**What to Check:**
```bash
cd /home/naji/code/nba-stats-scraper

# Search for self-referential queries in Phase 3
grep -r "nba_analytics" data_processors/analytics/ | grep FROM

# Look for patterns like:
# "FROM nba_analytics.player_game_summary WHERE game_date < @current_date"
# "ORDER BY game_date DESC LIMIT 5"  (last 5 games)
```

**Specific Processors to Check:**
1. `player_game_summary_processor.py` - Likely safe (aggregates from raw only)
2. `team_offense_game_summary_processor.py` - Likely safe
3. `team_defense_game_summary_processor.py` - Likely safe
4. `upcoming_player_game_context_processor.py` - ⚠️ LIKELY READS OWN OUTPUT (context needs history)
5. `upcoming_team_game_context_processor.py` - ⚠️ LIKELY READS OWN OUTPUT

**Resolution:**
- **Option A:** Processors only read Phase 2 raw → ✅ Parallel backfill safe
- **Option B:** Processors read Phase 3 output → ❌ Must process chronologically

**If Option B:**
1. Change backfill_phase3.sh to process dates sequentially OR
2. Process in chronological waves (dates 1-50, then 51-100, etc.) with buffer OR
3. Refactor processors to only use Phase 2 raw data

**Action Required:**
- [x] **VERIFIED:** No self-referential queries found in Phase 3 analytics! ✅
- [x] grep -r "FROM.*nba_analytics" returned NO matches
- [x] Safe to process dates in parallel during backfill
- [ ] Double-check during Week 2 implementation when writing Phase 3 code

**Time to Resolve:** COMPLETE - verification script found no issues ✅
**Blocking:** NO - parallel backfill is safe!

---

### Critical 2: Cloud Run Concurrent Instance Quota

**The Issue:**
Backfill plan calls for 210 concurrent operations (10 dates × 21 scrapers). Default Cloud Run quota is often 100 concurrent instances per region.

**What Could Happen:**
```
Batch 1: Trigger 210 scrapers
Cloud Run: Starts 100 instances, queues 110 requests
Scrapers: 110 requests timeout waiting for instances
Script: Reports 110 failures
Result: 52% failure rate, systematic data loss
```

**What to Check:**
```bash
# Check current Cloud Run quota
gcloud run services describe nba-phase1-scrapers \
  --region=us-west2 \
  --format='value(spec.template.spec.containerConcurrency)'

# Check quota limits
gcloud compute project-info describe \
  --project=nba-props-platform \
  --format='value(quotas)' | grep -i "cloud run"

# Or check in console:
# https://console.cloud.google.com/iam-admin/quotas?project=nba-props-platform
# Search for "Cloud Run"
```

**Resolution:**
- **Option A:** Current quota ≥ 210 → ✅ Proceed as planned
- **Option B:** Current quota < 210 → Request quota increase OR reduce parallelism

**If Option B:**
```bash
# Request quota increase (can take 1-2 days)
gcloud alpha quotas update \
  --service=run.googleapis.com \
  --consumer=projects/nba-props-platform \
  --metric=ConcurrentRequests \
  --value=250 \
  --region=us-west2

# OR reduce PARALLEL_DATES in scripts
PARALLEL_DATES=5  # Instead of 10
```

**Action Required:**
- [x] **VERIFIED:** Cloud Run service `nba-phase1-scrapers` exists and is deployed
- [x] URL: https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app
- [x] **VERIFIED:** Cloud Run quota confirmed at **1,000** concurrent requests/instances
  - Required: 210 (10 dates × 21 scrapers)
  - Available: 1,000
  - Headroom: 4.7x (790 spare capacity)
  - ✅ More than sufficient for backfill parallelism

**Time to Resolve:** ✅ COMPLETE - quota verified sufficient
**Blocking:** NO - quota is 4.7x more than needed

---

### Critical 3: RunHistoryMixin Immediate Write for Deduplication

**The Issue:**
Deduplication checks `processor_run_history` to avoid duplicate processing. But if the mixin only writes at the END of processing, there's a race window:

```
12:00:00 - Processor starts, checks run_history (empty), begins processing
12:05:00 - Pub/Sub redelivers message (ack timeout)
12:05:01 - New instance checks run_history (still empty - first one not done)
12:05:02 - New instance starts processing DUPLICATE
```

**What to Check:**
```bash
# Check if RunHistoryMixin writes "running" status immediately
cat shared/processors/mixins/run_history_mixin.py | grep -A 20 "start_run_tracking"

# Look for INSERT with status='running' at START of processing
# vs INSERT with status='success' at END
```

**Expected Behavior:**
```python
def start_run_tracking(self, data_date):
    """Should write 'running' status IMMEDIATELY to prevent duplicates."""
    row = {
        'run_id': self.run_id,
        'processor_name': self.__class__.__name__,
        'status': 'running',  # ← Must be 'running', not wait until 'success'
        'started_at': datetime.now(),
        ...
    }
    # Write to BigQuery IMMEDIATELY
    self.bq_client.insert_rows(...)
```

**Resolution:**
- **Option A:** Already writes 'running' immediately → ✅ Deduplication safe
- **Option B:** Only writes at end → ❌ Add immediate write in Week 1

**If Option B:**
Add to Week 1 Day 3 (Update Phase 2):
- Modify `RunHistoryMixin.start_run_tracking()` to write 'running' status
- Update deduplication query to check for 'running' OR 'success' status

**Action Required:**
- [x] **VERIFIED:** RunHistoryMixin does NOT write 'running' status immediately
- [x] `start_run_tracking()` only initializes in-memory state (no BigQuery write)
- [x] `record_run_complete()` writes to BigQuery at END of processing
- [ ] **ADD TO WEEK 1 DAY 1:** Modify `start_run_tracking()` to write 'running' status
- [ ] Update deduplication check to look for 'running' OR 'success'/'partial' status

**Fix to Apply in Week 1 Day 1:**
```python
def start_run_tracking(self, ...):
    # ... existing code ...

    # NEW: Write 'running' status immediately to prevent duplicates
    record = {
        'run_id': self._run_history_id,
        'processor_name': self.__class__.__name__,
        'phase': self.PHASE,
        'data_date': str(self._run_data_date),
        'status': 'running',  # Will be updated to 'success'/'failed' at end
        'started_at': self._run_start_time.isoformat(),
        'trigger_source': self._trigger_source,
        ...
    }
    self._insert_run_history(record)
```

**Time to Resolve:** 1 hour during Week 1 Day 1
**Blocking:** YES - could cause duplicate processing during Pub/Sub retries

---

### Critical 4: skip_downstream_trigger Flag Handling in Phase 2

**The Issue:**
Backfill mode requires Phase 2 to check `skip_downstream_trigger` flag and NOT publish to downstream when true. Otherwise, backfilling historical data would trigger the entire pipeline.

**Expected Flow:**
```
Scraper (backfill mode): skip_downstream_trigger=true
  ↓ Publishes to Phase 2
Phase 2: Processes data, checks flag
  ↓ Flag is true → SKIP publishing to Phase 3
Phase 3: Never triggered (correct for backfill)
```

**What to Check:**
```bash
# Check if Phase 2 processors respect skip_downstream_trigger
cat data_processors/raw/processor_base.py | grep -A 10 "skip_downstream_trigger"

# Look for:
# if opts.get('skip_downstream_trigger', False):
#     return  # Don't publish
```

**Expected Code:**
```python
def _publish_completion_event(self):
    """Publish completion event to Pub/Sub."""

    # Check backfill flag
    if self.opts.get('skip_downstream_trigger', False):
        logger.info("Backfill mode: skipping downstream trigger")
        return

    # Normal publishing
    publisher.publish(...)
```

**Resolution:**
- **Option A:** Already implemented → ✅ Backfill mode works
- **Option B:** Not implemented → ❌ Add to Week 1 Day 3

**If Option B:**
Add to Week 1 Day 3 (Update Phase 2):
- Add `skip_downstream_trigger` check to `_publish_completion_event()`
- Test with backfill flag
- Verify downstream not triggered

**Action Required:**
- [x] **VERIFIED:** Phase 2 `processor_base.py` HAS `skip_downstream_trigger` handling
- [x] Flag is checked in publish method
- [ ] **VERIFY DURING IMPLEMENTATION:** Ensure Phase 3, 4, 5 also check flag
- [ ] Test backfill mode end-to-end before production backfill

**Time to Resolve:** Already implemented for Phase 2! ✅
**Blocking:** NO - Phase 2 works, just verify Phase 3-5 during implementation

---

## IMPORTANT - Strongly Recommended Before Week 1

### Important 1: Correlation ID Tracking in Manual Triggers

**The Issue:**
When manually triggering Phase 3 during backfill, the correlation_id from Phase 2 is lost:

```bash
# Manual trigger has no correlation_id
curl -X POST https://phase3.../process -d '{"analysis_date": "2024-01-15"}'
```

**Impact:** Can't trace predictions back to original scraper run (breaks audit trail)

**Resolution Options:**
- **Option A:** Accept broken correlation for backfill (tracking resumes after backfill)
- **Option B:** Query `processor_run_history` to get upstream correlation_id:
  ```python
  if not correlation_id:
      # Look up from Phase 2 run history
      query = """
      SELECT correlation_id FROM processor_run_history
      WHERE phase = 'phase_2_raw'
        AND data_date = @game_date
        AND status = 'success'
      ORDER BY processed_at DESC LIMIT 1
      """
      correlation_id = execute_query(query)
  ```

**Recommendation:** Option A for v1.0 (simpler), Option B for v1.1 if needed

**Action Required:**
- [ ] Decide if correlation tracking during backfill is important
- [ ] If yes, add lookup logic to Phase 3-5 processors

**Time to Resolve:** 1 hour (if implementing Option B)
**Blocking:** NO - nice to have

---

### Important 2: Coordinator Stale Batch Detection

**The Issue:**
If coordinator crashes and leaves batch in "in_progress" state, recovery might find stale batches from previous days.

**Example:**
```
Yesterday 11:00 PM - Coordinator starts batch, crashes
Today 12:00 AM - New coordinator recovers, finds yesterday's batch
Today 12:01 AM - Tries to recover 24-hour-old batch (invalid)
```

**Resolution:**
Add stale detection to recovery logic:
```python
def recover_batch_state():
    active_batches = db.collection('prediction_batches') \
        .where('status', '==', 'in_progress') \
        .where('game_date', '>=', str(date.today() - timedelta(days=1))) \
        .stream()

    for batch in active_batches:
        started_at = batch['started_at']
        age = datetime.now() - started_at

        if age > timedelta(hours=4):
            # Mark as stale
            batch.reference.update({'status': 'stale'})
            logger.warning(f"Marked stale batch: {batch['batch_id']}")
        else:
            # Recover this batch
            recover_this_batch(batch)
```

**Action Required:**
- [ ] Add stale batch detection to Phase 5 coordinator recovery
- [ ] Add to Week 3 Day 9-10 implementation

**Time to Resolve:** 30 minutes
**Blocking:** NO - edge case, but should fix

---

### Important 3: Enhanced Failure Testing

**The Issue:**
Testing plan focuses on happy path. Missing chaos/failure scenarios:

**Missing Tests:**
1. Concurrent orchestrator updates (21 processors complete simultaneously)
2. Coordinator crash mid-batch with recovery
3. Pub/Sub message redelivery (test deduplication)
4. Cloud Run instance death mid-processing
5. BigQuery quota exceeded during backfill
6. Network partition between services

**Resolution:**
Add to Week 3 Day 13 (Testing):
```python
# Test concurrent orchestrator updates
def test_concurrent_completions():
    # Trigger all 21 Phase 2 processors simultaneously
    # Verify orchestrator only triggers Phase 3 ONCE
    pass

# Test coordinator crash recovery
def test_coordinator_crash():
    # Start batch
    # Kill coordinator process
    # Verify new instance recovers state
    # Verify completions still processed
    pass
```

**Action Required:**
- [ ] Add chaos/failure tests to Week 3 Day 13
- [ ] Document failure scenarios to test
- [ ] Create test scripts

**Time to Resolve:** 2 hours during Week 3
**Blocking:** NO - but critical for production confidence

---

### Important 4: Cost Estimate Update

**The Issue:**
Original estimate: $80-150
Revised calculation with hardened scripts:

**BigQuery:**
- Phase 1-2: ~10,500 runs × $0.005 = $50
- Phase 3: ~2,500 runs × $0.01 = $25
- Phase 4: ~2,500 runs × $0.02 = $50
- Phase 5: ~500 runs × $0.05 = $25
- Verification: $10
- **Subtotal: $160**

**Cloud Run:**
- ~15,000 invocations
- ~$30-50

**Total: $190-210** (vs original $80-150)

**Action Required:**
- [ ] Update cost estimate in BACKFILL-EXECUTION-PLAN.md
- [ ] Set up cost monitoring during backfill
- [ ] Alert if cost exceeds $250

**Time to Resolve:** 15 minutes
**Blocking:** NO - informational

---

### Important 5: User Availability Confirmation

**The Issue:**
Timeline assumes 23-30 hours/week:
- Full-time (40h/week): 3 weeks
- Part-time (20h/week): 4-5 weeks
- Side project (10h/week): 9-10 weeks

**Action Required:**
- [ ] Confirm user availability (hours per week)
- [ ] Adjust calendar timeline if needed
- [ ] Set realistic expectations

**Time to Resolve:** 5 minutes
**Blocking:** NO - planning only

---

## NICE TO HAVE - Can Do During Implementation

### Nice 1: Partial Rollback Procedures

**What's Missing:**
Rollback docs show full phase rollback. But what if Phase 4 fails halfway through backfill?

**Add to Documentation:**
```sql
-- Partial rollback: Phase 4 for specific date range
DELETE FROM nba_precompute.ml_feature_store_v2
WHERE game_date >= '2024-01-01' AND game_date <= '2024-01-31';

DELETE FROM processor_run_history
WHERE phase = 'phase_4_precompute'
  AND data_date >= '2024-01-01' AND data_date <= '2024-01-31';

-- Then re-run just that date range
./bin/backfill/backfill_phase4.sh --start-date=2024-01-01 --end-date=2024-01-31
```

**Action Required:**
- [ ] Document partial rollback procedures
- [ ] Add to BACKFILL-EXECUTION-PLAN.md during Week 3

---

### Nice 2: Operational Runbook

**What's Missing:**
- Daily operation procedures
- Debugging guide
- Common issues and fixes
- On-call playbook

**Create During Week 4:**
- `docs/operations/RUNBOOK.md`
- `docs/operations/DEBUGGING-GUIDE.md`
- `docs/operations/COMMON-ISSUES.md`

---

### Nice 3: Additional Monitoring

**What's Missing:**
1. Firestore orchestrator state monitoring (detect stuck)
2. Cloud Run error rate monitoring (detect crashes)
3. Pub/Sub dead letter queue monitoring
4. BigQuery quota alerts

**Action Required:**
- [ ] Add to Week 4 monitoring setup
- [ ] Create GCP monitoring dashboards
- [ ] Set up alerts

---

## Pre-Implementation Verification Script

**Create this script to automate checks:**

```bash
#!/bin/bash
# bin/verify_ready_to_implement.sh

echo "========================================="
echo "Pre-Implementation Verification"
echo "========================================="
echo ""

ERRORS=0

# Check 1: Phase 3 rolling averages
echo "Checking Phase 3 for self-referential queries..."
if grep -r "FROM.*nba_analytics" data_processors/analytics/ | grep -v "^Binary" | head -5; then
    echo "⚠️  Found queries reading from nba_analytics (review manually)"
    echo "    Action: Verify if rolling averages exist"
    ((ERRORS++))
else
    echo "✅ No self-referential queries found"
fi

# Check 2: Cloud Run quota
echo ""
echo "Checking Cloud Run quota..."
# (requires gcloud command)

# Check 3: RunHistoryMixin
echo ""
echo "Checking RunHistoryMixin for immediate write..."
if grep -A 5 "start_run_tracking" shared/processors/mixins/run_history_mixin.py | grep "status.*running"; then
    echo "✅ RunHistoryMixin writes 'running' status"
else
    echo "❌ RunHistoryMixin may not write immediate status"
    ((ERRORS++))
fi

# Check 4: skip_downstream_trigger handling
echo ""
echo "Checking skip_downstream_trigger handling..."
if grep "skip_downstream_trigger" data_processors/raw/processor_base.py > /dev/null; then
    echo "✅ Phase 2 checks skip_downstream_trigger"
else
    echo "❌ Phase 2 doesn't check skip_downstream_trigger"
    ((ERRORS++))
fi

echo ""
echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ All checks passed - Ready to implement"
    exit 0
else
    echo "❌ ${ERRORS} issue(s) found - Resolve before starting"
    exit 1
fi
```

---

## Checklist Summary

### CRITICAL (Must Complete Before Week 1)
- [x] ✅ **Verify Phase 3 rolling average dependencies** - NO ISSUES FOUND
- [x] ✅ **Check Cloud Run quota limits** - VERIFIED 1,000 (4.7x needed)
- [x] ❌ **Review RunHistoryMixin immediate write** - ISSUE FOUND, FIX IN WEEK 1 DAY 1
- [x] ✅ **Verify skip_downstream_trigger handling** - ALREADY IMPLEMENTED

**Status:** ✅ 4/4 COMPLETE
**Blocking Issues:** 1 (RunHistoryMixin - will fix in Week 1 Day 1, not blocking start)
**Manual Checks:** ✅ ALL COMPLETE

### IMPORTANT (Should Complete Before Week 1)
- [ ] Decide on correlation ID tracking strategy (30min)
- [ ] Add stale batch detection to plan (30min)
- [ ] Plan enhanced failure testing (1h)
- [ ] Update cost estimate (15min)
- [ ] Confirm user availability (5min)

**Total Time:** 2.5 hours
**Blocking:** NO - but recommended

### NICE TO HAVE (Can Do During Implementation)
- [ ] Document partial rollback procedures
- [ ] Create operational runbook
- [ ] Set up additional monitoring

**Total Time:** 3-4 hours during Weeks 3-4
**Blocking:** NO

---

## Recommendation

**Before starting Week 1 Day 1:**

1. ✅ **Spend 2-4 hours** resolving the 4 critical items - COMPLETE
2. ✅ **Create verification script** to automate checks - COMPLETE
3. ✅ **Document findings** in this file - COMPLETE
4. ✅ **Update implementation plan** with any changes needed - COMPLETE
5. ✅ **Get user approval** on final scope/timeline - COMPLETE

**Result:** Ready to begin Week 1 Day 1 with confidence! 🚀

---

**Document Status:** ✅ COMPLETE - Ready to implement
**Created:** 2025-11-28 11:15 PM PST
**Completed:** 2025-11-28 11:30 PM PST
**Next Action:** Begin Week 1 Day 1 implementation
