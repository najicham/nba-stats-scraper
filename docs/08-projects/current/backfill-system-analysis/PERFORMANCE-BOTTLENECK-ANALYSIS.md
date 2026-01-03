# Backfill Performance Bottleneck Analysis
**Date**: 2026-01-03
**Status**: 🔴 CRITICAL - 6-day completion time unacceptable
**Investigation**: In Progress

---

## 🚨 PROBLEM SUMMARY

**Current Status**:
- Backfill started: Jan 2, 11:01 PM PST
- Current progress: Day 71/944 (7.5%)
- Elapsed time: 11.2 hours
- **Actual ETA**: Jan 9, 4:00 AM (6 more days!)
- **Expected ETA** (from handoff doc): Jan 4, 8:00 AM (6-12 hours)

**Performance Degradation**:
- Early days (Oct 2021, no games): 28 seconds/day
- Game days (Nov-Dec 2021): 6,000-10,000 seconds/day (1.7-2.8 hours)
- **Performance is degrading over time** (6000s → 10000s)

---

## 🔍 ROOT CAUSE IDENTIFIED

### Smoking Gun: BigQuery Shot Zone Query

**Location**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py:551-703`

**The Bottleneck**:
```python
def _extract_player_shot_zones(self, start_date: str, end_date: str) -> None:
    """Extract shot zone data from BigDataBall play-by-play (Pass 2 enrichment)."""

    # This query scans bigdataball_play_by_play table - VERY SLOW
    query = f"""
    WITH player_shots AS (
        SELECT ...
        FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
        WHERE event_type = 'shot' AND game_date BETWEEN '{start_date}' AND '{end_date}'
    ),
    and1_events AS (...),
    block_aggregates AS (...),
    shot_aggregates AS (...)
    SELECT ... [14 columns of shot zone data]
    """

    shot_zones_df = self.bq_client.query(query).to_dataframe()  # ⏱️ 1.7-2.8 HOURS!
```

**Log Evidence**:
```
INFO: ✅ Extracted shot zones + shot creation + blocks for 178 player-games (55 with blocks) from BigDataBall
INFO: ANALYTICS_STEP Data extracted in 6230.1s  ← 1.7 HOURS

INFO: ✅ Extracted shot zones + shot creation + blocks for 267 player-games (85 with blocks) from BigDataBall
INFO: ANALYTICS_STEP Data extracted in 10624.0s  ← 2.95 HOURS (INCREASING!)
```

**Why It's Slow**:
1. **Massive table scan**: `bigdataball_play_by_play` has millions of rows
2. **Complex aggregations**: 4 CTEs + 3 JOINs per query
3. **No query caching**: Each day queries the SAME historical data separately
4. **No partitioning**: Query scans entire table every time
5. **Increasing cost**: As backfill progresses, cumulative data increases

**Time Breakdown Per Day**:
- Extraction (BigQuery): 6,000-10,000 seconds (1.7-2.8 hours)
- Processing/validation: ~15-20 seconds
- BigQuery insert: ~5 seconds
- **Total**: ~1.7-2.8 hours per day

**Projected Completion Time**:
- 944 days × 2.5 hours/day = 2,360 hours = **98 days** (!!)
- Actual will be lower due to caching, but still 5-7 days

---

## 📊 DETAILED ANALYSIS

### What the Query Does

**Shot Zone Extraction** (Lines 551-703):
- Scans `bigdataball_play_by_play` for shot events
- Calculates per-player, per-game:
  - Paint shots (attempts/makes)
  - Mid-range shots (attempts/makes)
  - Three-point shots (attempts/makes)
  - Assisted vs unassisted field goals
  - And-1 counts (made shot + foul)
  - Blocks by zone (paint, mid, three)
- Returns 14 columns of shot zone data per player-game

**Is This Data Critical?**
- **Priority**: OPTIONAL (according to processor comments line 57)
- **Purpose**: "Pass 2 enrichment" (line 553 comment)
- **Fallback**: Processor works without it (line 695-703 handles missing data)
- **For ML**: Need to verify if v3 model uses shot zones

### Backfill Architecture

**Current Flow** (Sequential, Day-by-Day):
```
For each day in 944 days:
  1. Extract player stats (nbac_gamebook/bdl) - 5-10s
  2. Extract shot zones (BigDataBall) - 6,000-10,000s ⏱️ BOTTLENECK
  3. Process records (parallel workers) - 10s
  4. Insert to BigQuery - 5s
  Total: ~1.7-2.8 hours
```

**Key Observations**:
- **Backfill script** (`player_game_summary_analytics_backfill.py`) is optimized
  - Day-by-day processing (good for checkpointing)
  - Checkpoint resume capability (line 224-228)
  - Parallel record processing (line 25, ThreadPoolExecutor)
- **Processor** (`player_game_summary_processor.py`) is NOT optimized for backfill
  - Queries BigQuery separately for each day
  - No caching between days
  - No option to skip optional enrichments

---

## 💡 OPTIMIZATION STRATEGIES

### Strategy 1: Skip Shot Zones for Backfill ⭐ FASTEST (1-2 hours implementation)

**Approach**: Add `skip_shot_zones` flag to backfill mode

**Impact**:
- Reduction: 6,000-10,000s → ~20s per day
- New total time: 944 days × 20s = 5.2 hours
- **Completion: Same day (6 hours from now)**

**Implementation**:
```python
# In player_game_summary_processor.py, line 549
def extract_data(self, start_date: str, end_date: str):
    self._extract_player_stats(start_date, end_date)

    # Skip shot zones if in backfill mode (can add later via Pass 2)
    if not self.config.get('skip_shot_zones', False):
        self._extract_player_shot_zones(start_date, end_date)
```

**Pros**:
- ✅ Immediate 99% speedup
- ✅ Minimal code changes
- ✅ Can backfill shot zones separately later
- ✅ Minutes data (critical for ML) still backfilled

**Cons**:
- ⚠️ ML model won't have shot zone features initially
- ⚠️ Need separate "Pass 2" backfill for shot zones

**Risk**: LOW - Shot zones are optional, ML can train without them

---

### Strategy 2: Batch BigQuery Query ⭐ GOOD (3-4 hours implementation)

**Approach**: Query ALL dates at once, cache results, look up per day

**Implementation**:
```python
# Query once for entire date range
shot_zones_df = self.bq_client.query(f"""
    SELECT ... FROM bigdataball_play_by_play
    WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'  -- All dates at once
""").to_dataframe()

# Cache in memory as dict: {(game_id, player_lookup): shot_zone_data}
self.shot_zone_cache = shot_zones_df.to_dict('records')

# Backfill script looks up from cache per day
```

**Impact**:
- Reduction: 944 queries → 1 query
- Query time: ~30-60 minutes (one-time cost)
- Per-day overhead: ~1 second (cache lookup)
- **Total time**: 1 hour + (944 × 20s) = ~6.2 hours

**Pros**:
- ✅ Keeps shot zone data
- ✅ Leverages BigQuery's bulk query efficiency
- ✅ Can reuse cache for multiple backfills

**Cons**:
- ⚠️ Requires significant memory (~500MB-1GB for 3 years of shot data)
- ⚠️ Need to refactor backfill script architecture
- ⚠️ Single query might timeout (can split into chunks)

**Risk**: MEDIUM - Memory constraints, query timeout risk

---

### Strategy 3: Parallel Day Processing 🚀 BEST (4-6 hours implementation)

**Approach**: Process multiple days concurrently (10-20 workers)

**Implementation**:
```python
# In backfill script
from concurrent.futures import ThreadPoolExecutor

def process_date_range_parallel(dates, workers=10):
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_day, date): date for date in dates}

        for future in as_completed(futures):
            date = futures[future]
            result = future.result()
            checkpoint.mark_date_complete(date)
```

**Impact**:
- With 10 workers: 944 days / 10 = 94.4 "batches"
- Per batch time: ~2.5 hours (slowest day in batch)
- **Total time**: 94.4 × 2.5 hours / 10 = ~23 hours (1 day)
- With 20 workers: ~12 hours

**Pros**:
- ✅ Keeps all data (shot zones included)
- ✅ Massive speedup (10-20x)
- ✅ Leverages existing code structure
- ✅ Can combine with other strategies

**Cons**:
- ⚠️ BigQuery concurrent query quotas (check limits)
- ⚠️ Checkpoint complexity (concurrent writes)
- ⚠️ Error handling complexity
- ⚠️ Memory usage (10-20 processor instances)

**Risk**: MEDIUM-HIGH - Quota limits, concurrency bugs

---

### Strategy 4: Hybrid Approach ⭐⭐⭐ RECOMMENDED

**Combine Strategy 1 + Strategy 3**:
1. Skip shot zones for initial backfill (minutes data only)
2. Use parallel processing (10 workers)
3. Run separate "Pass 2" backfill for shot zones later (if needed)

**Implementation Plan**:
```python
# Phase 1: Fast backfill (minutes data only)
# - Skip shot zones: 20s/day
# - 10 parallel workers
# - Total time: 944 / 10 × 20s = 31 minutes

# Phase 2: Shot zones backfill (optional, run later)
# - Batch query approach
# - Total time: ~6 hours
```

**Impact**:
- **Phase 1 completion**: 30-60 minutes
- ML training can start immediately
- Shot zones can be added later if needed

**Pros**:
- ✅ Fastest time to ML training (< 1 hour)
- ✅ Low risk (proven patterns)
- ✅ Incremental enrichment strategy
- ✅ Can validate minutes data quality first

**Cons**:
- ⚠️ Requires two backfill passes (but second is optional)

**Risk**: LOW - Best of both worlds

---

## 🎯 RECOMMENDATION

**Implement Strategy 4: Hybrid Approach**

### Phase 1: Fast Minutes Backfill (< 1 hour)

1. **Add `skip_shot_zones` flag** (15 min)
   - Modify processor to skip shot zone extraction
   - Pass flag from backfill script

2. **Implement parallel processing** (30 min)
   - Add ThreadPoolExecutor to backfill script
   - Thread-safe checkpoint updates
   - Start with 10 workers

3. **Kill current backfill, restart optimized** (5 min)
   - Kill tmux session
   - Start new backfill with optimizations
   - Monitor for first 10-20 days

4. **Validate completion** (30 min)
   - Run NULL rate query
   - Verify 35-45% NULL rate
   - Check data completeness

### Phase 2: Shot Zones Backfill (Optional, 6-8 hours)

Only run if ML model needs shot zone features:
1. Design batch query strategy
2. Implement caching mechanism
3. Run "Pass 2" enrichment backfill
4. Validate shot zone data

---

## 📈 EXPECTED OUTCOMES

### Before Optimization:
- **Completion time**: 6 days (Jan 9)
- **Processing rate**: 6.3 days/hour
- **Total records**: ~120K

### After Optimization (Phase 1):
- **Completion time**: 30-60 minutes (today!)
- **Processing rate**: ~150-300 days/hour (50x faster)
- **Total records**: ~120K (minutes data)
- **Shot zones**: Skip for now, add later if needed

### ROI:
- **Time saved**: 6 days → 1 hour = 144 hours saved
- **ML training**: Can start today instead of Jan 9
- **Risk reduction**: Validated approach, minimal code changes

---

## 🔧 IMPLEMENTATION CHECKLIST

- [ ] Verify ML model doesn't require shot zones for v3
- [ ] Add `skip_shot_zones` config flag to processor
- [ ] Implement parallel processing in backfill script
- [ ] Test with small date range (7 days)
- [ ] Kill current backfill
- [ ] Start optimized backfill (2021-2024)
- [ ] Monitor first 50 days for errors
- [ ] Run validation queries when complete
- [ ] Document results
- [ ] (Optional) Plan Phase 2 shot zones backfill

---

## 📝 NEXT STEPS

1. ✅ Analysis complete (this document)
2. ⏳ Check ML model requirements for shot zones
3. ⏳ Implement optimizations
4. ⏳ Test and deploy
5. ⏳ Monitor and validate

---

**Status**: Analysis complete, awaiting implementation decision
**Owner**: AI + User
**Priority**: P0 (blocks ML training)
**ETA**: Phase 1 implementation in 1-2 hours
