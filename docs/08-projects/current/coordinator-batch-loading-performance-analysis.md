# Coordinator Batch Loading Performance Analysis
**Date:** 2026-01-18
**Session:** 102
**Issue:** Batch historical games loading bypassed due to timeout with large player counts

---

## 🔴 Problem Statement

The `load_historical_games_batch()` optimization in the prediction coordinator is currently **BYPASSED** because it times out with production-scale player counts (300-360 players).

**Current Status:**
- ✅ Works great: 118 players → 0.68s (331x speedup)
- ❌ **Times out**: 300-360 players → >30s (exceeds timeout)
- 🔄 Bypass active since Session 78
- ⚠️ Workers now query individually (~225s total vs <1s batch)

**Code Location:** `predictions/coordinator/coordinator.py:399`

---

## 📊 Performance Measurements

### Tested Performance (Dec 31, 2025)
- **Players:** 118
- **Execution Time:** 0.68 seconds
- **Speedup:** 331x vs sequential (225s → 0.68s)
- **Status:** SUCCESS ✅

### Production Scale (Jan 2026)
- **Typical Players:** 300-360 players on game days
- **Peak Players:** 364 players (Jan 18, 2026)
- **Current Timeout:** 30 seconds
- **Status:** **TIMEOUT** ❌

---

## 🔍 Root Cause Analysis

### 1. Query Timeout Too Aggressive
```python
QUERY_TIMEOUT_SECONDS = 30  # Too low for 300+ players
```

The query works well for small batches but needs more time at scale:
- 118 players: 0.68s ✅
- 300 players: ~2-3s (estimated) ⚠️
- 360 players: Could exceed 30s timeout ❌

### 2. Query Complexity
The batch query includes expensive operations:
```sql
-- Window functions across all players
ROW_NUMBER() OVER (PARTITION BY player_lookup ...)
LAG(game_date) OVER (PARTITION BY player_lookup ...)

-- 90-day lookback across multiple partitions
game_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)

-- Top-N per player (30 games each)
WHERE game_rank <= @max_games
```

### 3. Scaling Characteristics
- **Linear scaling:** Each additional player adds ~50-100 games to scan
- **300 players × 30 games** = 9,000 rows to process
- **360 players × 30 games** = 10,800 rows to process
- Window functions must operate across full result set

### 4. Table Structure (Good)
```
Partitioning: DAY on game_date ✅
Clustering: [universal_player_id, player_lookup, team_abbr, game_date] ✅
```
The table is well-optimized, so the issue is purely timeout-related.

---

## 💡 Proposed Solutions

### Option 1: Increase Timeout (RECOMMENDED)
**Effort:** 5 minutes
**Risk:** Low
**Impact:** Immediate fix

**Change:**
```python
# Before
QUERY_TIMEOUT_SECONDS = 30

# After
QUERY_TIMEOUT_SECONDS = 120  # 2 minutes for 400+ players
```

**Rationale:**
- Query is already well-optimized (partitioned + clustered)
- 0.68s for 118 players suggests ~2-3s for 360 players (linear scaling)
- 120s timeout provides 40-60x buffer for safety
- BigQuery queries are cheap (~$0.01 per 1TB scanned)

**Testing:**
1. Increase timeout to 120s
2. Re-enable batch loading in coordinator
3. Test with production player count (300-360)
4. Monitor for 3 days

---

### Option 2: Chunked Batch Loading
**Effort:** 2 hours
**Risk:** Medium
**Impact:** More complex, better scalability

**Approach:**
```python
def load_historical_games_batch_chunked(
    player_lookups, game_date, chunk_size=100
):
    """Load in chunks of 100 players"""
    all_games = {}
    for i in range(0, len(player_lookups), chunk_size):
        chunk = player_lookups[i:i+chunk_size]
        games = load_historical_games_batch(chunk, game_date)
        all_games.update(games)
    return all_games
```

**Trade-offs:**
- ✅ Guaranteed to work with any player count
- ✅ Each chunk completes quickly (<5s)
- ❌ Multiple BigQuery queries (3-4x for 360 players)
- ❌ Slightly higher cost (but still minimal)

---

### Option 3: Query Optimization
**Effort:** 4-6 hours
**Risk:** Medium-High
**Impact:** Marginal gains

**Potential optimizations:**
1. Remove LAG() calculation (compute client-side)
2. Use ARRAY_AGG instead of multiple window functions
3. Pre-filter to only recent games before windowing

**Analysis:**
- Table is already well-optimized (partitioned + clustered)
- Window functions are necessary for the use case
- Likely to save only 10-20% execution time
- **NOT WORTH THE EFFORT** given Option 1 is simpler

---

### Option 4: Caching Layer
**Effort:** 8+ hours
**Risk:** High
**Impact:** Complex, adds dependencies

**NOT RECOMMENDED** - Over-engineering for a problem that Option 1 solves.

---

## ✅ Recommended Solution

**Implement Option 1: Increase Timeout to 120s**

### Implementation Steps

1. **Update timeout constant** in `predictions/worker/data_loaders.py`:
   ```python
   # Query timeout in seconds - prevents worker hangs on slow/stuck queries
   # Increased from 30s to 120s to support batch loading for 300-400 players
   # Batch loading: 118 players = 0.68s, 360 players ≈ 2-3s (linear scaling)
   QUERY_TIMEOUT_SECONDS = 120
   ```

2. **Re-enable batch loading** in `predictions/coordinator/coordinator.py`:
   - Remove bypass at line 397-401
   - Uncomment lines 403-424
   - Update comment to reflect fix

3. **Add performance logging**:
   ```python
   import time
   start = time.time()
   batch_historical_games = data_loader.load_historical_games_batch(...)
   elapsed = time.time() - start
   logger.info(f"Batch loaded in {elapsed:.2f}s for {len(player_lookups)} players")
   ```

4. **Deploy and monitor**:
   - Deploy to prediction-coordinator
   - Monitor for 3 consecutive game days
   - Verify batch loading completes successfully
   - Check logs for execution times

### Success Criteria
- ✅ Batch loading completes in <10s for 360 players
- ✅ Zero timeouts over 3-day monitoring period
- ✅ Workers receive pre-loaded data (not querying individually)
- ✅ No increase in error rate

### Rollback Plan
If batch loading still times out:
1. Revert to bypass (current state)
2. Implement Option 2 (chunked loading)

---

## 📈 Expected Impact

### Performance Improvement
- **Before (bypassed):** Workers query individually (~225s total)
- **After (fixed):** Coordinator loads once (~2-3s for 360 players)
- **Speedup:** **75-110x faster**

### Cost Impact
- Single BigQuery query vs 360 individual queries
- **Cost savings:** ~99% reduction in BigQuery API calls
- **Absolute cost:** <$0.01 per batch (negligible)

### Operational Benefits
- Reduced worker execution time (more headroom)
- Lower API quota usage
- Better user experience (faster predictions)

---

## 🔬 Testing Plan

### Phase 1: Local Testing (10 minutes)
1. Update timeout to 120s
2. Test with mock data (100, 200, 300 players)
3. Verify no syntax errors

### Phase 2: Staging Testing (1 hour)
1. Deploy to staging environment
2. Test with production-size player lists
3. Monitor execution times
4. Check BigQuery logs for query performance

### Phase 3: Production Rollout (3 days)
1. Deploy to production coordinator
2. Monitor first 3 game days
3. Alert on any timeouts
4. Verify workers using batch data

---

## 📝 Implementation Checklist

- [ ] Update QUERY_TIMEOUT_SECONDS to 120
- [ ] Remove bypass in coordinator.py (lines 397-401)
- [ ] Uncomment batch loading code (lines 403-424)
- [ ] Add performance logging
- [ ] Update TODO comment with fix details
- [ ] Write test for batch loading with 360 players
- [ ] Deploy to staging
- [ ] Test in staging
- [ ] Deploy to production
- [ ] Monitor for 3 days
- [ ] Update documentation
- [ ] Close performance investigation issue

---

## 🎯 Decision

**Proceed with Option 1: Increase Timeout to 120s**

**Reasoning:**
- Simplest solution (5-minute fix)
- Low risk (timeout is a safety valve, not a performance constraint)
- Query is already optimized (partitioned + clustered table)
- Measured performance shows query is fast (0.68s for 118 players)
- Linear scaling suggests 2-3s for 360 players (well under 120s)

**Next Steps:**
1. Implement the fix
2. Test in staging
3. Deploy to production
4. Monitor for 3 days
5. Mark TODO as resolved

---

**Analysis By:** Claude Sonnet 4.5 (Session 102)
**Date:** 2026-01-18
**Status:** Ready for implementation
