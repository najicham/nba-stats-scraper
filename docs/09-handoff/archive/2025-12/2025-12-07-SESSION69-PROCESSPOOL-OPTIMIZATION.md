# Session 69: ProcessPool Optimization for 4-Season Backfill

**Date:** 2025-12-07
**Focus:** Fix ProcessPool bug for PSZA, enable 4-5x speedup for 4-season backfill
**Status:** PSZA fix applied, testing in progress

---

## Executive Summary

This session continued from Session 68 to implement ProcessPool optimization for Phase 4 processors. The goal is to enable a 4-season backfill (2021-2025, ~680 game dates) which would take ~170 hours with current ThreadPool vs ~40 hours with ProcessPool (4x speedup).

**Key Finding:** A critical bug was discovered and fixed in the PSZA ProcessPool implementation - the worker function called a non-existent method `SmartIdempotencyMixin._compute_hash_static`.

---

## Bug Fixed: ProcessPool Hash Computation

### Root Cause
The ProcessPool worker function (`_process_single_player_worker`) at line 310-311 had:
```python
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
record['data_hash'] = SmartIdempotencyMixin._compute_hash_static(record, hash_fields)
```

But `_compute_hash_static` doesn't exist - the actual method is `compute_data_hash` (instance method, not static).

### Error Manifested As
- 398 PROCESSING_ERROR failures on a mid-season date test
- Error message: `"type object 'SmartIdempotencyMixin' has no attribute '_compute_hash_static'"`

### Fix Applied
**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

1. **Added** static hash function at module level (lines 67-96):
```python
import hashlib

def _compute_hash_static(record: dict, hash_fields: list) -> str:
    """
    Compute SHA256 hash (16 chars) from meaningful fields only.
    Static version for ProcessPool workers.
    """
    hash_values = []
    for field in hash_fields:
        value = record.get(field)
        # Normalize value to string representation
        if value is None:
            normalized = "NULL"
        elif isinstance(value, (int, float)):
            normalized = str(value)
        elif isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value)
        hash_values.append(f"{field}:{normalized}")

    # Create canonical string (sorted for consistency)
    canonical_string = "|".join(sorted(hash_values))

    # Compute SHA256 hash
    hash_bytes = canonical_string.encode('utf-8')
    sha256_hash = hashlib.sha256(hash_bytes).hexdigest()

    # Return first 16 characters
    return sha256_hash[:16]
```

2. **Updated** worker function (line 341-342):
```python
# Compute hash (use module-level static function for ProcessPool compatibility)
record['data_hash'] = _compute_hash_static(record, hash_fields)
```

---

## Current State

### Files Modified (Uncommitted)
```
M data_processors/precompute/player_composite_factors/player_composite_factors_processor.py (+484 lines - ProcessPool added)
M data_processors/precompute/player_daily_cache/player_daily_cache_processor.py (+603 lines - ProcessPool added)
M data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py (+446 lines - ProcessPool + hash fix)
M scripts/validate_backfill_coverage.py (+30 lines - failure category display)
```

### Test Running
A test is currently running (background shell 3e081a):
```bash
time .venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({
    'analysis_date': date(2022, 1, 15),
    'backfill_mode': True,
    'skip_downstream_trigger': True
})
print('RESULTS:')
print(f'Records created: {p.stats.get(\"records_created\", 0)}')
print(f'Errors to investigate: {p.stats.get(\"errors_to_investigate\", 0)}')
"
```

**Expected Results if Fix Works:**
- Records created: ~400 (mid-season has most players with 10+ games)
- EXPECTED_INCOMPLETE: ~150-200 (players with <10 actual games)
- PROCESSING_ERROR: 0 (the bug is fixed)

---

## Outstanding Tasks

### Immediate (This Session)
1. **Verify PSZA fix** - Check test results (shell 3e081a)
2. **Check PDC/PCF for same bug** - They may have the same hash computation issue
3. **Apply fix to PDC/PCF if needed**

### After Fix Verification
4. **Benchmark ProcessPool performance**
   - Current ThreadPool: ~3 min/date
   - Expected ProcessPool: ~45-60 sec/date (4-5x speedup)

5. **Run December 2021 backfill** (if ready)
   - PCF/PDC/ML need backfill (PSZA/TDZA done)
   - Command: `./bin/backfill/run_phase4_backfill.sh --start 2021-12-01 --end 2021-12-31 --start-from 3`

### 4-Season Backfill Plan
| Season  | Dates | Estimated Time (ProcessPool) |
|---------|-------|------------------------------|
| 2021-22 | Oct 19, 2021 - Jun 30, 2022 | ~10 hours |
| 2022-23 | Oct 18, 2022 - Jun 30, 2023 | ~10 hours |
| 2023-24 | Oct 24, 2023 - Jun 30, 2024 | ~10 hours |
| 2024-25 | Oct 22, 2024 - Jun 22, 2025 | ~10 hours |
| **Total** | ~680 game dates | **~40 hours** |

---

## ProcessPool Implementation Details

### Which Processors Can Use ProcessPool
| Processor | Safe for ProcessPool | Notes |
|-----------|----------------------|-------|
| PSZA | ✅ Yes | Fixed hash bug, workers don't need BQ |
| PDC | ✅ Yes | Uses batch circuit breaker query |
| PCF | ✅ Yes | In-memory calculations |
| TDZA | ⚠️ Skip | Only 30 teams, minimal benefit |
| ML | ❌ No | Has BQ queries inside workers |

### Key ProcessPool Requirements
1. **Worker functions must be module-level** (not instance methods)
2. **No BQ client in workers** (not picklable)
3. **Pre-fetch all BQ data** before entering ProcessPool
4. **No class instance references** in worker arguments

### Circuit Breaker Optimization
In backfill mode, circuit breaker checks are now skipped:
```python
# Skip circuit breaker checks in backfill mode (historical data doesn't need this)
if self.is_backfill_mode or is_bootstrap or is_season_boundary:
    logger.info(f"⏭️  Skipping circuit breaker checks (backfill/bootstrap mode)")
    for player_lookup in all_players:
        circuit_breaker_statuses[player_lookup] = {
            'active': False, 'attempts': 0, 'until': None
        }
```

---

## Previous Session Context (Session 68)

### Failure Classification (Already Implemented)
- `EXPECTED_INCOMPLETE`: Player has <10 actual games (season bootstrap)
- `INCOMPLETE_UPSTREAM`: Player has 10+ actual games but we're missing data

### Performance Optimizations (Already Implemented)
- 100x dependency skip in backfill mode
- Completeness check skip in backfill mode
- Batch extraction for all processors

---

## Verification Commands

### Test PSZA with ProcessPool
```bash
time .venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({
    'analysis_date': date(2022, 1, 15),
    'backfill_mode': True,
    'skip_downstream_trigger': True
})
print(f'Records: {p.stats.get(\"records_created\", 0)}')
print(f'Errors: {p.stats.get(\"errors_to_investigate\", 0)}')
"
```

### Check Recent Failures in BQ
```sql
SELECT
  failure_category,
  COUNT(*) as count
FROM `nba_processing.precompute_failures`
WHERE processor_name = "PlayerShotZoneAnalysisProcessor"
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY 1;
```

### Check for Hash Bug in PDC/PCF
```bash
grep -n "SmartIdempotencyMixin._compute_hash_static" data_processors/precompute/*/
grep -n "_compute_hash_static" data_processors/precompute/*/
```

---

## Files to Review

### PSZA Processor (Hash Fix Applied)
`data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- Lines 67-96: New `_compute_hash_static` function
- Line 341-342: Updated to use static function
- Lines 946-1100: ProcessPool implementation

### PDC Processor (Check for Same Bug)
`data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Check if ProcessPool worker has the same hash computation issue

### PCF Processor (Check for Same Bug)
`data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
- Check if ProcessPool worker has the same hash computation issue

---

## Key Decisions Made

1. **ProcessPool is worth it** for 4-season backfill (saves ~130 hours)
2. **Skip TDZA ProcessPool** - only 30 teams, minimal benefit
3. **Skip ML ProcessPool** - has BQ queries inside workers (blocked)
4. **Failure classification working** - EXPECTED_INCOMPLETE vs INCOMPLETE_UPSTREAM

---

## Background Tasks (May Be Stale)

These background tasks were running from previous sessions:
- `3e081a`: PSZA test with fix (current)
- `3368b5`: Pipeline validation
- `74a82c`: ML Feature Store query
- `6ada78`: PSZA backfill Nov 1-4
- Many others - check with `/tasks` command

**Recommendation:** Kill stale tasks and run fresh tests.

---

## Summary for Next Session

1. **Check test results** from shell 3e081a
2. **If PSZA works**: Check PDC/PCF for same hash bug
3. **If bugs found**: Apply same `_compute_hash_static` fix
4. **Benchmark**: Compare ProcessPool vs ThreadPool timing
5. **Backfill**: Start with December 2021, then full 4-season

**Key file to read first:**
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` (lines 67-96 for the fix)
