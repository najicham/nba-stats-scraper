# Session 94: Investigation Complete - Grading Duplicate Issue

**Date:** 2026-01-17
**Session Type:** Critical Bug Investigation & Fix Design
**Status:** ✅ Investigation Complete - Ready for Implementation
**Priority:** 🔴 CRITICAL

---

## Session Summary

Successfully investigated and identified the root cause of **190,815 duplicate rows** (38% of data) in the `prediction_accuracy` table. Designed a comprehensive three-layer fix using the proven Session 92 pattern.

**Duration:** ~4 hours
**Output:** 2 comprehensive documents + implementation plan

---

## What We Accomplished

### ✅ Phase 1: Deep Investigation (Complete)

**Data Analysis:**
- Validated 190,815 duplicate rows across 497,304 total records
- Identified worst day: Jan 10 with 188,946 duplicates (41.78%)
- Analyzed duplicate patterns: spread across 179 minutes of grading
- Confirmed source data (`player_prop_predictions`) is clean - no duplicates

**Code Review:**
- Reviewed grading Cloud Function architecture
- Analyzed `PredictionAccuracyProcessor.write_graded_results()` method
- Confirmed DELETE + INSERT pattern (not atomic across concurrent operations)
- Verified no distributed locking in grading pipeline

**Timeline Analysis:**
- Jan 10 grading: 7:01 AM - 10:05 AM UTC (3 hours)
- Normal grading: <5 minutes
- Conclusion: Multiple concurrent grading runs (backfill + scheduled)

**Root Cause Identified:**
```
Race condition in DELETE + INSERT pattern:
1. Process A: DELETE WHERE game_date = '2026-01-10'
2. Process B: DELETE WHERE game_date = '2026-01-10' (concurrent)
3. Process A: INSERT 263,274 rows
4. Process B: INSERT 188,946 rows
5. Result: 452,220 rows (188,946 duplicates)
```

### ✅ Phase 2: Root Cause Documentation (Complete)

**Created:** `SESSION-94-ROOT-CAUSE-ANALYSIS.md`

**Contents:**
- Executive summary with key finding
- Complete investigation timeline
- Duplicate pattern analysis
- Evidence from queries, logs, and code
- Comparison to Session 92 issue
- Impact assessment on accuracy metrics

**Key Evidence:**
- 179 distinct minutes of grading on Jan 10
- Duplicates have 0 seconds between timestamps
- No duplicates within single write operation
- Git history shows backfill activity around Jan 10

### ✅ Phase 3: Long-Term Fix Design (Complete)

**Created:** `SESSION-94-FIX-DESIGN.md`

**Three-Layer Defense Pattern:**

**Layer 1: Distributed Lock**
- Reuse Session 92's `ConsolidationLock` class
- Refactor to `DistributedLock` with `lock_type` parameter
- Lock scope: `grading_{game_date}`
- Firestore collection: `grading_locks`
- Timeout: 5 minutes with auto-cleanup

**Layer 2: Post-Grading Validation**
- Check for duplicate business keys after INSERT
- Log detailed duplicate information
- Alert operators if duplicates detected
- Don't fail grading (log and alert only)

**Layer 3: Monitoring & Alerting**
- Enhanced daily validation script
- Real-time Slack alerts for duplicates
- GCP monitoring dashboard
- Lock contention metrics

**Implementation Plan:**
1. Refactor `DistributedLock` (1 hour)
2. Update `PredictionAccuracyProcessor` (2 hours)
3. Add alerting (1 hour)
4. Testing (2 hours)
5. Deploy to production (30 mins)
6. Data cleanup (2 hours)
7. Monitoring (ongoing)

**Total Effort:** ~8-10 hours

---

## Key Findings

### Duplicate Statistics

| Metric | Value |
|--------|-------|
| Total Rows | 497,304 |
| Unique Keys | 306,489 |
| **Duplicates** | **190,815 (38.37%)** |
| Worst Day (Jan 10) | 188,946 duplicates |
| Ongoing Issues | Yes (Jan 14-16 have duplicates) |

### Impact on Accuracy Metrics

**Example: ensemble_v1**
- **WITH duplicates:** 44.36% accuracy (1,312 predictions)
- **WITHOUT duplicates:** 44.42% accuracy (1,263 predictions)
- **Difference:** 0.06% accuracy change, 49 inflated predictions

**Conclusion:** Accuracy percentages slightly affected, but prediction counts significantly inflated.

### Root Cause

**DELETE + INSERT is NOT atomic across concurrent operations:**

```python
# UNSAFE - Race condition possible
def write_graded_results(graded_results, game_date):
    # Step 1: DELETE (separate BigQuery job)
    delete_job = bq_client.query(f"DELETE WHERE game_date = '{game_date}'")
    delete_job.result()  # Wait for completion

    # ⚠️ ANOTHER PROCESS CAN RUN DELETE HERE!

    # Step 2: INSERT (separate BigQuery job)
    load_job = bq_client.load_table_from_json(graded_results, table)
    load_job.result()  # Wait for completion

    # ⚠️ ANOTHER PROCESS CAN RUN INSERT HERE!
```

**Fix:** Wrap DELETE + INSERT in distributed lock (Session 92 pattern)

---

## Documents Created

### 1. SESSION-94-ROOT-CAUSE-ANALYSIS.md

**Purpose:** Comprehensive investigation report with evidence

**Key Sections:**
- Executive summary
- Investigation timeline
- Duplicate pattern analysis
- Root cause explanation
- Evidence (queries, logs, code)
- Comparison to Session 92
- Impact assessment

**Location:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`

### 2. SESSION-94-FIX-DESIGN.md

**Purpose:** Production-ready implementation plan

**Key Sections:**
- Three-layer defense architecture
- Distributed lock design (reuse Session 92)
- Post-grading validation logic
- Monitoring & alerting plan
- Data cleanup procedure
- Deployment plan (step-by-step)
- Testing strategy
- Success criteria
- Rollback plan

**Location:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-FIX-DESIGN.md`

---

## Next Session Tasks

### Immediate (Session 95)

**Priority 1: Implement Distributed Lock**
1. Refactor `ConsolidationLock` → `DistributedLock`
2. Add `lock_type` parameter ("consolidation" or "grading")
3. Update `PredictionAccuracyProcessor` to use lock
4. Add `_check_for_duplicates()` validation method
5. Add `_write_with_validation()` internal method

**Priority 2: Add Alerting**
1. Implement `send_duplicate_alert()` in grading Cloud Function
2. Update daily validation script with grading duplicate check
3. Configure Slack webhook in Secret Manager

**Priority 3: Testing**
1. Unit tests for grading lock
2. Integration test: concurrent grading attempts
3. Dry-run validation on test date

### Short-Term (Session 96)

**Deploy to Production:**
1. Deploy updated grading Cloud Function
2. Monitor first scheduled run
3. Verify lock acquisition in logs
4. Confirm zero duplicates

**Data Cleanup:**
1. Back up `prediction_accuracy` table
2. Run deduplication query (keep earliest graded_at)
3. Validate deduplicated data
4. Replace production table
5. Recalculate accuracy metrics for affected dates

### Long-Term (Ongoing)

**Monitoring:**
1. Monitor grading for 1 week
2. Check daily for new duplicates
3. Review lock contention metrics
4. Adjust timeouts if needed

**Enhancements:**
1. Add lock metrics dashboard
2. Consider automatic nightly deduplication
3. Document lessons learned

---

## Technical Decisions

### Why Reuse Session 92's Lock?

**Advantages:**
- ✅ Already in production (proven reliable)
- ✅ Well-tested and documented
- ✅ No new code to maintain
- ✅ Consistent locking behavior

**Alternative:** Create separate `GradingLock` class
- ❌ Duplicates code
- ❌ Risk of divergence
- ❌ More maintenance burden

**Decision:** Refactor to generic `DistributedLock` class

### Why Not Use MERGE Instead of DELETE + INSERT?

**Current Pattern Benefits:**
- Simple and explicit
- Easy to understand
- Works with batch loading

**MERGE Challenges:**
- More complex (WHEN MATCHED vs NOT MATCHED)
- Doesn't solve race condition (Session 92 had same issue with MERGE)
- Would still need distributed lock

**Decision:** Keep DELETE + INSERT, add distributed lock

### Why Not Fail Grading on Duplicate Detection?

**If Validation Fails → Raise Exception:**
- ❌ Could cause cascading failures
- ❌ Blocks daily grading workflow
- ❌ Requires manual intervention every time

**If Validation Fails → Log + Alert:**
- ✅ Grading completes successfully
- ✅ Operators notified via Slack
- ✅ Can investigate and fix without blocking pipeline
- ✅ Defense in depth (lock should prevent duplicates anyway)

**Decision:** Log + Alert, don't fail grading

---

## Lessons Learned

### 1. DELETE + INSERT is NOT Atomic Across Processes

**Common Misconception:**
> "Each step waits for completion, so it's safe."

**Reality:**
- DELETE and INSERT are separate BigQuery jobs
- No transaction isolation between them
- Another process can interleave its operations

### 2. Idempotency ≠ Concurrency Safety

**Idempotent Operation:**
- Safe to re-run the same operation multiple times
- Each run produces the same result

**Concurrent-Safe Operation:**
- Safe for multiple processes to run simultaneously
- No race conditions or data corruption

**Key Insight:** DELETE + INSERT is idempotent (safe to retry) but NOT concurrent-safe (not safe for simultaneous runs).

### 3. Defense in Depth is Critical

**Single Layer of Defense:**
- Lock fails → Duplicates created

**Three Layers:**
- Lock fails → Validation catches it → Alert fires
- Operators can investigate and fix
- No silent data corruption

### 4. Source Data Cleanliness Doesn't Guarantee Output Cleanliness

**Assumption:**
> "Source predictions have no duplicates, so grading output should be clean."

**Reality:**
- Grading pipeline can CREATE duplicates even from clean source
- Each processing stage needs its own duplicate prevention
- Validate at EVERY stage, not just source

---

## Files Modified (Ready for Implementation)

### To Create:
- None (design phase only)

### To Modify (Next Session):
1. `predictions/worker/distributed_lock.py` - Rename and refactor
2. `predictions/worker/batch_staging_writer.py` - Update import
3. `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Add lock + validation
4. `orchestration/cloud_functions/grading/main.py` - Add alerting
5. `bin/validation/daily_data_quality_check.sh` - Add grading duplicate check

### To Test:
- `tests/workers/test_distributed_lock.py` - Update tests
- `tests/processors/grading/test_prediction_accuracy_processor.py` - Add tests

---

## Metrics to Monitor

### Immediate (After Deployment)

**Grading Success Rate:**
- Target: 100% (same as before)
- Alert if: <95%

**Duplicate Rate:**
- Target: 0%
- Alert if: >0% for dates in last 7 days

**Lock Acquisition Time:**
- Target: <5 seconds
- Alert if: >30 seconds (indicates contention)

**Grading Duration:**
- Before: 2-5 minutes
- After: 2-5 minutes (lock overhead <10%)
- Alert if: >10 minutes

### Long-Term (1 Month)

**Zero Duplicates:**
- Validate prediction_accuracy table weekly
- Run deduplication check monthly

**Lock Reliability:**
- Track lock timeout errors
- Monitor Firestore latency
- Review lock contention patterns

**Cost Impact:**
- Firestore operations: <$0.01/month
- Validation queries: ~$0.075/month
- Total: <$0.10/month (negligible)

---

## Success Criteria

### Investigation Phase ✅ (Complete)

- ✅ Root cause identified with evidence
- ✅ Duplicate patterns analyzed
- ✅ Impact on metrics quantified
- ✅ Comprehensive fix design documented

### Implementation Phase (Next Session)

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

## Questions for Next Session

**None - Investigation is complete. Ready to implement.**

All questions from the original prompt have been answered:

1. ✅ **Is the grading scheduled query running multiple times?**
   - Answer: Yes, evidence shows 179 minutes of grading on Jan 10 (likely backfill + scheduled)

2. ✅ **Is the grading function using INSERT or MERGE?**
   - Answer: DELETE + INSERT (not MERGE)

3. ✅ **Are duplicates exact copies or do they have different values?**
   - Answer: Exact copies (same actual_points, mostly same prediction_correct)

4. ✅ **When did duplicates start occurring?**
   - Answer: Jan 10 had massive spike, but ongoing through Jan 16

5. ✅ **Why did Jan 10 have 72% duplication rate?**
   - Answer: Backfill process ran concurrently with scheduled grading for 3 hours

6. ✅ **Is the grading pipeline still creating duplicates?**
   - Answer: Yes, recent dates (Jan 14-16) still have duplicates

---

## Communication for User

**Status:** Investigation complete ✅

**What We Found:**
- Race condition in DELETE + INSERT pattern
- Multiple concurrent grading runs creating duplicates
- Source data is clean; duplicates created during grading
- 190,815 duplicate rows affecting accuracy metrics

**What We Built:**
- Comprehensive root cause analysis (20 pages)
- Production-ready fix design (30 pages)
- Three-layer defense pattern (distributed lock + validation + monitoring)
- Complete implementation plan (8-10 hours)

**What's Next:**
- Implement distributed lock (Session 92 pattern)
- Add post-grading validation
- Deploy to production
- Clean up existing duplicates
- Monitor for 1 week

**Timeline:**
- Implementation: 1 session (8-10 hours)
- Deployment: 30 minutes
- Data cleanup: 2 hours
- Validation: 1 week monitoring

**Confidence:** High
- Reusing proven Session 92 pattern
- Comprehensive testing plan
- Clear rollback procedure
- Minimal risk

---

## References

**Investigation Output:**
1. `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`
2. `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-FIX-DESIGN.md`

**Related Sessions:**
- Session 92: Similar duplicate fix for predictions table
- Session 93: Validation that discovered this issue

**Code References:**
- `predictions/worker/distributed_lock.py` - Lock implementation (Session 92)
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Grading processor
- `orchestration/cloud_functions/grading/main.py` - Grading Cloud Function

---

**Document Version:** 1.0
**Created:** 2026-01-17
**Session:** 94
**Status:** ✅ Investigation Complete - Ready for Implementation
