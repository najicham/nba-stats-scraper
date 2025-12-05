# Session 31 - Parallelize All Remaining Processors

**Date:** 2025-12-04
**Focus:** Apply player/team-level parallelization to ALL Phase 3 & Phase 4 processors
**Status:** 🚧 IN PROGRESS
**Previous Work:** Sessions 29-30 (UPGC + PSZA parallelization complete)

---

## Mission

Apply ThreadPoolExecutor parallelization pattern to **ALL remaining processors** in Phase 3 (Analytics) and Phase 4 (Precompute). This will reduce daily processing time from ~50 minutes to ~5-10 minutes (5-10x speedup).

---

## Completed in Previous Sessions

### ✅ Session 29: UPGC Parallelization
**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- **Lines 1467-1746**: Added parallelization with feature flag
- **Performance:** 389 players in 33.2s (11+ players/sec)
- **Speedup:** ~10x

### ✅ Session 30: PSZA Parallelization
**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- **Lines 612-1056**: Added parallelization with feature flag
- **Performance:** 438 players in 0.8s (486-510 players/sec)
- **Speedup:** ~600x

---

## Processors to Parallelize (Prioritized)

### **Priority 1 - HIGH IMPACT** (Do These First)

#### 1. Player Composite Factors (PCF) - Phase 4
**File:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
- **Entity Type:** Player (~450 entities)
- **Processing Pattern:** Complex similarity calculations
- **Expected Speedup:** 10x (similar to UPGC)
- **Impact:** ~8-10 min daily savings
- **Loop Location:** Look for `for player_lookup in all_players:` pattern
- **Feature Flag:** `ENABLE_PLAYER_PARALLELIZATION`

#### 2. ML Feature Store (MLFS) - Phase 4
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- **Entity Type:** Player (~450 entities)
- **Processing Pattern:** Feature engineering for ML
- **Expected Speedup:** 5-10x
- **Impact:** ~5-8 min daily savings
- **Loop Location:** Look for player loop pattern
- **Feature Flag:** `ENABLE_PLAYER_PARALLELIZATION`

#### 3. Player Game Summary (PGS) - Phase 3
**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- **Entity Type:** Player (~450 entities)
- **Processing Pattern:** Game-level aggregations
- **Expected Speedup:** 5-10x
- **Impact:** ~3-5 min daily savings
- **Loop Location:** Look for player loop pattern
- **Feature Flag:** `ENABLE_PLAYER_PARALLELIZATION`

---

### **Priority 2 - MEDIUM IMPACT** (Do After P1)

#### 4. Player Daily Cache (PDC) - Phase 4
**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- **Entity Type:** Player (~450 entities)
- **Processing Pattern:** Cache updates
- **Expected Speedup:** 3-5x
- **Impact:** ~2-3 min daily savings
- **Loop Location:** Look for player loop pattern
- **Feature Flag:** `ENABLE_PLAYER_PARALLELIZATION`

#### 5. Team Defense Zone Analysis (TDZA) - Phase 4
**File:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
- **Entity Type:** Team (~30 entities)
- **Processing Pattern:** Zone analysis calculations
- **Expected Speedup:** 3-5x
- **Impact:** ~2-3 min daily savings
- **Loop Location:** Look for `for team in all_teams:` pattern
- **Feature Flag:** `ENABLE_TEAM_PARALLELIZATION` (different flag for teams!)

---

### **Priority 3 - LOW IMPACT BUT DO ANYWAY** (Do Last)

#### 6. Upcoming Team Game Context (UTGC) - Phase 3
**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`
- **Entity Type:** Team (~30 entities)
- **Processing Pattern:** Context calculations
- **Expected Speedup:** 2-3x
- **Impact:** ~1-2 min daily savings
- **Feature Flag:** `ENABLE_TEAM_PARALLELIZATION`

#### 7. Team Defense Game Summary (TDGS) - Phase 3
**File:** `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- **Entity Type:** Team (~30 entities)
- **Processing Pattern:** Game summary aggregations
- **Expected Speedup:** 2-3x
- **Impact:** ~1 min daily savings
- **Feature Flag:** `ENABLE_TEAM_PARALLELIZATION`

#### 8. Team Offense Game Summary (TOGS) - Phase 3
**File:** `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
- **Entity Type:** Team (~30 entities)
- **Processing Pattern:** Game summary aggregations
- **Expected Speedup:** 2-3x
- **Impact:** ~1 min daily savings
- **Feature Flag:** `ENABLE_TEAM_PARALLELIZATION`

---

## Parallelization Pattern (Copy This!)

### Step 1: Add Imports
```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
```

### Step 2: Replace Serial Loop with Feature Flag

**Find the existing loop** (around line 600-800):
```python
for entity in all_entities:
    try:
        # ... existing processing logic ...
        successful.append(result)
    except Exception as e:
        failed.append(error)

self.transformed_data = successful
self.failed_entities = failed
```

**Replace with:**
```python
# Feature flag for parallelization
ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'
# Note: Use ENABLE_TEAM_PARALLELIZATION for team processors!

if ENABLE_PARALLELIZATION:
    successful, failed = self._process_entities_parallel(
        all_entities, completeness_results, is_bootstrap, is_season_boundary, analysis_date
    )
else:
    successful, failed = self._process_entities_serial(
        all_entities, completeness_results, is_bootstrap, is_season_boundary, analysis_date
    )

self.transformed_data = successful
self.failed_entities = failed
```

### Step 3: Add Parallel Processing Method

```python
def _process_entities_parallel(self, all_entities, completeness_results,
                                is_bootstrap, is_season_boundary, analysis_date):
    """Process all entities using ThreadPoolExecutor for parallelization."""
    # Determine worker count
    max_workers = min(10, os.cpu_count() or 1)
    logger.info(f"Processing {len(all_entities)} entities with {max_workers} workers (parallel mode)")

    # Performance timing
    loop_start = time.time()
    processed_count = 0

    # Thread-safe result collection
    successful = []
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all entity tasks
        futures = {
            executor.submit(
                self._process_single_entity,
                entity, completeness_results, is_bootstrap, is_season_boundary, analysis_date
            ): entity
            for entity in all_entities
        }

        # Collect results as they complete
        for future in as_completed(futures):
            entity = futures[future]
            processed_count += 1

            try:
                success, data = future.result()
                if success:
                    successful.append(data)
                else:
                    failed.append(data)

                # Progress logging every 50 entities
                if processed_count % 50 == 0:
                    elapsed = time.time() - loop_start
                    rate = processed_count / elapsed
                    remaining = len(all_entities) - processed_count
                    eta = remaining / rate if rate > 0 else 0
                    logger.info(
                        f"Entity processing progress: {processed_count}/{len(all_entities)} "
                        f"| Rate: {rate:.1f} entities/sec | ETA: {eta/60:.1f}min"
                    )
            except Exception as e:
                logger.error(f"Error processing {entity}: {e}")
                failed.append({
                    'entity_id': entity,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })

    # Final timing summary
    total_time = time.time() - loop_start
    logger.info(
        f"Completed {len(successful)} entities in {total_time:.1f}s "
        f"(avg {total_time/len(successful) if successful else 0:.2f}s/entity) "
        f"| {len(failed)} failed"
    )

    return successful, failed
```

### Step 4: Add Single Entity Processor

```python
def _process_single_entity(self, entity, completeness_results,
                            is_bootstrap, is_season_boundary, analysis_date):
    """Process one entity (thread-safe). Returns (success: bool, data: dict)."""
    try:
        # Copy ALL the logic from the original loop body here
        # Make sure to:
        # 1. Get completeness for this entity
        # 2. Check circuit breaker
        # 3. Filter data for this entity
        # 4. Calculate metrics
        # 5. Build output record
        # 6. Return (True, record) on success
        # 7. Return (False, error_dict) on failure

        # ... (copy existing loop body logic) ...

        return (True, record)

    except Exception as e:
        return (False, {
            'entity_id': entity,
            'reason': str(e),
            'category': 'PROCESSING_ERROR',
            'can_retry': False
        })
```

### Step 5: Add Serial Fallback

```python
def _process_entities_serial(self, all_entities, completeness_results,
                               is_bootstrap, is_season_boundary, analysis_date):
    """Original serial processing (kept for fallback)."""
    logger.info(f"Processing {len(all_entities)} entities (serial mode)")

    successful = []
    failed = []

    # Copy the ORIGINAL loop code here (before parallelization)
    for entity in all_entities:
        try:
            # ... original logic ...
            successful.append(record)
        except Exception as e:
            logger.error(f"Failed to process {entity}: {e}")
            failed.append({
                'entity_id': entity,
                'reason': str(e),
                'category': 'PROCESSING_ERROR',
                'can_retry': False
            })

    return successful, failed
```

---

## Testing Each Processor

After implementing parallelization for each processor, test it:

```bash
# Test with parallelization enabled (default)
PYTHONPATH=. python3 data_processors/{phase}/{processor}/{processor}_processor.py 2021-11-15

# Test with parallelization disabled
ENABLE_PLAYER_PARALLELIZATION=false PYTHONPATH=. python3 data_processors/{phase}/{processor}/{processor}_processor.py 2021-11-15
```

**Look for in output:**
- `Processing N entities with M workers (parallel mode)` - confirms parallel mode
- `Rate: X entities/sec` - should be HIGH (50-500+/sec)
- `Completed N entities in X.Xs` - should be FAST (seconds, not minutes)

---

## Important Notes

### Feature Flags
- **Player processors:** Use `ENABLE_PLAYER_PARALLELIZATION`
- **Team processors:** Use `ENABLE_TEAM_PARALLELIZATION`
- Both default to `'true'`
- Can disable instantly: `ENABLE_X_PARALLELIZATION=false`

### Thread Safety
- ✅ **SAFE:** Reading from `self.raw_data` (read-only DataFrame)
- ✅ **SAFE:** Calling pure calculation functions
- ✅ **SAFE:** Building result dicts
- ❌ **UNSAFE:** Appending to `self.transformed_data` directly
- ❌ **UNSAFE:** Modifying shared state

**Solution:** Collect results in local lists, then assign to `self.transformed_data` at the end

### Worker Count
- Use `min(10, os.cpu_count() or 1)` for player processors (450 entities)
- Use `min(5, os.cpu_count() or 1)` for team processors (30 entities)

---

## Expected Results

### After All P1 Processors (PCF, MLFS, PGS)
- Daily processing: 50 min → 15-20 min
- Backfill single date: 30 min → 3-5 min
- **Cumulative savings:** ~25-30 min/day

### After All P2 Processors (PDC, TDZA)
- Daily processing: 15-20 min → 8-12 min
- **Additional savings:** ~5-8 min/day

### After All P3 Processors (UTGC, TDGS, TOGS)
- Daily processing: 8-12 min → 5-10 min
- **Additional savings:** ~3-5 min/day

### **TOTAL IMPACT**
- **Before:** ~50 minutes daily
- **After:** ~5-10 minutes daily
- **Speedup:** 5-10x across entire pipeline! 🚀

---

## Workflow for Next Session

1. **Start with P1 processors** (highest impact)
   - Do PCF first (most complex, similar to UPGC)
   - Then MLFS
   - Then PGS

2. **Test each one** after implementation
   - Run on 2021-11-15 (known good date)
   - Verify parallel mode logs
   - Check performance metrics

3. **Move to P2 processors**
   - PDC
   - TDZA

4. **Finish with P3 processors**
   - UTGC, TDGS, TOGS (quick wins, small gains)

5. **Create final handoff doc** with:
   - All performance metrics
   - Before/after comparisons
   - Deployment instructions
   - Feature flag documentation

---

## Reference Files

**Working examples:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` (lines 1467-1746)
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` (lines 612-1056)

**Documentation:**
- `docs/09-handoff/2025-12-04-SESSION29-PERFORMANCE-OPTIMIZATION-HANDOFF.md`
- `docs/08-projects/current/backfill/PERFORMANCE-OPTIMIZATION-IMPLEMENTATION.md`

---

## Success Criteria

✅ All 8 processors have parallelization implemented
✅ All processors tested on 2021-11-15
✅ Feature flags working for instant rollback
✅ Performance logging showing speedups
✅ Daily processing time reduced from 50min to 5-10min

---

**READY TO START - BEGIN WITH PLAYER_COMPOSITE_FACTORS!** 🚀
