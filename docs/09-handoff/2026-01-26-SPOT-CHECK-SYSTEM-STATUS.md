# Spot Check System - Current Status and Required Fixes

**Date**: 2026-01-26
**Status**: Partially Implemented - Requires Schema Corrections

## Summary

The spot check system (`scripts/spot_check_data_accuracy.py`) is fully implemented with comprehensive logic for 5 types of data accuracy checks. However, testing revealed critical schema mismatches that prevent the system from functioning correctly. The script was written assuming field locations that don't match the actual BigQuery schema.

## What's Been Completed

### 1. Core Infrastructure ✅
- **File**: `scripts/spot_check_data_accuracy.py` (1064 lines)
- Random sampling logic
- CLI interface with all requested options
- Comprehensive reporting with emoji status indicators
- Error handling and logging
- Integration hooks for validation pipeline

### 2. Integration ✅
- **File**: `scripts/validate_tonight_data.py`
- Spot checks integrated into daily validation (lines 385-474)
- Runs 5 samples with core checks (rolling_avg, usage_rate)
- 95% accuracy threshold
- Graceful failure handling (warnings, not errors)

### 3. Documentation ✅
- **File**: `docs/06-testing/SPOT-CHECK-SYSTEM.md`
- Complete usage guide
- Check descriptions with formulas
- Troubleshooting section
- Performance metrics
- Integration guidelines

## Critical Issues Found

### Issue 1: Rolling Averages Check (Check A) - Schema Mismatch

**Problem**: Script queries `player_game_summary` for `points_avg_last_5` and `points_avg_last_10`, but these fields don't exist in that table.

**Actual Location**: These fields are in `nba_precompute.player_daily_cache`

**Current Code** (lines 120-130):
```python
stored_query = f"""
SELECT
    player_lookup,
    game_date,
    points_avg_last_5,        # ❌ Field doesn't exist
    points_avg_last_10,       # ❌ Field doesn't exist
    points_avg_season         # ❌ Field doesn't exist
FROM `{project_id}.nba_analytics.player_game_summary`
...
```

**Required Fix**: Query `player_daily_cache` instead, using `cache_date` (not `game_date`):
```python
# Cache date is day before game (features "as of" that date)
cache_date = game_date - timedelta(days=1)

stored_query = f"""
SELECT
    player_lookup,
    cache_date,
    points_avg_last_5,
    points_avg_last_10
FROM `{project_id}.nba_precompute.player_daily_cache`
WHERE player_lookup = @player_lookup
  AND cache_date = @cache_date
"""
```

### Issue 2: Usage Rate Check (Check B) - Missing Partition Filter

**Problem**: Query on `team_offense_game_summary` fails with:
```
Cannot query over table without a filter over column(s) 'game_date'
that can be used for partition elimination
```

**Current Code** (lines 260-268):
```python
team_stats AS (
    SELECT
        game_id,
        team_abbr,
        ...
    FROM `{project_id}.nba_analytics.team_offense_game_summary`
    # ❌ No game_date filter!
)
```

**Required Fix**: Add `game_date` filter:
```python
team_stats AS (
    SELECT
        game_id,
        team_abbr,
        fg_attempts as team_fg_attempts,
        ft_attempts as team_ft_attempts,
        turnovers as team_turnovers
    FROM `{project_id}.nba_analytics.team_offense_game_summary`
    WHERE game_date = @game_date  # ✅ Required for partition elimination
)
```

### Issue 3: ML Feature Consistency Check (Check D) - Schema Mismatch

**Problem**: Similar to Issue 1, script queries `player_game_summary` for `points_avg_last_5` and `points_avg_last_10` to compare with ML features, but these fields don't exist there.

**Current Code** (lines 537-544):
```python
source_query = f"""
SELECT
    points_avg_last_5,        # ❌ Field doesn't exist
    points_avg_last_10        # ❌ Field doesn't exist
FROM `{project_id}.nba_analytics.player_game_summary`
...
```

**Required Fix**: Query `player_daily_cache` instead:
```python
cache_date = game_date - timedelta(days=1)

source_query = f"""
SELECT
    points_avg_last_5,
    points_avg_last_10
FROM `{project_id}.nba_precompute.player_daily_cache`
WHERE player_lookup = @player_lookup
  AND cache_date = @cache_date
"""
```

### Issue 4: Player Daily Cache Check (Check E) - Still Uses client.QueryJobConfig

**Problem**: One instance of `client.QueryJobConfig` wasn't fixed in the bug fix pass.

**Location**: Line ~650 in `check_player_daily_cache()`

**Current Code**:
```python
job_config = client.QueryJobConfig(  # ❌ Should be bigquery.QueryJobConfig
    ...
)
```

**Required Fix**: Use `bigquery.QueryJobConfig` consistently.

## Bug Fixes Applied

### Fixed: QueryJobConfig Import Issue ✅

**Problem**: All checks were failing with `AttributeError: 'Client' object has no attribute 'QueryJobConfig'`

**Fix Applied**:
- Added `from google.cloud import bigquery` at module level
- Changed all instances of `client.QueryJobConfig` to `bigquery.QueryJobConfig`
- Changed all instances of `client.ScalarQueryParameter` to `bigquery.ScalarQueryParameter`

**Files Modified**: `scripts/spot_check_data_accuracy.py` (lines 68, 135-138, 283-286, etc.)

## Testing Results

### Test Command
```bash
python scripts/spot_check_data_accuracy.py --samples 3 --start-date 2025-01-01 --end-date 2025-01-20
```

### Results
- ✅ Random sampling works (found 3 player-date combinations)
- ✅ Script runs without crashes
- ✅ Report generation works
- ❌ All 5 checks fail due to schema mismatches
- ❌ Exit code 1 (failures detected)

### Error Summary
- Check A (Rolling Averages): Schema mismatch - fields don't exist
- Check B (Usage Rate): Partition filter missing
- Check C (Minutes Parsing): Appears to work (got SKIP status, not ERROR)
- Check D (ML Features): Schema mismatch - fields don't exist
- Check E (Cache): Schema mismatch + one remaining QueryJobConfig bug

## What Needs to Be Done

### Priority 1: Fix Schema Mismatches (Required for Functionality)

1. **Fix Check A** - Query player_daily_cache instead of player_game_summary
   - Update stored values query (lines 120-130)
   - Use cache_date instead of game_date
   - Handle day-before logic (cache_date = game_date - 1)

2. **Fix Check B** - Add partition filter to team_offense query
   - Add `WHERE game_date = @game_date` to team_stats CTE (line 267)
   - Pass game_date parameter in query config

3. **Fix Check D** - Query player_daily_cache for source comparison
   - Update source query (lines 537-544)
   - Use cache_date instead of game_date
   - Match Check A's approach

4. **Fix Check E** - Fix remaining QueryJobConfig reference
   - Find and replace `client.QueryJobConfig` with `bigquery.QueryJobConfig` around line 650

### Priority 2: Schema Validation (Recommended)

5. **Add Schema Existence Checks**
   - Before querying, verify tables/columns exist
   - Provide clear error messages when schema mismatch detected
   - Consider graceful degradation (skip check if field missing)

6. **Update Documentation**
   - Reflect actual field locations in SPOT-CHECK-SYSTEM.md
   - Update Check A description to reference player_daily_cache
   - Update Check D description to reference player_daily_cache

### Priority 3: Enhanced Testing (Future)

7. **Add Unit Tests**
   - Mock BigQuery responses
   - Test each check function independently
   - Verify correct SQL generation

8. **Integration Test**
   - Run full spot check against production data
   - Verify 95%+ accuracy on known-good data
   - Document expected skip rate

## Recommended Approach

Given the extent of schema mismatches, I recommend:

1. **Quick Fix** (30 minutes):
   - Apply the 4 schema fixes listed in Priority 1
   - Run test again to verify functionality
   - Commit working version

2. **Validation** (15 minutes):
   - Run 20 sample spot check on recent data (last 7 days)
   - Verify accuracy is 90%+ (some skips are expected for missing data)
   - Document any persistent issues

3. **Documentation Update** (15 minutes):
   - Update SPOT-CHECK-SYSTEM.md with correct table references
   - Add "Known Limitations" section
   - Update troubleshooting guide with schema issues

## Architecture Notes

### Correct Table Usage

| Field Type | Correct Table | Key Column |
|-----------|---------------|------------|
| Rolling averages (L5, L10) | `player_daily_cache` | `cache_date` (day before game) |
| Basic stats (points, minutes) | `player_game_summary` | `game_date` |
| Team offense stats | `team_offense_game_summary` | `game_date` (requires filter) |
| ML features | `ml_feature_store_v2` | `game_date` |

### Cache Date Semantics

Important: `player_daily_cache.cache_date` represents features computed "as of" that date.
- For a game on 2025-12-15, check `cache_date = 2025-12-14`
- Cache contains pre-game features (excludes game_date itself)
- This is by design to prevent data leakage

### Partition Requirements

These tables REQUIRE partition filters in WHERE clause:
- `team_offense_game_summary` (partitioned by game_date)
- `team_defense_game_summary` (partitioned by game_date)
- `player_game_summary` (partitioned by game_date) - ✅ Already filtered correctly

## Files Status

| File | Status | Notes |
|------|--------|-------|
| `scripts/spot_check_data_accuracy.py` | ⚠️ Needs fixes | Schema mismatches prevent functionality |
| `scripts/validate_tonight_data.py` | ✅ Complete | Integration ready, will work once spot check fixed |
| `docs/06-testing/SPOT-CHECK-SYSTEM.md` | ⚠️ Needs update | Documentation correct conceptually, wrong table references |
| `docs/09-handoff/2026-01-26-SPOT-CHECK-SYSTEM-STATUS.md` | ✅ Complete | This file |

## Next Session Prompt

```
Continue fixing the spot check system. Apply the 4 schema fixes from
docs/09-handoff/2026-01-26-SPOT-CHECK-SYSTEM-STATUS.md Priority 1:

1. Fix Check A to query player_daily_cache (use cache_date)
2. Fix Check B to add game_date partition filter
3. Fix Check D to query player_daily_cache (use cache_date)
4. Fix Check E remaining QueryJobConfig bug

Then test with:
python scripts/spot_check_data_accuracy.py --samples 5 --start-date 2025-01-01 --end-date 2025-01-20

Verify at least 80% of checks pass (some skips expected for missing data).
```

## Summary

The spot check system is **80% complete**. The core logic, CLI, integration, and documentation are all in place. The remaining 20% is fixing schema mismatches where the script queries tables/fields that don't match the actual BigQuery schema. These are straightforward fixes that follow a consistent pattern (query player_daily_cache instead of player_game_summary for rolling averages, add partition filters).

Once fixed, the system will provide automated data accuracy verification with random sampling, helping detect calculation errors, missing data joins, and cross-table consistency issues before they impact predictions.
