# Session 94: Investigation Complete - Summary

**Date:** 2026-01-17
**Duration:** ~4 hours
**Status:** ✅ INVESTIGATION COMPLETE - Ready for Implementation

---

## What We Accomplished

### 🔍 Deep Investigation Complete

**Problem:** 190,815 duplicate rows (38% of data) in `prediction_accuracy` table

**Deliverables:**
1. ✅ **Root Cause Analysis** - 20 pages of detailed investigation
2. ✅ **Fix Design** - 30 pages of production-ready implementation plan
3. ✅ **Handoff Document** - Complete session summary

**Investigation Duration:** 4 hours

---

## Root Cause Identified

**The Problem:**

```python
# DELETE + INSERT is NOT atomic across concurrent operations

Timeline of Race Condition:
Time | Process A (Scheduled)          | Process B (Backfill)
-----|--------------------------------|--------------------------------
T0   | Start grading Jan 10           | Start grading Jan 10
T1   | DELETE WHERE date = Jan 10     |
T2   | DELETE completes (0 rows)      |
T3   |                                | DELETE WHERE date = Jan 10
T4   |                                | DELETE completes (0 rows)
T5   | INSERT 263,274 records         |
T6   | INSERT completes               |
T7   |                                | INSERT 188,946 records
T8   |                                | INSERT completes
     |                                |
Result: 452,220 total rows (188,946 duplicates!)
```

**Key Evidence:**
- Jan 10 had **179 minutes of continuous grading** (normal: <5 minutes)
- Grading started at 7:01 AM UTC, ended at 10:05 AM UTC (3 hours!)
- This indicates backfill process running concurrently with scheduled grading
- Source `player_prop_predictions` table is **clean** (0 duplicates)
- Duplicates are created **during grading**, not from source data

---

## Investigation Results

### Duplicate Statistics

| Metric | Value |
|--------|-------|
| **Total Rows** | 497,304 |
| **Unique Keys** | 306,489 |
| **Duplicates** | **190,815 (38.37%)** |
| **Worst Day** | Jan 10: 188,946 duplicates |
| **Business Key** | (player_lookup, game_id, system_id, line_value) |

### Duplicate Distribution by Date

| Date | Total Rows | Unique Keys | Duplicates | Duplication % |
|------|-----------|-------------|------------|---------------|
| **Jan 10** | 452,220 | 263,274 | **188,946** | **41.78%** |
| Jan 14 | 7,075 | 5,762 | 1,313 | 18.56% |
| Jan 16 | 2,515 | 2,189 | 326 | 12.96% |
| Jan 15 | 328 | 255 | 73 | 22.26% |
| Jan 11 | 35,166 | 35,009 | 157 | 0.45% |

**Conclusion:** Ongoing issue, not a one-time event.

### Impact on Accuracy Metrics

**Example: ensemble_v1**
- **WITH duplicates:** 44.36% accuracy (1,312 predictions)
- **WITHOUT duplicates:** 44.42% accuracy (1,263 predictions)
- **Impact:** 0.06% accuracy difference, 49 inflated predictions

**Overall Impact:**
- Accuracy percentages: **Slightly affected** (0.01-0.06% difference)
- Prediction counts: **Significantly inflated** (up to 49 extra per system)
- Trend analysis: **Unreliable**
- System comparisons: **Invalid**

---

## Fix Design (Three-Layer Defense)

### Layer 1: Distributed Lock

**Reuse Session 92's proven pattern:**
- Firestore-based distributed locking
- Lock scope: `grading_{game_date}`
- Timeout: 5 minutes with auto-cleanup
- Prevents concurrent grading for same date

**Implementation:**
```python
# Refactor ConsolidationLock → DistributedLock
lock = DistributedLock(project_id="nba-props-platform", lock_type="grading")

with lock.acquire(game_date="2026-01-17", operation_id="grading"):
    # DELETE + INSERT happens inside lock
    # Only ONE process can grade a date at a time
    write_graded_results(...)
```

### Layer 2: Post-Grading Validation

**Detect duplicates after write:**
- Check for duplicate business keys
- Log detailed duplicate information
- Alert operators via Slack
- Don't fail grading (log + alert only)

**Validation Query:**
```sql
SELECT COUNT(*) as duplicate_count
FROM (
    SELECT player_lookup, game_id, system_id, line_value, COUNT(*) as cnt
    FROM prediction_accuracy
    WHERE game_date = '2026-01-17'
    GROUP BY 1,2,3,4
    HAVING cnt > 1
)
```

### Layer 3: Monitoring & Alerting

**Enhanced monitoring:**
- Daily validation script checks for duplicates
- Real-time Slack alerts when duplicates detected
- GCP monitoring dashboard
- Lock contention metrics

**Alert Example:**
> 🔴 **Grading Duplicate Alert**
>
> **Date:** 2026-01-17
> **Duplicates:** 5 business keys
> **Status:** Grading completed but with duplicates
> **Action Required:** Run deduplication query

---

## Documents Created

### 1. SESSION-94-ROOT-CAUSE-ANALYSIS.md

**Location:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`

**Contents:**
- Executive summary
- Complete investigation timeline
- Duplicate pattern analysis
- Evidence from queries, logs, code
- Comparison to Session 92 issue
- Impact on accuracy metrics

**Length:** ~20 pages

### 2. SESSION-94-FIX-DESIGN.md

**Location:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-FIX-DESIGN.md`

**Contents:**
- Three-layer defense architecture
- Distributed lock design (reuse Session 92)
- Post-grading validation logic
- Monitoring & alerting plan
- Data cleanup procedure (remove 190k duplicates)
- Deployment plan (step-by-step)
- Testing strategy
- Success criteria
- Rollback plan
- Cost impact analysis

**Length:** ~30 pages

### 3. SESSION-94-INVESTIGATION-COMPLETE.md

**Location:** `docs/09-handoff/SESSION-94-INVESTIGATION-COMPLETE.md`

**Contents:**
- Session summary
- Key findings
- Documents created
- Next steps (implementation)
- Success criteria
- Lessons learned

**Length:** ~15 pages

---

## Next Steps

### Session 95: Implementation (8-10 hours)

**Tasks:**
1. **Refactor DistributedLock** (1 hour)
   - Rename `ConsolidationLock` → `DistributedLock`
   - Add `lock_type` parameter
   - Update all existing uses

2. **Update PredictionAccuracyProcessor** (2 hours)
   - Add `_write_with_validation()` method
   - Add `_check_for_duplicates()` method
   - Update `write_graded_results()` to use lock

3. **Add Alerting** (1 hour)
   - Implement `send_duplicate_alert()`
   - Update daily validation script
   - Configure Slack webhook

4. **Testing** (2 hours)
   - Unit tests for grading lock
   - Integration test: concurrent grading attempts
   - Dry-run validation

5. **Deploy** (30 mins)
   - Deploy updated Cloud Function
   - Verify first scheduled run
   - Monitor logs

6. **Data Cleanup** (2 hours)
   - Back up current table
   - Run deduplication query
   - Replace production table
   - Recalculate accuracy metrics

### Session 96: Monitoring (1 week)

**Tasks:**
- Monitor grading daily
- Check for new duplicates
- Review lock contention metrics
- Validate accuracy metrics

---

## Key Insights

### 1. DELETE + INSERT ≠ Atomic

**Common Misconception:**
> "Each step waits for completion, so it's safe."

**Reality:**
- DELETE and INSERT are separate BigQuery jobs
- No transaction isolation between them
- Another process can interleave its operations

### 2. Idempotency ≠ Concurrency Safety

**Idempotent:** Safe to re-run the same operation multiple times
**Concurrent-Safe:** Safe for multiple processes to run simultaneously

**DELETE + INSERT is idempotent but NOT concurrent-safe!**

### 3. Defense in Depth is Critical

**Single Layer:** Lock fails → Duplicates created
**Three Layers:** Lock fails → Validation catches it → Alert fires

### 4. Session 92 Pattern is Proven

**Advantages:**
- Already in production (reliable)
- Well-tested and documented
- No new code to maintain
- Consistent locking behavior

**Decision:** Reuse, don't rewrite

---

## Success Criteria

### Implementation Phase (Session 95)

- [ ] Distributed lock implemented and tested
- [ ] Post-grading validation added
- [ ] Alerting configured
- [ ] Unit tests passing
- [ ] Integration tests passing

### Deployment Phase (Session 96)

- [ ] Fix deployed to production
- [ ] First scheduled run successful with lock
- [ ] Zero duplicates in new grading runs
- [ ] Monitoring dashboard configured

### Cleanup Phase (Session 96)

- [ ] Existing 190k duplicates removed
- [ ] Accuracy metrics recalculated
- [ ] TRUE accuracy validated
- [ ] Backup table preserved

### Long-Term (1 Month)

- [ ] Zero duplicates for 30 consecutive days
- [ ] No lock timeout errors
- [ ] No manual intervention required
- [ ] Accuracy metrics stable and reliable

---

## Cost Impact

**Firestore Operations:**
- ~5 operations per grading run
- ~150 operations/month
- **Cost: <$0.01/month**

**BigQuery Validation:**
- ~500k rows scanned per validation
- 1 validation per day
- **Cost: ~$0.075/month**

**Total: <$0.10/month** (negligible)

**Comparison:** Fixing duplicate data issues manually costs hours of engineering time.

---

## Technical Decisions

### Why Reuse Session 92's Lock?

✅ Already in production (proven reliable)
✅ Well-tested and documented
✅ No new code to maintain
✅ Consistent locking behavior

❌ Alternative: Create separate GradingLock class
- Duplicates code
- Risk of divergence
- More maintenance burden

**Decision: Refactor to generic DistributedLock class**

### Why Not Use MERGE?

**DELETE + INSERT Benefits:**
- Simple and explicit
- Easy to understand
- Works with batch loading

**MERGE Challenges:**
- More complex
- Doesn't solve race condition (Session 92 had same issue)
- Would still need distributed lock

**Decision: Keep DELETE + INSERT, add distributed lock**

### Why Not Fail Grading on Duplicates?

**If Validation Fails → Raise Exception:**
❌ Could cause cascading failures
❌ Blocks daily grading workflow
❌ Requires manual intervention

**If Validation Fails → Log + Alert:**
✅ Grading completes successfully
✅ Operators notified via Slack
✅ Can investigate without blocking pipeline
✅ Defense in depth (lock should prevent anyway)

**Decision: Log + Alert, don't fail grading**

---

## Files Modified (Next Session)

### To Create:
- None (design phase complete)

### To Modify:
1. `predictions/worker/distributed_lock.py` - Rename and refactor
2. `predictions/worker/batch_staging_writer.py` - Update import
3. `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Add lock + validation
4. `orchestration/cloud_functions/grading/main.py` - Add alerting
5. `bin/validation/daily_data_quality_check.sh` - Add grading duplicate check

### To Test:
- `tests/workers/test_distributed_lock.py` - Update tests
- `tests/processors/grading/test_prediction_accuracy_processor.py` - Add tests

---

## Timeline

| Phase | Duration | Status |
|-------|----------|--------|
| **Investigation** | 4 hours | ✅ Complete |
| **Implementation** | 8-10 hours | 📋 Next Session |
| **Testing** | 2 hours | 📋 Next Session |
| **Deployment** | 30 mins | 📋 Session 96 |
| **Data Cleanup** | 2 hours | 📋 Session 96 |
| **Monitoring** | 1 week | 📋 Session 96+ |

**Total Estimated Time:** ~15 hours (investigation + implementation + deployment)

---

## Lessons Learned

1. **DELETE + INSERT is NOT atomic across processes**
   - Each step waits for completion
   - But no transaction isolation between them
   - Another process can interleave operations

2. **Idempotency ≠ Concurrency Safety**
   - Idempotent: Safe to retry
   - Concurrent-Safe: Safe for simultaneous runs
   - DELETE + INSERT is idempotent but NOT concurrent-safe

3. **Defense in Depth is Critical**
   - Lock alone might fail (Firestore outage)
   - Validation alone detects too late
   - Together: Comprehensive protection

4. **Source Data Cleanliness ≠ Output Cleanliness**
   - Clean source doesn't guarantee clean output
   - Each processing stage needs duplicate prevention
   - Validate at every stage

5. **Proven Patterns > New Code**
   - Session 92 pattern works well
   - Reusing reduces risk and maintenance
   - Consistency across pipelines

---

## References

**Investigation Documents:**
1. `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`
2. `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-FIX-DESIGN.md`
3. `docs/09-handoff/SESSION-94-INVESTIGATION-COMPLETE.md`

**Related Sessions:**
- Session 92: Similar duplicate fix for predictions table
- Session 93: Validation that discovered this issue

**Code References:**
- `predictions/worker/distributed_lock.py` - Lock implementation (Session 92)
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Grading processor
- `orchestration/cloud_functions/grading/main.py` - Grading Cloud Function

---

## Questions Answered

From the original Session 94 prompt, all questions have been answered:

1. ✅ **Is the grading scheduled query running multiple times?**
   - Yes, evidence shows 179 minutes of grading on Jan 10

2. ✅ **Is the grading function using INSERT or MERGE?**
   - DELETE + INSERT (not MERGE)

3. ✅ **Are duplicates exact copies or different values?**
   - Exact copies (same timestamps, same values)

4. ✅ **When did duplicates start occurring?**
   - Jan 10 had massive spike, ongoing through Jan 16

5. ✅ **Why did Jan 10 have 72% duplication rate?**
   - Backfill ran concurrently with scheduled grading for 3 hours

6. ✅ **Is the grading pipeline still creating duplicates?**
   - Yes, recent dates (Jan 14-16) still have duplicates

---

**Status:** ✅ INVESTIGATION COMPLETE
**Next:** Implementation in Session 95
**Confidence:** HIGH (reusing proven Session 92 pattern)
**Risk:** LOW (comprehensive testing + rollback plan)
**Timeline:** 8-10 hours implementation + 1 week monitoring

---

**Ready to implement!** 🚀
