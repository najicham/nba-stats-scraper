# Phase 3 Parallel Execution - Implementation Plan
**Created:** Dec 31, 2025 1:15 PM ET
**Status:** Ready to Implement
**Impact:** 75% faster (20 min → 5 min)
**Risk:** LOW - Independent processors

---

## Current State Analysis

### Architecture
- **Service:** `nba-phase3-analytics-processors` (Cloud Run)
- **Trigger:** Pub/Sub subscription `nba-phase3-analytics-sub`
- **Topic:** Listens to `nba-phase2-raw-complete`
- **Entry Point:** `data_processors/analytics/main_analytics_service.py`

### 5 Phase 3 Processors (All Independent!)
1. `PlayerGameSummaryProcessor` → `nba_analytics.player_game_summary`
2. `TeamOffenseGameSummaryProcessor` → `nba_analytics.team_offense_game_summary`
3. `TeamDefenseGameSummaryProcessor` → `nba_analytics.team_defense_game_summary`
4. `UpcomingPlayerGameContextProcessor` → `nba_analytics.upcoming_player_game_context`
5. `UpcomingTeamGameContextProcessor` → `nba_analytics.upcoming_team_game_context`

### Current Sequential Execution
**File:** `data_processors/analytics/main_analytics_service.py`
**Lines:** 118-153

```python
results = []
for processor_class in processors_to_run:  # SEQUENTIAL!
    try:
        logger.info(f"Running {processor_class.__name__} for {game_date}")

        processor = processor_class()
        opts = {...}

        success = processor.run(opts)  # Blocks here until complete

        if success:
            stats = processor.get_analytics_stats()
            results.append({"processor": processor_class.__name__, "status": "success", "stats": stats})
        else:
            results.append({"processor": processor_class.__name__, "status": "error"})
    except Exception as e:
        results.append({"processor": processor_class.__name__, "status": "exception", "error": str(e)})
```

**Problem:**
- Each processor waits for previous to complete
- 5 processors × 4 min each = 20 minutes total
- CPU mostly idle waiting for BigQuery

---

## Performance Analysis

### Current Timeline
```
PlayerGameSummaryProcessor:          [████████████] 4 min
TeamOffenseGameSummaryProcessor:                    [████████████] 4 min
TeamDefenseGameSummaryProcessor:                                   [████████████] 4 min
UpcomingPlayerGameContextProcessor:                                               [████████████] 4 min
UpcomingTeamGameContextProcessor:                                                                [████████████] 4 min
TOTAL: 20 minutes
```

### Parallel Timeline
```
All 5 processors:                    [████████████] ~5 min (longest one)
TOTAL: 5 minutes
```

**Speedup:** 75% faster (20 min → 5 min)

---

## Implementation Plan

### Option A: ThreadPoolExecutor (Recommended)
**Why:** Simple, robust, standard library, works with Cloud Run

**Code Changes:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def run_single_processor(processor_class, opts):
    """
    Run a single analytics processor (for parallel execution).

    Args:
        processor_class: Processor class to instantiate
        opts: Options dict for processor.run()

    Returns:
        Dict with processor results
    """
    try:
        logger.info(f"Running {processor_class.__name__} for {opts.get('start_date')}")

        processor = processor_class()
        success = processor.run(opts)

        if success:
            stats = processor.get_analytics_stats()
            logger.info(f"Successfully ran {processor_class.__name__}: {stats}")
            return {
                "processor": processor_class.__name__,
                "status": "success",
                "stats": stats
            }
        else:
            logger.error(f"Failed to run {processor_class.__name__}")
            return {
                "processor": processor_class.__name__,
                "status": "error"
            }
    except Exception as e:
        logger.error(f"Analytics processor {processor_class.__name__} failed: {e}")
        return {
            "processor": processor_class.__name__,
            "status": "exception",
            "error": str(e)
        }

# Replace lines 118-153 with:
results = []
with ThreadPoolExecutor(max_workers=5) as executor:
    # Submit all processors for parallel execution
    futures = {
        executor.submit(run_single_processor, processor_class, opts): processor_class
        for processor_class in processors_to_run
    }

    # Collect results as they complete
    for future in as_completed(futures):
        processor_class = futures[future]
        try:
            result = future.result(timeout=600)  # 10 min timeout per processor
            results.append(result)
        except TimeoutError:
            logger.error(f"Processor {processor_class.__name__} timed out after 10 minutes")
            results.append({
                "processor": processor_class.__name__,
                "status": "timeout"
            })
        except Exception as e:
            logger.error(f"Failed to get result from {processor_class.__name__}: {e}")
            results.append({
                "processor": processor_class.__name__,
                "status": "exception",
                "error": str(e)
            })
```

### Option B: asyncio (More Complex)
**Why:** Maximum concurrency, but requires more refactoring
**Not Recommended:** Processors use synchronous BigQuery client

---

## Deployment Steps

### Step 1: Update main_analytics_service.py
1. Import ThreadPoolExecutor at top:
   ```python
   from concurrent.futures import ThreadPoolExecutor, as_completed
   ```

2. Add helper function `run_single_processor()` above `process_analytics()`

3. Replace for-loop (lines 118-153) with parallel executor code

4. **ALSO update** `/process-date-range` endpoint (lines 226-258) for manual triggers!

### Step 2: Test Locally
```bash
# Test with manual trigger
curl -X POST https://nba-phase3-analytics-processors-*.run.app/process-date-range \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2025-12-30", "end_date": "2025-12-30", "processors": ["PlayerGameSummaryProcessor", "TeamOffenseGameSummaryProcessor"]}'
```

**Expected:** Both processors run simultaneously, complete in ~4-5 min instead of 8 min

### Step 3: Deploy
```bash
cd /home/naji/code/nba-stats-scraper
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Step 4: Monitor First Run
- Check Cloud Run logs for parallel execution
- Verify all 5 processors complete successfully
- Confirm timing improved from ~20 min to ~5 min

---

## Safety & Rollback

### Why This is Safe
✅ **Independent processors:** Each writes to different BigQuery table
✅ **No shared state:** No race conditions
✅ **Idempotent writes:** Processors use MERGE/upsert patterns
✅ **Standard library:** ThreadPoolExecutor is battle-tested
✅ **Failure isolation:** One processor failure doesn't block others

### Potential Issues
⚠️ **BigQuery rate limits:** 5 concurrent queries might hit limits
   - **Mitigation:** Start with max_workers=3, increase to 5 if no issues
   - **Monitoring:** Check for "rateLimitExceeded" errors in logs

⚠️ **Memory usage:** 5 processors in memory simultaneously
   - **Mitigation:** Cloud Run has 2+ GB memory, processors are lightweight
   - **Monitoring:** Check Cloud Run memory metrics

⚠️ **Timeout issues:** Overall Cloud Run timeout
   - **Mitigation:** Timeout is 3600s (1 hour), plenty for 5-min parallel run
   - **Per-processor timeout:** 600s (10 min) with future.result(timeout=600)

### Rollback Plan
If issues occur:
1. Revert `main_analytics_service.py` to sequential for-loop
2. Redeploy: `./bin/analytics/deploy/deploy_analytics_processors.sh`
3. System returns to previous 20-min sequential behavior

**Git Revert:**
```bash
git revert <commit-hash>
git push
./bin/analytics/deploy/deploy_analytics_processors.sh
```

---

## Testing Checklist

### Before Deployment
- [ ] Code review of changes
- [ ] Local syntax check: `python -m py_compile data_processors/analytics/main_analytics_service.py`
- [ ] Verify imports work

### After Deployment
- [ ] Health check: `curl https://nba-phase3-analytics-processors-*.run.app/health`
- [ ] Manual trigger test: `/process-date-range` with 2 processors
- [ ] Check logs for "Running X for..." messages appearing simultaneously
- [ ] Verify no "rateLimitExceeded" errors

### Production Validation
- [ ] Wait for natural Phase 2 → Phase 3 trigger (1-3 AM ET next day)
- [ ] Check cascade timing query shows Phase 3 completion in ~5 min
- [ ] Verify all 5 analytics tables updated correctly
- [ ] Compare record counts to previous day (should be similar)

---

## Success Metrics

**Before:**
- Phase 3 total time: ~20 minutes
- Processors run sequentially
- Logs show 5 separate "Running..." → "Successfully ran..." sequences

**After:**
- Phase 3 total time: ~5 minutes (75% faster!)
- Processors run in parallel
- Logs show 5 "Running..." messages nearly simultaneously
- All 5 "Successfully ran..." messages within ~1 minute of each other

**Query to Track:**
```sql
SELECT
  DATE(started_at, 'America/New_York') as run_date,
  processor_name,
  FORMAT_TIMESTAMP('%H:%M:%S ET', started_at, 'America/New_York') as start_time,
  FORMAT_TIMESTAMP('%H:%M:%S ET', completed_at, 'America/New_York') as end_time,
  TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds
FROM nba_reference.processor_run_history
WHERE processor_name IN (
  'PlayerGameSummaryProcessor',
  'TeamOffenseGameSummaryProcessor',
  'TeamDefenseGameSummaryProcessor',
  'UpcomingPlayerGameContextProcessor',
  'UpcomingTeamGameContextProcessor'
)
AND DATE(started_at, 'America/New_York') >= CURRENT_DATE('America/New_York') - 2
ORDER BY started_at DESC
LIMIT 25
```

---

## Next Steps

After Phase 3 parallelization succeeds:
1. **Phase 4 Parallelization:** Similar pattern in `precompute/main_precompute_service.py`
2. **Phase 1 Parallelization:** Parallel scraper execution in workflow executor
3. **Monitoring Dashboard:** Add Phase 3 parallelization metrics

---

**Status:** ✅ READY TO IMPLEMENT
**Estimated Implementation Time:** 1 hour
**Estimated Testing Time:** 1 hour
**Total:** 2 hours for 75% speedup!
