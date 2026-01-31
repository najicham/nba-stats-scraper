# Session 47 Start Prompt

## Context

Read the Session 46 handoff first:
```bash
cat docs/09-handoff/2026-01-30-SESSION-46-FATIGUE-FIX-HANDOFF.md
```

## Critical Bug to Fix

There's a bug in the `PlayerCompositeFactorsProcessor` where **ProcessPoolExecutor produces wrong `fatigue_score` values** (0 instead of 100), but serial processing works correctly.

### Evidence

```python
# Parallel processing (ProcessPoolExecutor):
fatigue_score = 0  # WRONG
JSON_VALUE(fatigue_context_json, '$.final_score') = 100  # Correct in JSON

# Serial processing:
fatigue_score = 100  # CORRECT
```

### The Code

The fix was applied in commits `cec08a99` and `c475cb9e`:
- `data_processors/precompute/player_composite_factors/worker.py` line 140:
  ```python
  'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],
  ```
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` line 1609:
  ```python
  'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],
  ```

Both code paths have the fix, but only serial processing produces correct results.

### Suspected Causes

1. **ProcessPoolExecutor loads cached .pyc files** with old code in subprocess
2. **Module import issue** in worker subprocess
3. **Pickling/unpickling issue** with the record dict
4. **Some post-processing** that overwrites fatigue_score after worker returns

## Your Task

1. **Investigate why ProcessPoolExecutor produces wrong values** when the code is correct
2. **Find the root cause** - add debug logging, trace the data flow
3. **Fix the parallel processing** so it works correctly
4. **Test the fix** by running:
   ```bash
   PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py --dates="2026-01-30"
   ```
5. **Verify with BigQuery:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT AVG(fatigue_score) as avg, COUNTIF(fatigue_score > 0) as correct
   FROM nba_precompute.player_composite_factors
   WHERE game_date = '2026-01-30'"
   ```

## Key Files

- `data_processors/precompute/player_composite_factors/worker.py` - Worker function for ProcessPoolExecutor
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - Main processor (lines 1235-1339 for parallel processing)
- `data_processors/precompute/player_composite_factors/factors/fatigue_factor.py` - Fatigue factor calculator

## Debugging Approach

1. Add print/logging in the worker to trace `fatigue_score` value before return
2. Check if `factor_contexts['fatigue_context_json']['final_score']` is correct in worker
3. Add logging after `future.result()` in processor to see what comes back
4. Compare pickled vs unpickled record to see if data changes

## After Fixing

1. Deploy Phase 4: `./bin/deploy-service.sh nba-phase4-precompute-processors`
2. Re-run backfill for Jan 25-30 with parallelization enabled
3. Verify correct fatigue scores in BigQuery
