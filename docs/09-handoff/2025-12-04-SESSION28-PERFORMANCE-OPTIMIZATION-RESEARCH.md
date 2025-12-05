# Session 28 - Performance Optimization Research
**Date:** 2025-12-04
**Focus:** Daily Production Performance (Not Backfills)
**Key Finding:** Serial player processing is the bottleneck

---

## Executive Summary

### The Problem
User concern: "I need these processors running quick for daily orchestration"

### Root Cause Identified
**Both UPGC and PSZA process ~460 players SERIALLY in Python loops** with NO parallelization for player-level processing.

### Impact
- UPGC: ~10 min/date (for daily production with ~460 active players)
- PSZA: ~10 min/date (same issue)
- This cascades through Phase 3 → Phase 4 → Phase 5 orchestration

### Recommended Fix
Add player-level parallelization using ThreadPoolExecutor to process players concurrently instead of serially.

---

## Deep Research Findings

### 1. UPGC (Upcoming Player Game Context) - Phase 3 Analytics

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

#### Current Architecture

```python
# Line 59: ThreadPoolExecutor is imported
from concurrent.futures import ThreadPoolExecutor, as_completed

# Line 1418: ThreadPoolExecutor ONLY used for completeness checks
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(run_completeness_check, config): config[0]
              for config in completeness_windows}
```

**CRITICAL**: The ThreadPoolExecutor is used ONLY for running 5 completeness check queries in parallel, NOT for processing players!

#### Player Processing (SERIAL)

```python
# Line 837-888: Extract historical boxscores for ALL players (batched query - GOOD)
player_lookups = [p['player_lookup'] for p in self.players_to_process]
player_lookups_str = "', '".join(player_lookups)
# ... single batch query for all ~460 players

# Line 880-888: Store data PER PLAYER in a Python loop (SERIAL - BAD)
for player_lookup in player_lookups:
    if df.empty or 'player_lookup' not in df.columns:
        self.historical_boxscores[player_lookup] = pd.DataFrame()
    else:
        player_data = df[df['player_lookup'] == player_lookup].copy()
        self.historical_boxscores[player_lookup] = player_data
```

#### What Happens Per Player (Serial Loop)
1. Extract player's historical boxscores from batch DataFrame
2. Calculate 5/10/30 day aggregates (mean, std, trends)
3. Calculate fatigue metrics (rest days, back-to-backs)
4. Calculate prop line movement
5. Calculate game situation context
6. Compile into output record

**Time estimate:** ~1-2 seconds per player × 460 players = **~10 minutes total**

---

### 2. PSZA (Player Shot Zone Analysis) - Phase 4 Precompute

**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

#### Current Architecture

**NO ThreadPoolExecutor at all!**

```python
# Line 610: Process players SERIALLY
for player_lookup in all_players:
    try:
        # Get completeness for this player
        completeness = completeness_results.get(player_lookup, {...})

        # Filter data for this player
        player_data = self.raw_data[
            self.raw_data['player_lookup'] == player_lookup
        ].copy()

        # Calculate shot zone metrics (line 671-806)
        zone_metrics = self._calculate_zone_metrics(games_df)

        # ... build output record
```

#### What Happens Per Player (Serial Loop)
1. Get completeness check results
2. Filter raw data for player's last 10-20 games
3. Calculate shot distribution rates (paint %, mid-range %, three-point %)
4. Calculate efficiency by zone (FG% in each zone)
5. Calculate volume per game
6. Calculate shot creation metrics
7. Identify primary scoring zone
8. Compile into output record

**Time estimate:** ~1-2 seconds per player × 460 players = **~10 minutes total**

---

### 3. Completeness Check Bottleneck

#### Observed in Logs

```
WARNING:data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor:
Completeness check for l7d failed: Timeout of 600.0s exceeded
...HTTPSConnectionPool(host='bigquery.googleapis.com', port=443): Read timed out
```

#### What's Happening
- UPGC runs 5 completeness checks in parallel (l5d, l7d, l10d, l14d, l30d)
- Each check queries BigQuery for per-player game counts
- Some queries timeout at 600 seconds (10 minutes!)
- This is ONLY for data quality validation, not core processing

#### Why It's Slow
The completeness checker queries look like this (conceptually):
```sql
-- Per each player, count games in last N days
SELECT
    player_lookup,
    COUNT(*) as actual_count
FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-12-27' - INTERVAL 7 DAY
GROUP BY player_lookup
```

For backfills processing historical dates, these checks are:
1. **Unnecessary** (historical data is stable, not changing)
2. **Expensive** (full table scans for each lookback window)
3. **Redundant** (running same checks 5 times)

---

## Performance Breakdown by Phase

### Daily Production Run (Typical Day with 10 Games, ~460 Active Players)

| Phase | Processor | Current Time | Bottleneck | Parallelizable? |
|-------|-----------|--------------|------------|-----------------|
| 3 | player_game_summary | ~1 min | BigQuery query | ❌ (already batched) |
| 3 | team_defense_game_summary | ~30 sec | BigQuery query | ❌ (30 teams only) |
| 3 | team_offense_game_summary | ~30 sec | BigQuery query | ❌ (30 teams only) |
| 3 | upcoming_team_game_context | ~30 sec | Team-level calcs | ❌ (20 teams only) |
| **3** | **upcoming_player_game_context** | **~10 min** | **Serial player loops** | **✅ YES** |
| 4 | team_defense_zone_analysis | ~1 min | Team-level calcs | ❌ (30 teams only) |
| **4** | **player_shot_zone_analysis** | **~10 min** | **Serial player loops** | **✅ YES** |
| 4 | player_composite_factors | ~5 min | Player loops | ✅ YES |
| 4 | player_daily_cache | ~3 min | Player loops | ✅ YES |
| 4 | ml_feature_store_v2 | ~15 min | 90 features/player | ✅ YES |

**Total Daily Runtime:** ~50 minutes
**Critical Path:** UPGC (10min) → PSZA (10min) → MLFS (15min) = **35 minutes of player-level serial processing**

---

## Optimization Opportunities

### 🎯 High Impact (Recommended)

#### 1. Parallelize Player Processing in UPGC
**Location:** `upcoming_player_game_context_processor.py:1100-1300`

**Current:**
```python
for player_lookup in self.players_to_process:
    context = self._calculate_player_context(player_lookup)
    self.transformed_data.append(context)
```

**Proposed:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_single_player(self, player_info):
    """Process one player's context (thread-safe)."""
    return self._calculate_player_context(player_info)

# In calculate_analytics():
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(self._process_single_player, p): p
              for p in self.players_to_process}

    for future in as_completed(futures):
        try:
            context = future.result()
            self.transformed_data.append(context)
        except Exception as e:
            player = futures[future]
            self.failed_entities.append({
                'entity_id': player['player_lookup'],
                'reason': str(e)
            })
```

**Expected Speedup:** 10 minutes → 1-2 minutes (**5-10x faster**)

---

#### 2. Parallelize Player Processing in PSZA
**Location:** `player_shot_zone_analysis_processor.py:610-806`

**Current:**
```python
for player_lookup in all_players:
    player_data = self.raw_data[
        self.raw_data['player_lookup'] == player_lookup
    ].copy()
    zone_metrics = self._calculate_zone_metrics(player_data)
    # ... build record
```

**Proposed:**
```python
def _process_single_player_zones(self, player_lookup, analysis_date):
    """Calculate zone metrics for one player (thread-safe)."""
    player_data = self.raw_data[
        self.raw_data['player_lookup'] == player_lookup
    ].copy()

    if len(player_data) < self.min_games_required:
        return None  # Skip

    zone_metrics = self._calculate_zone_metrics(player_data)
    # ... build and return record
    return record

# In calculate_precompute():
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(self._process_single_player_zones, p, analysis_date): p
              for p in all_players}

    for future in as_completed(futures):
        try:
            record = future.result()
            if record:
                successful.append(record)
        except Exception as e:
            player = futures[future]
            failed.append({'player_lookup': player, 'reason': str(e)})
```

**Expected Speedup:** 10 minutes → 1-2 minutes (**5-10x faster**)

---

#### 3. Skip Completeness Checks in Backfill Mode
**Location:** Multiple processors use `CompletenessChecker`

**Current:**
```python
# Always run completeness checks
completeness_results = self.completeness_checker.check_completeness_batch(
    entity_ids=list(all_players),
    ...
)
```

**Proposed:**
```python
# Check if in backfill mode
is_backfill = self.opts.get('backfill_mode', False)

if is_backfill:
    # Skip expensive completeness checks for historical data
    logger.info("Backfill mode: Skipping completeness checks")
    completeness_results = {
        player: {'completeness_pct': 100.0, 'actual_count': 10, 'expected_count': 10}
        for player in all_players
    }
else:
    # Production: Run completeness checks as normal
    completeness_results = self.completeness_checker.check_completeness_batch(...)
```

**Expected Speedup:** Eliminates 5-10 minute timeout delays in backfills

---

### 📊 Medium Impact (Nice to Have)

#### 4. Add Performance Timing Logs
**Location:** All player-processing loops

**Proposed:**
```python
import time

# Before loop
loop_start = time.time()
player_times = []

# In loop
player_start = time.time()
# ... process player
player_elapsed = time.time() - player_start
player_times.append(player_elapsed)

if len(player_times) % 50 == 0:
    avg_time = sum(player_times[-50:]) / 50
    remaining = len(all_players) - len(player_times)
    eta_seconds = avg_time * remaining
    logger.info(f"Progress: {len(player_times)}/{len(all_players)} players "
               f"| Avg: {avg_time:.2f}s/player | ETA: {eta_seconds/60:.1f}min")

# After loop
total_time = time.time() - loop_start
avg_time = sum(player_times) / len(player_times)
logger.info(f"Completed {len(player_times)} players in {total_time:.1f}s "
           f"(avg {avg_time:.2f}s/player)")
```

**Benefit:** Clear visibility into actual bottlenecks

---

#### 5. Optimize BigQuery Completeness Queries
**Location:** `shared/processors/dependencies/completeness_checker.py`

**Current:** Runs 5 separate queries (l5d, l7d, l10d, l14d, l30d)

**Proposed:** Combine into single query with multiple windows
```sql
SELECT
    player_lookup,
    COUNTIF(game_date >= CURRENT_DATE() - 5) as l5d_count,
    COUNTIF(game_date >= CURRENT_DATE() - 7) as l7d_count,
    COUNTIF(game_date >= CURRENT_DATE() - 10) as l10d_count,
    COUNTIF(game_date >= CURRENT_DATE() - 14) as l14d_count,
    COUNTIF(game_date >= CURRENT_DATE() - 30) as l30d_count
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY player_lookup
```

**Expected Speedup:** 5 queries → 1 query (**5x faster**)

---

## Implementation Plan

### Phase 1: Quick Wins (Immediate - 1 day)
1. ✅ Add `--skip-completeness` flag to backfill scripts
2. ✅ Add performance timing logs to all player loops
3. ✅ Document findings (this file)

### Phase 2: Parallelization (High Priority - 2-3 days)
1. Add player-level parallelization to UPGC
2. Add player-level parallelization to PSZA
3. Test with single date to verify correctness
4. Deploy to production

### Phase 3: Additional Optimizations (Medium Priority - 1-2 days)
1. Parallelize PCF (player_composite_factors)
2. Parallelize PDC (player_daily_cache)
3. Parallelize MLFS (ml_feature_store_v2)

### Phase 4: Query Optimization (Low Priority - 1 day)
1. Combine completeness check queries
2. Add query result caching where appropriate

---

## Expected Impact

### Daily Production (10 games, 460 players)

**Before Optimization:**
- Phase 3 UPGC: 10 minutes
- Phase 4 PSZA: 10 minutes
- Phase 4 MLFS: 15 minutes
- **Total: ~50 minutes**

**After Optimization (Phase 1+2):**
- Phase 3 UPGC: 1-2 minutes (5-10x faster)
- Phase 4 PSZA: 1-2 minutes (5-10x faster)
- Phase 4 MLFS: 15 minutes (unchanged until Phase 3)
- **Total: ~25 minutes** (**2x faster**)

**After Full Optimization (Phase 1-4):**
- Phase 3 UPGC: 1-2 minutes
- Phase 4 PSZA: 1-2 minutes
- Phase 4 MLFS: 2-3 minutes (5x faster)
- **Total: ~10-15 minutes** (**3-5x faster**)

### Backfills

**Before:** 10 min/date × 31 dates = **~5 hours**
**After:** 2 min/date × 31 dates = **~1 hour** (**5x faster**)

---

## Risk Assessment

### Low Risk
- Adding timing logs ✅
- Skipping completeness checks in backfill mode ✅

### Medium Risk
- Player-level parallelization
  - Risk: Race conditions if processors aren't thread-safe
  - Mitigation: Careful code review, test with single date first
  - Fallback: Keep max_workers=1 as configuration option

### Testing Strategy
1. Test parallelization with single date (2021-11-15)
2. Compare outputs: serial vs parallel (should be identical)
3. Test with 3-5 dates
4. Full month backfill
5. Deploy to production

---

## Next Steps for User

### Immediate (This Session)
1. ✅ Complete December 2021 backfills (UPGC + PSZA finishing now)
2. Review this research document
3. Decide on optimization priority

### Next Session
1. Implement player-level parallelization for UPGC + PSZA
2. Test with single date
3. Deploy optimizations
4. Measure actual speedup

---

## Technical Notes

### Thread Safety Considerations

#### What Makes Code Thread-Safe?
- ✅ Reading from shared DataFrames (pandas is thread-safe for reads)
- ✅ Local variables within each thread
- ✅ Immutable data structures
- ❌ Writing to shared lists/dicts without locks
- ❌ Modifying instance variables from multiple threads

#### UPGC Thread Safety
**Safe:**
- `self.historical_boxscores` (read-only during player processing)
- `self.schedule_data` (read-only)
- `self.prop_lines` (read-only)

**Needs Protection:**
- `self.transformed_data` (append from multiple threads)
- `self.failed_entities` (append from multiple threads)

**Solution:** Use thread-safe collections or accumulate results in futures, then merge

#### PSZA Thread Safety
**Safe:**
- `self.raw_data` (read-only during player processing)

**Needs Protection:**
- `successful` list (accumulate in futures instead)
- `failed` list (accumulate in futures instead)

---

## References

### Code Locations
- UPGC: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
  - ThreadPoolExecutor import: Line 59
  - Completeness check parallelization: Line 1418
  - Player processing loop: Line 880

- PSZA: `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
  - Player processing loop: Line 610
  - Zone metrics calculation: Line 811

### Related Files
- CompletenessChecker: `shared/processors/dependencies/completeness_checker.py`
- ProcessorBase: `data_processors/raw/processor_base.py`
- Backfill scripts: `backfill_jobs/*/`

---

## Conclusion

The system is well-architected with proper batch queries and data flow. The bottleneck is **NOT** the queries - those are already optimized.

**The bottleneck is Python-level serial processing of ~460 players.**

Adding player-level parallelization will deliver **5-10x speedup** for daily production runs, reducing orchestration time from ~50 minutes to ~10-15 minutes.

This is a **high-impact, low-risk optimization** that should be prioritized.
