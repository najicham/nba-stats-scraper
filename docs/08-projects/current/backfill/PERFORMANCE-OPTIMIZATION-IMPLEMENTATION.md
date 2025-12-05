# Performance Optimization Implementation - Player-Level Parallelization

**Date:** 2025-12-04
**Session:** 28-29
**Status:** In Progress
**Priority:** HIGH - Needed for daily production orchestration

---

## Executive Summary

Implementing player-level parallelization in Phase 3 and Phase 4 processors to achieve 3-5x speedup for daily production runs.

**Key Decision:** Parallelize existing processors using ThreadPoolExecutor rather than migrating to Phase 5 service pattern.

**Timeline:** 2-3 days to implement, test, and deploy
**Expected Impact:** 50 min → 10-15 min daily production runs (3-5x faster)

---

## Problem Statement

### User Need
> "I need these processors running quick for daily orchestration"

### Current Performance
- **Daily Production:** ~50 minutes for 460 players
- **Bottleneck:** Serial Python processing of ~460 players
  - UPGC (Phase 3): ~10 minutes per date
  - PSZA (Phase 4): ~10 minutes per date
- **Impact:** Cascades through entire Phase 3 → Phase 4 → Phase 5 orchestration

### Root Cause
Both UPGC and PSZA process ~460 players SERIALLY in Python loops with NO parallelization:
- BigQuery queries: Already optimized (single batch query for all players)
- Player processing: 1-2 seconds/player × 460 players = 10+ minutes

---

## Options Considered

### Option A: Parallelize Existing Processors ✅ **CHOSEN**

**Implementation:**
```python
# Use ThreadPoolExecutor for player-level parallelization
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(process_player, p): p for p in players}
    for future in as_completed(futures):
        result = future.result()
```

**Pros:**
- ✅ Low effort: 2-3 days implementation
- ✅ Low risk: Minimal architectural change
- ✅ 3-5x speedup: 50 min → 10-15 min production runs
- ✅ No infrastructure changes needed
- ✅ No cost increase
- ✅ Reuses all existing patterns (mixins, logging, circuit breakers)

**Cons:**
- ❌ Limited to 10-20 concurrent threads (GIL + CPU limits)
- ❌ Can't scale beyond 1 instance
- ❌ If one thread fails, could block batch

**Expected Performance:**
- Daily production: 50 min → 10-15 min (**3-5x faster**)
- Backfills: 10 min/date → 2 min/date (**5x faster**)
- With date-level parallelization: 5 hours/month → 12 min/month (**25x faster**)

---

### Option B: Migrate to Phase 5 Service Pattern ❌ **REJECTED**

**Implementation:**
- Create coordinator service (like predictions/coordinator)
- Publish player tasks to Pub/Sub
- Create worker service processing one player per request
- Scale to 20 instances × 5 threads = 100 concurrent players

**Pros:**
- ✅ Massive parallelization: 100 concurrent players
- ✅ Better failure isolation
- ✅ Proven pattern (Phase 5 uses this)
- ✅ 450 players in 2-3 minutes (20-25x faster)

**Cons:**
- ❌ HIGH effort: 3 weeks implementation
- ❌ HIGH risk: Complete architectural rewrite
- ❌ New infrastructure: Pub/Sub topics, subscriptions, DLQs
- ❌ Cost increase: Pub/Sub messages
- ❌ Complex backfill orchestration
- ❌ Lose processor patterns: Need to rewrite circuit breakers, smart skip, run history

**Why Rejected:**
- ROI: 3 weeks work for 10 extra minutes/day vs 2 days work for 35-40 minutes/day
- Risk: All-or-nothing vs incremental improvement
- Flexibility: Can implement later if needed

---

## Decision Rationale

### Key Insight: BigQuery is NOT the Bottleneck

**What's Already Optimized:**
```python
# UPGC line 837-888: Single batch query for ALL 460 players
player_lookups_str = "', '".join(player_lookups)  # All players
query = f"""SELECT ... FROM bdl_player_boxscores
           WHERE player_lookup IN ('{player_lookups_str}')"""
df = self.bq_client.query(query).to_dataframe()  # ONE query
```

**The Real Bottleneck:**
```python
# Line 880-888: Serial loop processing 460 players
for player_lookup in player_lookups:
    player_data = df[df['player_lookup'] == player_lookup].copy()
    # 1-2 seconds of pure Python/Pandas calculations
    context = calculate_player_context(player_data)
    results.append(context)
# Total: 460 × 1.5 sec = 10+ minutes
```

### Thread Safety Analysis

**UPGC is Thread-Safe:**
- ✅ `self.historical_boxscores`: Read-only during processing (populated beforehand)
- ✅ `self.schedule_data`: Read-only
- ✅ `self.prop_lines`: Read-only
- ✅ `_calculate_player_context()`: Pure function, returns dict
- ✅ Results collected in futures, then merged

**PSZA is Thread-Safe:**
- ✅ `self.raw_data`: Read-only during processing
- ✅ `.copy()` creates independent DataFrame for each thread
- ✅ `_calculate_zone_metrics()`: Pure computation
- ✅ Results collected in futures

### Python GIL Considerations

**Why Threading Works Here (not CPU-bound):**
- Pandas operations release the GIL
- Most time spent in NumPy/Pandas (C extensions)
- Not pure Python computation
- I/O operations (memory access) benefit from threading

**Worker Count Tuning:**
```python
# Conservative (safe for all environments)
max_workers = min(10, os.cpu_count() or 1)

# Aggressive (Cloud Run with 4+ CPUs)
max_workers = min(20, (os.cpu_count() or 1) * 2)
```

---

## Implementation Plan

### Phase 1: Player-Level Parallelization (2 days)

#### Day 1: UPGC Parallelization

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Changes:**
1. Add `_process_players_parallel()` method
2. Replace serial loop with ThreadPoolExecutor
3. Add performance timing logs
4. Test with single date (2021-11-15)

**Code Location:** Line ~1300 (after all data extraction complete)

#### Day 2: PSZA Parallelization

**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Changes:**
1. Extract `_process_single_player_zones()` method
2. Replace serial loop (line 610) with ThreadPoolExecutor
3. Add performance timing logs
4. Test with single date

---

### Phase 2: Additional Optimizations (1 day)

#### Completeness Query Consolidation

**Current:** 5 separate queries (l5d, l7d, l10d, l14d, l30d)

**Optimized:** Single query with conditional aggregates
```sql
SELECT
    player_lookup,
    COUNTIF(game_date >= @analysis_date - 5) as l5d_count,
    COUNTIF(game_date >= @analysis_date - 7) as l7d_count,
    COUNTIF(game_date >= @analysis_date - 10) as l10d_count,
    COUNTIF(game_date >= @analysis_date - 14) as l14d_count,
    COUNTIF(game_date >= @analysis_date - 30) as l30d_count
FROM nba_analytics.player_game_summary
WHERE game_date >= @analysis_date - 30
GROUP BY player_lookup
```

**Impact:** 5 queries → 1 query = 5x faster for completeness checks

**File:** `shared/utils/completeness_checker.py`

---

### Phase 3: Date-Level Parallelization for Backfills (Optional)

**Current Backfill Pattern:**
```bash
# Serial: 30 dates × 2 min = 60 minutes
for date in 2021-11-01 to 2021-11-30:
    process_date(date)
```

**Optimized:**
```bash
# Parallel: 6 batches × 2 min = 12 minutes (5x faster)
# Process 5 dates concurrently
parallel_process([Nov 1-5, Nov 6-10, Nov 11-15, ...])
```

**BigQuery Impact:** 5 concurrent queries is trivial (well within 100 query limit)

---

## Performance Monitoring

### Timing Logs

Added to both UPGC and PSZA:
```python
import time

loop_start = time.time()
processed_count = 0

# Every 50 players
if processed_count % 50 == 0 and processed_count > 0:
    elapsed = time.time() - loop_start
    rate = processed_count / elapsed
    remaining = total_players - processed_count
    eta = remaining / rate

    logger.info(
        f"Player processing progress: {processed_count}/{total_players} "
        f"| Rate: {rate:.1f} players/sec "
        f"| ETA: {eta/60:.1f}min"
    )

# Final summary
total_time = time.time() - loop_start
logger.info(
    f"Completed {len(results)} players in {total_time:.1f}s "
    f"(avg {total_time/len(results):.2f}s/player)"
)
```

### Metrics to Track

**Before Optimization (Baseline):**
- UPGC processing time per date
- PSZA processing time per date
- Total Phase 3 + Phase 4 time

**After Optimization:**
- Players/second processing rate
- Thread utilization
- Memory usage
- Error rate

---

## Testing Strategy

### 1. Single Date Test (2021-11-15)
```bash
# Test UPGC with parallelization
PYTHONPATH=. python3 -m pytest tests/test_upgc_parallel.py -v

# Compare outputs: serial vs parallel (should be identical)
bq query --format=csv "SELECT * FROM nba_analytics.upcoming_player_game_context
                       WHERE analysis_date = '2021-11-15'
                       ORDER BY player_lookup" > serial_output.csv

# Run with parallelization
bq query --format=csv "SELECT * FROM nba_analytics.upcoming_player_game_context_parallel
                       WHERE analysis_date = '2021-11-15'
                       ORDER BY player_lookup" > parallel_output.csv

# Diff should be empty
diff serial_output.csv parallel_output.csv
```

### 2. Multi-Date Test (Nov 15-20)
- Run 5 consecutive dates
- Monitor for race conditions
- Check error rates

### 3. Full Month Backfill
- Run November 2021 (30 dates)
- Measure total time: expect ~1 hour vs 5 hours
- Verify data quality

### 4. Production Deployment
- Deploy to Cloud Run
- Monitor first daily run
- Compare to historical baseline

---

## Rollback Plan

### If Issues Arise

**Quick Rollback:**
```python
# Add flag to disable parallelization
ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PARALLELIZATION', 'true').lower() == 'true'

if ENABLE_PARALLELIZATION:
    self._process_players_parallel()
else:
    self._process_players_serial()  # Old code path
```

**Deployment Strategy:**
1. Deploy with parallelization disabled by default
2. Enable for single date test
3. Enable for production run
4. If issues: `gcloud run services update --set-env-vars ENABLE_PARALLELIZATION=false`

---

## BigQuery Considerations

### Parallel Query Capacity

**BigQuery Limits:**
- 100 interactive queries per project (concurrent)
- 100 batch queries per project (concurrent)
- Each query gets independent slot allocation

**Our Usage:**
- Player parallelization: No additional queries (uses in-memory data)
- Date parallelization: 5 concurrent queries (well within limits)
- Completeness optimization: Reduces from 5 to 1 query

**Conclusion:** No BigQuery bottlenecks expected. May even reduce load (fewer queries).

### Cost Impact

**Current Costs:**
- BigQuery: Batch queries ~$5/TB scanned
- Cloud Run: Per-second execution time

**With Parallelization:**
- BigQuery: **Unchanged** (same queries, faster wall-clock time)
- Cloud Run: **Reduced** (less execution time)

**Net Effect:** Cost savings due to faster execution.

---

## Expected Results

### Daily Production (After Phase 1)

| Processor | Before | After | Speedup |
|-----------|--------|-------|---------|
| UPGC | 10 min | 1-2 min | 5-10x |
| PSZA | 10 min | 1-2 min | 5-10x |
| Other processors | 30 min | 30 min | 1x |
| **Total** | **50 min** | **10-15 min** | **3-5x** |

### Backfills (After Phase 1 + Phase 3)

| Scenario | Before | After | Speedup |
|----------|--------|-------|---------|
| Single date | 10 min | 2 min | 5x |
| 30 dates (serial) | 5 hours | 1 hour | 5x |
| 30 dates (parallel) | 5 hours | 12 min | 25x |

---

## Code Locations

### UPGC (upcoming_player_game_context_processor.py)
- Line 59: ThreadPoolExecutor import (already present!)
- Line 837-888: Batch query + serial storage loop
- Line 1418: Current ThreadPoolExecutor usage (completeness checks only)
- **New code:** ~Line 1300 - Add `_process_players_parallel()`

### PSZA (player_shot_zone_analysis_processor.py)
- Line 610-750: Serial player processing loop
- **New code:** Extract to `_process_single_player_zones()`, add ThreadPoolExecutor

### CompletenessChecker (shared/utils/completeness_checker.py)
- Multiple methods running 5 separate queries
- **New code:** Consolidate to single multi-window query

---

## Related Documentation

- Research: `docs/09-handoff/2025-12-04-SESSION28-PERFORMANCE-OPTIMIZATION-RESEARCH.md`
- Schedule-aware backfills: `docs/09-handoff/2025-12-04-SESSION21-SCHEDULE-AWARE-BACKFILLS.md`
- Phase 5 architecture: `predictions/worker/worker.py` (service pattern reference)

---

## Success Criteria

### Must Have (Phase 1)
- ✅ UPGC processes 460 players in <2 minutes
- ✅ PSZA processes 460 players in <2 minutes
- ✅ Output identical to serial version
- ✅ No increase in error rate
- ✅ Production deployment successful

### Nice to Have (Phase 2-3)
- ✅ Completeness checks <30 seconds (vs 5+ minutes)
- ✅ Date-level parallelization working
- ✅ Backfill month in <15 minutes (vs 5 hours)

---

## Next Steps

1. ✅ Document decision (this file)
2. 🔄 Implement UPGC parallelization
3. ⏳ Implement PSZA parallelization
4. ⏳ Add performance timing
5. ⏳ Test with single date
6. ⏳ Deploy to production

---

## Notes

- Phase 5 service pattern remains an option for future if 10-15 min isn't fast enough
- Implementing parallelization now doesn't prevent service migration later
- Focus on quick wins first, iterate based on results
- ThreadPoolExecutor already imported in UPGC - just need to move it to player processing
