# Phase 4 Backfill Execution Issues

**Date**: 2026-01-17
**Status**: Blocked by processor bugs

## What We Tried

Executed Phase 4 backfill for 2021:
```bash
./bin/backfill/run_year_phase4.sh --year 2021 --skip-validation
```

## Results

### Successful Processor
✅ **player_shot_zone_analysis**: 11 dates successfully processed
- Successfully merged data into BigQuery
- Backfill mode working correctly
- Processing ~20-40 seconds per date

### Failed Processor
❌ **team_defense_zone_analysis**: 100% failure rate
- All dates failed with same error
- Processor bugs preventing backfill from completing

## Root Causes

### Issue #1: BigQuery Location Mismatch
**Error**: `Not found: Dataset urcwest:nba_raw was not found in location US`

**Location**: `shared/utils/completeness_checker.py:332`

**Problem**: The completeness checker is hardcoded to query BigQuery in location "US" but all datasets are in "us-west2"

**Impact**: Every call to `check_completeness_batch()` fails

### Issue #2: Completeness Check Running in Backfill Mode
**Location**: `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py:672`

**Problem**: Even though backfill mode is active (`🔄 BACKFILL MODE ACTIVE`), the processor still calls:
```python
completeness_results = self.completeness_checker.check_completeness_batch(...)
```

**Expected**: Backfill mode should skip completeness checks entirely

### Issue #3: DataFrame Ambiguity Error in Error Handling
**Error**: `ValueError: The truth value of a DataFrame is ambiguous`

**Location**: `data_processors/precompute/precompute_base.py:573`

**Code**:
```python
elif not self.raw_data:
```

**Problem**: Can't use `not` on a DataFrame - should be `self.raw_data.empty`

**Impact**: Error handling itself crashes, masking the real error

## Workarounds Attempted

### 1. --skip-validation flag
✅ Successfully bypassed Phase 3 validation
❌ Did not prevent completeness checks in processor

### 2. Parallel execution
✅ Both processors started in parallel
❌ Team defense consistently failed while player shot zone succeeded

## Impact Assessment

### What Works
- Player shot zone analysis: Can backfill successfully
- Player composite factors: Unknown (not reached due to dependencies)
- ML feature store: Unknown (not reached due to dependencies)

### What's Blocked
- Team defense zone analysis: 100% failure rate
- All subsequent processors that depend on team defense completion

### Data Gap Impact
With team_defense_zone_analysis failing:
- 102 dates remain without complete Phase 4 processing
- Player shot zone data can be partially backfilled
- Team defense zone data cannot be backfilled without code fixes

## Recommended Solutions

### Option A: Fix the Bugs (Best long-term)
**Effort**: 1-2 hours
**Steps**:
1. Fix BigQuery location in completeness_checker.py
2. Skip completeness check in backfill mode for team defense
3. Fix DataFrame ambiguity in error handling

**Pros**: Permanent fix, enables full backfill
**Cons**: Requires code changes and testing

### Option B: Run Only Working Processors (Quick workaround)
**Effort**: 10 minutes
**Steps**:
1. Run player_shot_zone_analysis directly for all years
2. Skip team_defense_zone_analysis
3. Run player_composite_factors (if it doesn't depend on team defense)
4. Run ml_feature_store

**Pros**: Partial progress immediately
**Cons**: Incomplete backfill, missing team defense data

### Option C: Use Direct BigQuery Inserts (Manual)
**Effort**: 2-3 hours
**Steps**:
1. Write custom SQL to compute team defense zone metrics
2. Insert directly into BigQuery table
3. Bypass the buggy processor entirely

**Pros**: Works around processor bugs
**Cons**: Custom solution, harder to maintain

## Immediate Next Steps

### Recommendation: Option B (Partial Backfill)
Run only the working processors to make progress on 102 gaps:

1. **Player Shot Zone** (works)
   ```bash
   ./bin/run_backfill.sh precompute/player_shot_zone_analysis --start-date 2021-01-01 --end-date 2025-12-31
   ```

2. **Player Composite Factors** (test if it works)
   ```bash
   ./bin/run_backfill.sh precompute/player_composite_factors --start-date 2021-11-01 --end-date 2021-11-01
   ```

3. **ML Feature Store** (test if it works)
   ```bash
   ./bin/run_backfill.sh precompute/ml_feature_store --start-date 2021-11-01 --end-date 2021-11-01
   ```

Then file issues for:
- [ ] Fix BigQuery location in completeness checker
- [ ] Fix backfill mode not skipping completeness check in team defense
- [ ] Fix DataFrame ambiguity in error handling

## Files to Fix

1. **shared/utils/completeness_checker.py**
   - Line 332: Add location parameter
   - Use us-west2 instead of default US

2. **data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py**
   - Line 672: Wrap completeness check in backfill mode conditional
   ```python
   if not self.backfill_mode:
       completeness_results = self.completeness_checker.check_completeness_batch(...)
   ```

3. **data_processors/precompute/precompute_base.py**
   - Line 573: Fix DataFrame check
   ```python
   elif self.raw_data.empty:
   ```

## Lessons Learned

1. **Test with dry-run first**: Should have tested on 1-2 dates before full year
2. **Processor dependencies on completeness checks**: Backfill mode doesn't fully disable all checks
3. **BigQuery location matters**: Hardcoded location assumptions break in multi-region setups
4. **Error handling needs testing too**: Bugs in error handlers mask real issues

## Current State

- Backfill task stopped after ~11 player shot zone successes
- 0 team defense zone successes
- 102 total gaps remain
- Infrastructure ready but blocked by processor bugs

## Decision Needed

Should we:
1. Fix the bugs first (delays backfill 1-2 hours)
2. Run partial backfill with working processors (starts immediately)
3. Wait for bug fixes in another session

**Recommendation**: Option 2 (partial backfill) to make progress, file bugs for later fix.
