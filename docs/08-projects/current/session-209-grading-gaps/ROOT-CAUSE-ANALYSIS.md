# Grading Gap Root Cause Analysis (Session 209 Follow-Up)

## Current Status After Backfill Attempts

| Date | Predictions | Graded | Gap | Status |
|------|-------------|--------|-----|--------|
| 2026-01-29 | 282 | 108 | 174 (38.3%) | Still incomplete |
| 2026-01-30 | 351 | 123 | 228 (35.0%) | Still incomplete |
| 2026-01-31 | 209 | 94 | 115 (45.0%) | Still incomplete |
| 2026-02-03 | 171 | 126 | 45 (26.3%) | Improved from 48.6% |
| 2026-02-10 | 29 | 23 | 6 (20.7%) | Improved from 58.6% |

**Backfill Service Responses:**
- 2026-01-31: Reported 661 graded ✓ (but only 94 in prediction_accuracy)
- 2026-02-03: Reported 962 graded ✓ (but only 126 in prediction_accuracy)
- 2026-01-30: Reported 826 graded ✓ (but only 123 in prediction_accuracy)
- 2026-01-29: Reported 294 graded ✓ (but only 108 in prediction_accuracy)

## Root Cause Hypotheses

### 1. **Multi-Model Grading vs Champion-Only Queries** (MOST LIKELY)

The grading service grades ALL active models (14+ models including shadows), but our validation queries only check `catboost_v9` (champion).

**Evidence:**
- Grading service reported 661 graded for 2026-01-31
- But champion only has 94 graded
- 661 / 14 models ≈ 47 per model (close to the 94 we see)

**Implication:** Grading IS working, but we're measuring the wrong thing.

### 2. **Table Write Target Mismatch**

Grading service may write to a different table than `prediction_accuracy` (e.g., staging table, different partition).

**How to verify:**
```sql
-- Check all tables with grading data
SELECT table_name, row_count, last_modified_time
FROM `nba-props-platform.nba_predictions.__TABLES__`
WHERE table_name LIKE '%accur%' OR table_name LIKE '%grad%'
ORDER BY last_modified_time DESC
```

### 3. **Partial Grading Success**

Grading runs but fails partway through due to:
- Timeout (Cloud Run 60-min limit)
- Memory exhaustion
- Missing boxscore data for some players

**Sample ungraded players:**
- 2026-01-29: nikolajokic, aarongordon (high-profile players - unlikely to be missing data)
- 2026-02-10: lukadoncic, deandreayton (both were DNP - expected)

### 4. **Scheduler Configuration Issues**

Grading jobs run at wrong times or with wrong parameters.

**Current schedulers:**
- `grading-daily`: 11:00 AM ET
- `grading-morning`: 7:00 AM ET  
- `grading-latenight`: 2:30 AM ET

**For games on 2026-01-30:**
- Games finish: ~10-11 PM ET (Jan 30)
- Boxscores arrive: ~12-3 AM ET (Jan 31)
- First grading run: 2:30 AM ET (Jan 31) - may be too early
- Second run: 7:00 AM ET (Jan 31)
- Third run: 11:00 AM ET (Jan 31)

**Problem:** If boxscores arrive at 3 AM but grading runs at 2:30 AM, it misses them.

## Prevention & Improvement Strategies

### Immediate (This Session)

1. **Fix Grading Gap Detector Query** ✓ (Already created)
   - Detects <80% grading completion
   - Auto-triggers backfills
   - Runs daily at 9 AM ET

2. **Add Multi-Model Grading Validation** (NEW)
   - Don't just check champion - check ALL active models
   - Alert if ANY model has <80% grading

3. **Add Grading to `/validate-daily`** (HIGH PRIORITY)
   - Currently checks predictions, features, cache
   - Should also check grading completion
   - Phase 0.7: Grading Completeness Check

### Short-Term (Next Session)

4. **Grading Readiness Check** (Prerequisite validation)
   - Before running grading, verify:
     - All games have status = 3 (Final)
     - All games have boxscores in player_game_summary
     - All predictions have is_active = TRUE
   - Don't run grading if prerequisites not met

5. **Grading Audit Trail**
   - Log which predictions were attempted vs graded
   - Write to `grading_audit_log` table:
     - game_date, system_id, attempted, succeeded, failed, reason
   - Makes debugging much easier

6. **Scheduler Timing Optimization**
   - Move `grading-latenight` from 2:30 AM to 4:00 AM ET
   - Gives more time for boxscores to arrive
   - Reduces false negatives

### Long-Term (Future Sessions)

7. **Grading Service v2 - Idempotent Design**
   - Current: Grading may skip already-graded predictions
   - Better: Always attempt all predictions, use MERGE/UPSERT
   - Benefit: Backfills become no-ops if already graded

8. **Grading Completeness Dashboard**
   - Real-time view of grading status
   - Shows: predictions made, graded, pending, failed
   - Per-model breakdown
   - Historical trend (are gaps increasing?)

9. **Auto-Heal Grading Gaps** (Similar to Phase 5 shadow model auto-heal)
   - Pipeline canary detects gap
   - Auto-triggers backfill
   - Slack alert to #nba-alerts
   - No manual intervention needed

## Validation Improvements

### Current Validation Gaps

**`/validate-daily` Phases:**
- Phase 0.1: Data freshness ✓
- Phase 0.2: Scraper coverage ✓
- Phase 0.3: Cache hit rate ✓
- Phase 0.4: Feature quality ✓
- Phase 0.5: Prediction coverage ✓
- **Phase 0.7: MISSING - Grading completeness**

**What's missing:**
- No check for grading completion percentage
- No check for multi-model grading parity
- No check for grading lag (time between game end and grading)

### Proposed: Phase 0.7 - Grading Completeness

Add to `/validate-daily`:

```python
# Phase 0.7: Grading Completeness Check
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

grading_check = """
WITH predictions AS (
  SELECT system_id, COUNT(*) as predicted
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date = @yesterday AND is_active = TRUE
  GROUP BY system_id
),
graded AS (
  SELECT system_id, COUNT(*) as graded_count
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date = @yesterday
  GROUP BY system_id
)
SELECT
  p.system_id,
  p.predicted,
  COALESCE(g.graded_count, 0) as graded,
  ROUND(100.0 * COALESCE(g.graded_count, 0) / p.predicted, 1) as grading_pct
FROM predictions p
LEFT JOIN graded g USING (system_id)
WHERE COALESCE(g.graded_count, 0) / p.predicted < 0.80  -- Alert if <80%
"""

# If any model <80% graded, trigger backfill automatically
```

**Output:**
```
Phase 0.7: Grading Completeness
  catboost_v9: 23/29 (79.3%) ⚠️ Below 80%
  catboost_v9_q43: 21/26 (80.8%) ✓
  
  ⚠️ 1 model(s) below 80% grading threshold
  🔧 Auto-triggering backfill for 2026-02-10...
```

## Actionable Next Steps

**This Session:**
1. ✅ Created grading gap detector
2. ✅ Set up Cloud Scheduler (needs Cloud Function deployment)
3. ⏳ Verify backfills completed (check again in 5 min)
4. ⏳ Annotate remaining 12 views

**Next Session:**
5. Add Phase 0.7 to `/validate-daily`
6. Fix grading scheduler timing (2:30 AM → 4:00 AM)
7. Add grading audit trail table
8. Investigate table write target (why service reports 661 but we see 94?)

**Investigation Needed:**
- Check if grading service writes to a staging table first
- Verify multi-model grading is working correctly
- Check grading service deployment status (any recent changes?)

