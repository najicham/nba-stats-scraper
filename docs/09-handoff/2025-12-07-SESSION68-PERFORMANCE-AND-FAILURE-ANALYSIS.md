# Session 68: Performance Analysis & Failure Reclassification

**Date:** 2025-12-07
**Focus:** Deep performance analysis, failure study, and architecture decisions
**Status:** Handoff ready - key decisions made

---

## Executive Summary

This session conducted a thorough investigation of Phase 4 backfill performance and failure patterns. Key decisions:

1. **Keep 10-game minimum** for Phase 4 PSZA (data quality requirement)
2. **Reframe "INSUFFICIENT_DATA"** - not a failure, just incomplete data
3. **Performance optimizations identified** - 3-5x speedup possible
4. **December 2021 backfill ready** - needs PCF/PDC/ML processors run

---

## Key Findings

### 1. Performance Analysis

**Current State:**
- 5-6 min per date (with 100x dependency optimization)
- ~67 hours for full season (800 dates)
- Only using 10 workers on 32-core machine (31% CPU)
- Using ThreadPoolExecutor (GIL-limited)

**Optimization Opportunities:**
| Change | Impact | Effort |
|--------|--------|--------|
| Increase workers: 10 → 32 | 2.5x faster | 1 env var |
| ThreadPool → ProcessPool | 1.5-2x faster | 2 lines |
| **Combined** | **3-5x faster** | **5 min** |

**Files to modify for ProcessPoolExecutor:**
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
  - Line 31: Change `ThreadPoolExecutor` to `ProcessPoolExecutor`
  - Line 686: Same change in the `with` statement

### 2. Failure Analysis

**Total failures analyzed:** 9,118 (Nov-Dec 2021)

| Category | Count | % | Nature |
|----------|-------|---|--------|
| INSUFFICIENT_DATA | 8,057 | 88% | Expected - players < 10 games |
| MISSING_DEPENDENCY | 1,034 | 11% | Cascade from above |
| PROCESSING_ERROR | 0 | 0% | **Zero bugs!** |

**Key Insight:** These aren't "failures" - they're expected incomplete data states.

### 3. User Decision: Keep 10-Game Minimum

**Rationale:**
- 10 games provides statistically reliable shot zone analysis
- Phase 3 can have less games and record it in DB
- The issue is how we're classifying/presenting this, not the threshold

**Action Needed:**
- Reframe INSUFFICIENT_DATA from "failure" to "incomplete data"
- Validation script should not count these as failures
- Consider adding status like `PENDING_DATA` or `INCOMPLETE`

---

## Architecture Decision

### Current Flow (Problem)
```
Player has 7 games → PSZA checks → "INSUFFICIENT_DATA" → Logged as FAILURE
                                                        ↓
                     Validation script counts it as failure
                                                        ↓
                     Makes backfill look broken (25-30% "failure rate")
```

### Proposed Flow (Solution)
```
Player has 7 games → PSZA checks → "INCOMPLETE_DATA" → Logged as EXPECTED SKIP
                                                       ↓
                     Validation script ignores (not a failure)
                                                       ↓
                     Backfill shows true failure rate (~0%)
```

### Implementation Options

**Option A: Rename failure category**
```python
# Instead of INSUFFICIENT_DATA, use:
failure_category = "EXPECTED_INCOMPLETE"  # or "PENDING_DATA"
```

**Option B: Add "expected" flag**
```python
# In precompute_failures table, add:
is_expected_skip = True  # For INSUFFICIENT_DATA cases
```

**Option C: Separate table**
```python
# New table: precompute_incomplete_data
# Only track actual errors in precompute_failures
```

**Option D: Validation script filter**
```python
# In validation, exclude expected categories:
WHERE failure_category NOT IN ('INSUFFICIENT_DATA', 'EXPECTED_INCOMPLETE')
```

---

## December 2021 Status

### Current Data State
| Processor | Dates | Records | Status |
|-----------|-------|---------|--------|
| PSZA | 30 | 10,914 | ✅ Complete |
| TDZA | 29 | 870 | ⚠️ Missing Dec 4 |
| PCF | 0 | 0 | ❌ Needs backfill |
| PDC | 0 | 0 | ❌ Needs backfill |
| ML | 0 | 0 | ❌ Needs backfill |

### Backfill Command
```bash
# Run from processor 3 (PCF) since PSZA/TDZA done
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2021-12-01 \
  --end-date 2021-12-31 \
  --start-from 3
```

### Expected Results
- Duration: ~90-120 min (without perf optimization)
- Duration: ~30-40 min (with perf optimization)
- Records: ~350-400 per date per processor
- INSUFFICIENT_DATA rate: 15-20% (expected, not failures)

---

## Documents Created This Session

### Performance Documentation
| File | Purpose |
|------|---------|
| `docs/backfill-performance/PHASE4-PERFORMANCE-ANALYSIS.md` | Comprehensive performance analysis |

### Key Reference Documents
| File | Purpose |
|------|---------|
| `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md` | Primary backfill runbook |
| `docs/09-handoff/2025-12-07-SESSION67-*.md` | Previous session (100x optimization) |

---

## Code Files to Review

### Performance Optimization
```
data_processors/precompute/precompute_base.py
  - Lines 206-217: 100x dependency skip (already implemented)

data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
  - Line 31: ThreadPoolExecutor import (change to ProcessPoolExecutor)
  - Line 109: min_games_required = 10 (KEEP THIS)
  - Line 686: ThreadPoolExecutor usage (change to ProcessPoolExecutor)
  - Lines 794-800: INSUFFICIENT_DATA categorization (review for reframing)
```

### Failure Tracking
```
data_processors/precompute/precompute_base.py
  - Lines 1052-1100: Failure recording logic

nba_processing.precompute_failures (BigQuery table)
  - failure_category column: Currently includes INSUFFICIENT_DATA
```

### Validation Script
```
bin/validate_pipeline.py
  - Review how it counts/displays failures
  - Should exclude INSUFFICIENT_DATA from "failure" counts
```

---

## Validation Queries

### Check December Status
```sql
SELECT
  "PCF" as proc, COUNT(DISTINCT DATE(analysis_date)) as dates, COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE DATE(analysis_date) BETWEEN "2021-12-01" AND "2021-12-31"
UNION ALL
SELECT "PDC", COUNT(DISTINCT DATE(cache_date)), COUNT(*)
FROM nba_precompute.player_daily_cache
WHERE DATE(cache_date) BETWEEN "2021-12-01" AND "2021-12-31"
UNION ALL
SELECT "ML", COUNT(DISTINCT DATE(game_date)), COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE DATE(game_date) BETWEEN "2021-12-01" AND "2021-12-31";
```

### Check Real Failures (excluding expected)
```sql
SELECT processor_name, failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN "2021-12-01" AND "2021-12-31"
  AND failure_category NOT IN ('INSUFFICIENT_DATA')  -- Exclude expected
GROUP BY 1, 2;
```

### Verify Zero Bugs
```sql
SELECT COUNT(*) as bug_count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN "2021-12-01" AND "2021-12-31"
  AND failure_category = "PROCESSING_ERROR";
-- Expected: 0
```

---

## Next Steps for New Session

### Priority 1: Decide on Failure Reframing
1. Review current failure categorization in code
2. Choose approach (Option A/B/C/D above)
3. Implement the change
4. Update validation script

### Priority 2: Apply Performance Optimization (Optional)
1. Change ThreadPoolExecutor → ProcessPoolExecutor
2. Set `PSZA_WORKERS=32` environment variable
3. Test on single date first
4. Expected: 3-5x speedup

### Priority 3: Run December Backfill
1. Run from processor 3: `--start-from 3`
2. Monitor for PROCESSING_ERROR (should be 0)
3. INSUFFICIENT_DATA counts are expected, not failures
4. Validate results with queries above

---

## Testing Philosophy

From Session 67:
1. Test single dates first
2. Test small ranges (3-5 dates)
3. Monitor failure rates vs expected
4. Only run full backfill after validation

### Expected Failure Rates (INSUFFICIENT_DATA)
| Season Week | Days | Expected % |
|-------------|------|------------|
| 1-2 | 1-14 | 90-100% |
| 3 | 15-21 | 60-75% |
| 4 | 22-28 | 40-50% |
| 5+ | 29+ | 25-30% |

December 2021 = Week 9-13 = **15-25% expected** (not failures!)

---

## Summary

**What was accomplished:**
1. ✅ Deep performance analysis - 3-5x speedup identified
2. ✅ Comprehensive failure study - 0 bugs, all expected
3. ✅ User decision: Keep 10-game minimum
4. ✅ Architecture insight: Reframe INSUFFICIENT_DATA

**What needs to be done:**
1. 🔲 Implement failure reframing (INSUFFICIENT_DATA → not a failure)
2. 🔲 Optionally apply performance optimization
3. 🔲 Run December 2021 backfill (PCF/PDC/ML)
4. 🔲 Validate results

**Key insight from user:**
> "The issue is that we are recording this as a failure by our validation script, maybe it should be returned as not a failure, just incomplete data or something like that."

This is the correct architectural view - INSUFFICIENT_DATA is expected behavior, not a failure.
