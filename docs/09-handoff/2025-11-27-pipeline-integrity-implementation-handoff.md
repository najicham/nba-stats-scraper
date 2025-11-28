# Pipeline Integrity Implementation - Handoff for Development
**Created:** 2025-11-27
**Status:** 🎯 Design Complete - Ready for Implementation
**Audience:** Next developer/session working on pipeline integrity
**Can work in parallel with:** Bootstrap Period testing/deployment

---

## 🎯 Mission

**Implement data integrity features** to prevent processors from running with incomplete historical data during backfills and daily operations.

**What's done:**
- ✅ Complete design (DESIGN.md)
- ✅ Completeness checker enhancement design (COMPLETENESS-CHECKER-ENHANCEMENT.md)
- ✅ Implementation plan with file-by-file changes (IMPLEMENTATION-PLAN.md)
- ✅ Use cases documented (README.md)

**What you need to do:**
- 🔨 Implement cascade control (Phase 1)
- 🔨 Enhance completeness checker (Phase 2)
- 🔨 Create backfill scripts (Phase 3)
- 🧪 Test everything
- 🚀 Deploy

**Time estimate:** 26-34 hours (4-5 days)

---

## 📚 Context (5 min read)

### The Problem

**Three related issues:**

**Issue 1: Backfill Cascade Failures**
```
Phase 1: Oct 1-2, ❌ 3 (FAILS), 4-5 (continue)
           ↓                    ↓
Phase 2: Oct 1-2,              4-5
           ↓                    ↓
Phase 3: Oct 1-2,              4 (uses incomplete data!) ❌
```
Date 4 processes without date 3 → bad data cascades downstream

**Issue 2: Undetected Gaps**
```
Phase 3 has: Oct 1-10, Oct 15-20
Missing: Oct 11-14
Phase 4 runs Oct 20 → Uses incomplete historical window! ❌
```
No gap detection → processors run with incomplete data

**Issue 3: Uncontrolled Cascades**
```
Phase 1 backfill → Auto-triggers Phase 2 → Auto-triggers Phase 3
                   (via Pub/Sub)    (via Pub/Sub)

Can't verify Phase 1 complete before Phase 2 starts! ❌
```
No way to disable Pub/Sub during backfills

### The Solution

**Three features (all backward compatible, opt-in):**

1. **Cascade Control:** `--skip-downstream-trigger` flag
   - Disable Pub/Sub triggers during backfills
   - Allows verify-then-proceed workflow

2. **Gap Detection:** New completeness checker methods
   - Detect missing dates in historical ranges
   - Check if upstream processor failed

3. **Strict Mode:** Fail-on-incomplete option
   - Stop processing if data incomplete
   - Currently: warns and continues (soft)
   - New: raise exception (hard)

---

## 📂 Project Structure

**Location:** `docs/08-projects/current/pipeline-integrity/`

**Essential docs (read these):**
1. `README.md` - Project overview (5 min)
2. `DESIGN.md` - Complete technical design (15 min)
3. `COMPLETENESS-CHECKER-ENHANCEMENT.md` - API details (15 min)
4. `IMPLEMENTATION-PLAN.md` - Step-by-step guide (20 min)

**Total:** 4 docs, ~55 min to read

**Start with:** README.md → DESIGN.md → IMPLEMENTATION-PLAN.md

---

## 🎯 Implementation Phases

### Phase 1: Cascade Control (Priority 1)
**Goal:** Add `--skip-downstream-trigger` flag to disable Pub/Sub

**Effort:** 6-8 hours
**Files:** 3 base classes + ~20 processor CLIs
**Risk:** LOW (opt-in feature)

**What to do:**
1. Add parameter to ProcessorBase.__init__()
2. Add parameter to AnalyticsProcessorBase.__init__()
3. Add parameter to PrecomputeProcessorBase.__init__()
4. Modify _publish_completion_event() to check flag
5. Add CLI flag to all processors
6. Test: Verify no Pub/Sub message when flag set

**Details:** See IMPLEMENTATION-PLAN.md "Phase 1"

---

### Phase 2: Completeness Enhancements (Priority 2)
**Goal:** Add gap detection and strict mode

**Effort:** 12-16 hours
**Files:** 1 file (completeness_checker.py) + 3-4 test files
**Risk:** LOW (backward compatible)

**What to do:**
1. Add check_date_range_completeness() method
2. Add check_upstream_processor_status() method
3. Add fail_on_incomplete parameter to check_completeness()
4. Add DependencyError exception class
5. Write unit tests
6. Test: Verify gap detection works

**Details:** See IMPLEMENTATION-PLAN.md "Phase 2"
**API design:** See COMPLETENESS-CHECKER-ENHANCEMENT.md

---

### Phase 3: Backfill Tooling (Priority 3)
**Goal:** Create production-ready backfill scripts

**Effort:** 8-10 hours
**Files:** 5-6 new bash scripts
**Risk:** LOW (new files, no changes to existing)

**What to do:**
1. Create backfill_phase1.sh with error handling
2. Create backfill_phase2.sh
3. Create backfill_phase3.sh
4. Create backfill_phase4.sh
5. Create verify_phase_complete.sh helper
6. Create full_backfill_workflow.sh master script
7. Test: Run small backfill (3-5 days)

**Details:** See IMPLEMENTATION-PLAN.md "Phase 3"

---

## 📋 Quick Start Guide

### Step 1: Read Documentation (1 hour)

**Must read:**
- `README.md` - Problem and solutions overview
- `DESIGN.md` - Architecture and code examples
- `IMPLEMENTATION-PLAN.md` - File-by-file changes

**Optional (for details):**
- `COMPLETENESS-CHECKER-ENHANCEMENT.md` - Deep dive on API

---

### Step 2: Start with Phase 1 (6-8 hours)

**Cascade control is highest priority and quickest win.**

**Files to modify:**

1. `data_processors/raw/processor_base.py` (line ~537)
   ```python
   def __init__(self, skip_downstream_trigger=False):
       self.skip_downstream_trigger = skip_downstream_trigger
       # ...

   def _publish_completion_event(self):
       if self.skip_downstream_trigger:
           logger.info("Skipping downstream trigger (backfill mode)")
           return
       # Existing pub/sub code
   ```

2. `data_processors/analytics/analytics_base.py` (same pattern)

3. `data_processors/precompute/precompute_base.py` (same pattern)

4. All processor CLIs (~20 files):
   ```python
   parser.add_argument('--skip-downstream-trigger', action='store_true')
   processor = MyProcessor(skip_downstream_trigger=args.skip_downstream_trigger)
   ```

**Test:**
```bash
# Should NOT send Pub/Sub message
python processor.py --game-date 2023-10-24 --skip-downstream-trigger

# Verify: No message in topic
gcloud pubsub topics list-subscriptions phase3-trigger-topic
```

**Detailed instructions:** IMPLEMENTATION-PLAN.md "Phase 1"

---

### Step 3: Phase 2 - Completeness (12-16 hours)

**This is the most complex phase.**

**Main file:** `shared/utils/completeness_checker.py`

**Add three things:**

1. **New method: Gap detection**
   ```python
   def check_date_range_completeness(self, table, date_column, start_date, end_date):
       # Query for missing dates in range
       # Return {has_gaps, missing_dates, gap_count, coverage_pct}
   ```

2. **New method: Upstream failure detection**
   ```python
   def check_upstream_processor_status(self, processor_name, data_date):
       # Query processor_run_history
       # Return {processor_succeeded, status, safe_to_process}
   ```

3. **Enhancement: Add parameters to existing method**
   ```python
   def check_completeness(
       self,
       ...,
       fail_on_incomplete=False,  # NEW
       check_historical_gaps=False,  # NEW
       upstream_processor=None  # NEW
   ):
       # Existing logic...

       # NEW: Check gaps if requested
       if check_historical_gaps:
           gaps = self.check_date_range_completeness(...)

       # NEW: Fail hard if requested
       if fail_on_incomplete and not is_complete:
           raise DependencyError(...)
   ```

**Complete code examples:** COMPLETENESS-CHECKER-ENHANCEMENT.md

**Test files to create:**
- `tests/unit/completeness/test_gap_detection.py`
- `tests/unit/completeness/test_upstream_failure_detection.py`
- `tests/unit/completeness/test_strict_mode.py`

**Detailed instructions:** IMPLEMENTATION-PLAN.md "Phase 2"

---

### Step 4: Phase 3 - Backfill Scripts (8-10 hours)

**Create bash scripts for robust backfills.**

**Scripts to create in `bin/backfill/`:**

1. `backfill_phase1.sh` - Backfill scrapers with error handling
2. `backfill_phase2.sh` - Backfill raw processing
3. `backfill_phase3.sh` - Backfill analytics
4. `backfill_phase4.sh` - Backfill precompute
5. `verify_phase_complete.sh` - Check for gaps
6. `full_backfill_workflow.sh` - Master orchestrator

**Template:**
```bash
#!/bin/bash
set -e

ERROR_POLICY="${1:-stop}"
START_DATE="$2"
END_DATE="$3"

failed_dates=()
current_date="$START_DATE"

while [[ "$current_date" <= "$END_DATE" ]]; do
    if ! python processor.py --date "$current_date" --skip-downstream-trigger; then
        echo "❌ FAILED: $current_date"
        failed_dates+=("$current_date")

        if [[ "$ERROR_POLICY" == "stop" ]]; then
            exit 1
        fi
    fi
    current_date=$(date -I -d "$current_date + 1 day")
done

echo "Failed: ${failed_dates[@]}"
```

**Complete script templates:** IMPLEMENTATION-PLAN.md "Phase 3"

---

## 🧪 Testing Strategy

### Phase 1 Testing

**Test cascade control:**
```bash
# Test: Phase 2 should NOT trigger Phase 3
python processor.py --game-date 2023-10-24 --skip-downstream-trigger

# Verify: Check Pub/Sub topic
gcloud pubsub topics list-subscriptions phase3-trigger-topic
# Expected: No new messages

# Test: Normal mode should trigger
python processor.py --game-date 2023-10-24
# Expected: Pub/Sub message sent
```

---

### Phase 2 Testing

**Test gap detection:**
```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker()

# Test: Should find gaps
result = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=date(2023, 10, 31)
)

print(result['missing_dates'])  # Should show any gaps
```

**Test upstream failure detection:**
```python
# Test: Should detect failed processor
result = checker.check_upstream_processor_status(
    processor_name='player_boxscore_processor',
    data_date=date(2023, 10, 15)
)

print(result['safe_to_process'])  # False if processor failed
```

**Test strict mode:**
```python
# Test: Should raise exception when incomplete
with pytest.raises(DependencyError):
    checker.check_completeness(
        ...,
        fail_on_incomplete=True  # Should raise if incomplete
    )
```

---

### Phase 3 Testing

**Test backfill scripts:**
```bash
# Test with small date range
./bin/backfill/backfill_phase2.sh stop 2023-10-24 2023-10-26

# Expected: Processes 3 dates, stops if any fail

# Test verification script
./bin/backfill/verify_phase_complete.sh phase2 2023-10-24 2023-10-26

# Expected: Reports gaps if any exist
```

---

## 📊 Success Criteria

**Phase 1:**
- ✅ `--skip-downstream-trigger` flag works
- ✅ No Pub/Sub messages when flag set
- ✅ Normal behavior when flag not set
- ✅ All processors support the flag

**Phase 2:**
- ✅ Gap detection finds missing dates
- ✅ Upstream failure detection works
- ✅ Strict mode raises exceptions
- ✅ Backward compatible (existing code works)
- ✅ All unit tests pass

**Phase 3:**
- ✅ Backfill scripts handle errors correctly
- ✅ Verification scripts detect gaps
- ✅ Full workflow works end-to-end
- ✅ Scripts are well-documented

---

## 💡 Manual Workarounds (Use While Developing)

**Don't have cascade control yet? Use these:**

### Workaround 1: Disable Pub/Sub Manually
```bash
# Disable
gcloud pubsub subscriptions update phase3-sub --ack-deadline=600

# Run backfills
# ...

# Re-enable
gcloud pubsub subscriptions update phase3-sub --ack-deadline=10
```

### Workaround 2: Manual Gap Detection
```sql
-- Check for gaps
WITH expected AS (
    SELECT date FROM UNNEST(GENERATE_DATE_ARRAY('2023-10-01', '2023-10-31'))
),
actual AS (
    SELECT DISTINCT game_date as date FROM your_table
)
SELECT e.date as missing
FROM expected e
LEFT JOIN actual a ON e.date = a.date
WHERE a.date IS NULL;
```

### Workaround 3: Stop-on-Error
```bash
set -e  # Exit on first error
for date in ...; do
    python processor.py --game-date $date || exit 1
done
```

**These work NOW while you implement the real solution!**

---

## 🚨 Common Pitfalls

### Pitfall 1: Breaking Existing Behavior

**Problem:** Changing default behavior breaks existing code

**Solution:** Make all features opt-in
- `skip_downstream_trigger=False` (default: send Pub/Sub)
- `fail_on_incomplete=False` (default: warn and continue)
- `check_historical_gaps=False` (default: no gap check)

**Test:** Run existing processors without new flags → should work unchanged

---

### Pitfall 2: Forgetting to Update All Processors

**Problem:** Only updating some processors with CLI flag

**Solution:** Create a checklist
```bash
# List all processors with main blocks
find data_processors -name "*.py" -exec grep -l "if __name__" {} \;

# Check each one has --skip-downstream-trigger
```

---

### Pitfall 3: Performance Issues with Gap Detection

**Problem:** Gap detection queries scan large tables

**Solution:** Use partition filters
```sql
-- Always include date filters for partition elimination
WHERE DATE(date_column) >= @start_date
  AND DATE(date_column) <= @end_date
```

---

## 📁 Files to Modify/Create

**Phase 1 (Cascade Control):**
- Modify: `data_processors/raw/processor_base.py`
- Modify: `data_processors/analytics/analytics_base.py`
- Modify: `data_processors/precompute/precompute_base.py`
- Modify: ~20 processor CLI files

**Phase 2 (Completeness):**
- Modify: `shared/utils/completeness_checker.py`
- Create: `tests/unit/completeness/test_gap_detection.py`
- Create: `tests/unit/completeness/test_upstream_failure_detection.py`
- Create: `tests/unit/completeness/test_strict_mode.py`

**Phase 3 (Backfill Scripts):**
- Create: `bin/backfill/backfill_phase1.sh`
- Create: `bin/backfill/backfill_phase2.sh`
- Create: `bin/backfill/backfill_phase3.sh`
- Create: `bin/backfill/backfill_phase4.sh`
- Create: `bin/backfill/verify_phase_complete.sh`
- Create: `bin/backfill/full_backfill_workflow.sh`

**Total:** ~30-35 files

---

## ⏱️ Time Estimates

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| **Phase 1** | Cascade control | 6-8 hours |
| **Phase 2** | Completeness enhancements | 12-16 hours |
| **Phase 3** | Backfill scripts | 8-10 hours |
| **Testing** | All phases | 4-6 hours |
| **Documentation** | Update guides | 2-3 hours |

**Total:** 32-43 hours (estimate: ~37 hours)

**Breakdown:**
- Day 1: Phase 1 (6-8 hrs)
- Day 2-3: Phase 2 (12-16 hrs)
- Day 4: Phase 3 (8-10 hrs)
- Day 5: Testing & docs (6-9 hrs)

---

## 🔄 If You Get Stuck

### Design Questions

**Q: Should I change the default behavior?**
A: NO! Keep backward compatible. All features are opt-in.

**Q: Where does cascade control happen?**
A: In base classes (_publish_completion_event methods). See DESIGN.md.

**Q: How do I test gap detection without breaking prod?**
A: Use test tables or historical dates. Won't affect production.

### Implementation Questions

**Q: Which processors need the CLI flag?**
A: All Phase 2, 3, 4 processors. Use grep to find them.

**Q: Where do I add the new methods?**
A: In CompletenessChecker class, at the end. Keep existing methods unchanged.

**Q: How do I test Pub/Sub changes?**
A: Run processor with flag, check topic for messages (or lack of).

### Can't Resolve

1. Document the blocker clearly
2. Create handoff note for next session
3. List what was completed
4. Provide context for decision needed

---

## 🤝 Handoff from Previous Session

**What was completed:**
- Complete design (DESIGN.md)
- API specification (COMPLETENESS-CHECKER-ENHANCEMENT.md)
- Implementation plan (IMPLEMENTATION-PLAN.md)
- Use case documentation (README.md)

**What remains:**
- Implementation (3 phases)
- Testing
- Deployment
- Documentation updates

**Why this approach:**
- Enhance existing completeness checker (not create new)
- Opt-in features (backward compatible)
- Three independent phases (can work incrementally)

---

## 🎯 Quick Start (TL;DR)

**30-minute start:**

1. **Read docs (20 min):**
   - README.md - Overview
   - DESIGN.md - Architecture
   - IMPLEMENTATION-PLAN.md - File changes

2. **Start Phase 1 (10 min):**
   - Open `data_processors/raw/processor_base.py`
   - Find `_publish_completion_event` method
   - Add skip check as shown in IMPLEMENTATION-PLAN.md

3. **Then:** Continue with rest of Phase 1 (6-8 hours)

---

## 📞 Questions?

**For design/architecture:**
- See DESIGN.md - Complete technical design
- See COMPLETENESS-CHECKER-ENHANCEMENT.md - API details

**For implementation:**
- See IMPLEMENTATION-PLAN.md - Step-by-step guide
- See code examples in DESIGN.md

**For use cases:**
- See README.md - Problem statement and scenarios

---

## 🎉 Final Notes

**This is a well-designed solution:**
- Backward compatible (opt-in features)
- Clean separation of concerns
- Addresses real operational pain points
- Documented use cases from real scenarios

**Implementation is straightforward:**
- Clear phases with priorities
- Detailed code examples
- Comprehensive testing strategy
- Low risk changes

**You've got all you need:**
- Complete design
- Step-by-step plan
- Code examples
- Test strategies

**Go for it!** Start with Phase 1 (cascade control) - it's the quickest win and unblocks backfill workflows immediately. 🚀

---

**Status:** 🎯 Ready for implementation
**Next action:** Read docs (1 hour) → Start Phase 1 (6-8 hours)
**Estimated completion:** 4-5 days
**Can work in parallel with:** Bootstrap Period testing

**Good luck!** 💪
