# Phase 3 Schema Mismatch Bug - Session 115

**Date:** February 4, 2026
**Severity:** HIGH
**Status:** FIXED ✅

## Summary

Discovered schema mismatch bug in Phase 3 analytics (`upcoming_player_game_context`) when attempting to regenerate data after DNP fix deployment. The processor was using outdated column names that don't match the current `player_game_summary` schema.

## Bug Details

**Error:**
```
400 Name rebounds not found inside pgs at [9:17]
400 Name field_goals_made not found inside pgs at [10:17]
```

**Root Cause:**
The query in `game_data_loaders.py` was using old column names that don't exist in the current schema.

**Column Name Mismatches:**

| Code Used (OLD) | Schema Has (ACTUAL) |
|-----------------|---------------------|
| `rebounds` | `offensive_rebounds` + `defensive_rebounds` |
| `field_goals_made` | `fg_makes` |
| `field_goals_attempted` | `fg_attempts` |
| `three_pointers_made` | `three_pt_makes` |
| `three_pointers_attempted` | `three_pt_attempts` |
| `free_throws_made` | `ft_makes` |
| `free_throws_attempted` | `ft_attempts` |

## Fix Applied

**File:** `data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py`
**Lines:** 205-224

**Changes:**
```sql
-- BEFORE (broken):
pgs.rebounds,
pgs.field_goals_made,
pgs.field_goals_attempted,
pgs.three_pointers_made,
pgs.three_pointers_attempted,
pgs.free_throws_made,
pgs.free_throws_attempted,

-- AFTER (fixed):
(pgs.offensive_rebounds + pgs.defensive_rebounds) as rebounds,
pgs.fg_makes as field_goals_made,
pgs.fg_attempts as field_goals_attempted,
pgs.three_pt_makes as three_pointers_made,
pgs.three_pt_attempts as three_pointers_attempted,
pgs.ft_makes as free_throws_made,
pgs.ft_attempts as free_throws_attempted,
```

## Impact

**Before Fix:**
- Phase 3 regeneration completely broken ❌
- Could not process any dates
- ERROR on every run

**After Fix:**
- Phase 3 regeneration working ✅
- Can regenerate historical dates
- Consistent with schema

## Why This Wasn't Caught Earlier

**Likely Scenario:**
1. Schema was updated at some point (column names changed)
2. Phase 3 processor wasn't updated to match
3. Phase 3 only runs event-driven (when games happen)
4. No one tried to manually regenerate historical dates
5. Bug dormant until Session 115 attempted regeneration

**No Validation:**
- No schema validation in pre-commit hooks
- No integration tests for Phase 3 regeneration
- Manual regeneration rarely needed

## Prevention for Future

### 1. Add Schema Validation Pre-Commit Hook

Create validation to catch schema mismatches:

```python
# .pre-commit-hooks/validate_bigquery_queries.py
# Check all BigQuery queries use valid column names
```

### 2. Add Integration Test

```python
# tests/integration/test_phase3_regeneration.py
def test_phase3_can_regenerate_historical_date():
    """Verify Phase 3 processor can regenerate old dates"""
    processor = UpcomingPlayerGameContextProcessor()
    result = processor.process_date(date(2026, 1, 15))
    assert result['status'] == 'success'
```

### 3. Document Schema Change Process

When changing `player_game_summary` schema:
1. Update all processors that query the table
2. Update Phase 3 analytics queries
3. Update Phase 4 precompute queries
4. Run schema validation
5. Test regeneration on historical date

## Files Affected

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py` | Fixed column names (lines 205-220) |

## Related Issues

- Session 115: Phase 3 stale data after DNP fix deployment
- Could not regenerate Phase 3 without this fix
- Blocked from bringing Phase 3 in sync with Phase 4

## Testing

**Verification:**
```bash
# Test regeneration for Feb 1
python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor 2026-02-01 --skip-downstream-trigger

# Expected: Success (not ERROR 400)
```

**Status:** ✅ VERIFIED - Processor now runs successfully

## Commits

| Commit | Description |
|--------|-------------|
| TBD | fix: Update Phase 3 column names to match player_game_summary schema |

---

**Lesson Learned:** Schema changes need coordinated updates across all consumers. Add validation to prevent schema drift.
