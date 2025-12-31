# Session 70: ProcessPool Bug Fixes and December 2021 Backfill

**Date:** 2025-12-07
**Focus:** Fix critical ProcessPool bugs, run December 2021 backfill
**Status:** Backfill running in background, bugs fixed and committed

---

## Executive Summary

This session continued from Session 69 to fix critical bugs in the ProcessPool implementation and run a December 2021 backfill. Two bugs were discovered and fixed:

1. **PSZA hash bug** (fixed in Session 69, commit `7d63f07`)
2. **PCF missing module bug** (fixed this session, commit `93008a1`)

The December 2021 backfill is now running successfully in the background.

---

## Bugs Fixed

### Bug 1: PSZA Hash Computation (Session 69)

**Commit:** `7d63f07`

**Root Cause:** ProcessPool worker called non-existent `SmartIdempotencyMixin._compute_hash_static`

**Fix:** Added module-level `_compute_hash_static()` function at line 69-96 in:
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Verification:** Tested on Jan 15, 2022 - 398 records, 0 PROCESSING_ERROR

---

### Bug 2: PCF Missing hash_utils Module (This Session)

**Commit:** `93008a1`

**Root Cause:** PCF ProcessPool worker at line 113 imported:
```python
from shared.utils.hash_utils import compute_hash_from_dict
```
But this module didn't exist, causing 100% failure rate (665 calculation_errors).

**Fix:** Created `shared/utils/hash_utils.py` with:
- `compute_hash_from_dict(data, fields)` - for PCF processor
- `compute_hash_static(record, hash_fields)` - alias for other processors

**Verification:** Tested on Dec 15, 2021 - 207 players, 0 failures, 613 players/sec

---

## Current State

### December 2021 Backfill

**Status:** RUNNING in background (PID 1607135)
**Log file:** `/tmp/dec2021_backfill_v2.log`
**Monitor:** `tail -f /tmp/dec2021_backfill_v2.log`

**Progress:**
- PCF: Processing dates 11-30 (resumed from checkpoint after bug fix)
- PDC: Pending (starts after PCF completes)
- ML: Pending (starts after PDC completes)

**Command used:**
```bash
nohup ./bin/backfill/run_phase4_backfill.sh --start-date 2021-12-01 --end-date 2021-12-31 --start-from 3 > /tmp/dec2021_backfill_v2.log 2>&1 &
```

**Expected completion:** ~80-100 minutes from session start

---

### Git Status

**Recent commits:**
```
93008a1 fix: Add missing hash_utils.py for PCF ProcessPool workers
7d63f07 perf: Implement ProcessPoolExecutor for 4-5x parallelization speedup
ceab163 docs: Add Session 67 handoff - backfill docs and optimization
1d1720b docs: Add Phase 4 precompute backfill runbook
1e0284b perf: Skip dependency check in backfill mode for 100x speedup
```

**Clean working directory** (no uncommitted changes to processors)

---

## ProcessPool Implementation Status

| Processor | ProcessPool | Hash Fix | Tested | Status |
|-----------|-------------|----------|--------|--------|
| PSZA | ✅ | ✅ `_compute_hash_static()` | ✅ Jan 15 | Working |
| PCF | ✅ | ✅ `shared/utils/hash_utils.py` | ✅ Dec 15 | Working |
| PDC | ✅ | ✅ Uses inline `hashlib.sha256()` | ⏳ | Should work |
| TDZA | ⏭️ Skip | N/A | N/A | Only 30 teams |
| ML | ❌ | N/A | N/A | Has BQ in workers |

---

## Performance Benchmarks

| Processor | Workers | Rate | Per-Date Time |
|-----------|---------|------|---------------|
| PSZA | 32 | 466 players/sec | ~20 sec |
| PCF | 32 | 613 players/sec | ~40 sec |
| PDC | 32 | ~350 players/sec | ~65 sec |

**Speedup vs ThreadPool:** 4-5x on multi-core systems

---

## Database Error Records

When this session started, there were 665 `calculation_error` failures from PCF due to the missing module bug. These records are in the BQ streaming buffer and cannot be deleted yet (will age out).

**Current failures after fix:**
```sql
SELECT processor_name, failure_category, COUNT(*) as count
FROM `nba_processing.precompute_failures`
WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY 1, 2;
```

---

## Key Files

### ProcessPool Implementations
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
  - Lines 67-96: `_compute_hash_static()` function
  - Lines 300-420: `_process_single_player_worker()` function

- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
  - Line 113: Uses `shared.utils.hash_utils.compute_hash_from_dict`
  - Lines 70-413: `_process_single_player_worker()` function

- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
  - Line 447: Uses inline `hashlib.sha256()` (no external dependency)

### Hash Utility Module
- `shared/utils/hash_utils.py` (NEW - created this session)
  - `compute_hash_from_dict()` - primary function
  - `compute_hash_static()` - alias

### Backfill Scripts
- `bin/backfill/run_phase4_backfill.sh` - Main orchestrator
- `backfill_jobs/precompute/*/` - Individual processor backfill jobs

### Documentation
- `docs/02-operations/backfill-guide.md` - Comprehensive backfill guide
- `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md` - Phase 4 specific

---

## Next Steps

### Immediate (After Backfill Completes)

1. **Validate December 2021 data:**
   ```sql
   SELECT
     'PCF' as processor, COUNT(DISTINCT DATE(analysis_date)) as dates, COUNT(*) as records
   FROM `nba_precompute.player_composite_factors`
   WHERE DATE(analysis_date) BETWEEN '2021-12-01' AND '2021-12-31'
   UNION ALL
   SELECT 'PDC', COUNT(DISTINCT DATE(cache_date)), COUNT(*)
   FROM `nba_precompute.player_daily_cache`
   WHERE DATE(cache_date) BETWEEN '2021-12-01' AND '2021-12-31'
   UNION ALL
   SELECT 'ML', COUNT(DISTINCT DATE(game_date)), COUNT(*)
   FROM `nba_predictions.ml_feature_store_v2`
   WHERE DATE(game_date) BETWEEN '2021-12-01' AND '2021-12-31';
   ```

2. **Check for errors:**
   ```sql
   SELECT failure_category, COUNT(*)
   FROM `nba_processing.precompute_failures`
   WHERE analysis_date BETWEEN '2021-12-01' AND '2021-12-31'
     AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
   GROUP BY 1;
   ```
   - Should see mostly `EXPECTED_INCOMPLETE` (early season bootstrap)
   - Should NOT see `calculation_error` or `PROCESSING_ERROR`

### 4-Season Backfill Plan

After December 2021 validates successfully:

| Season | Dates | Estimated Time |
|--------|-------|----------------|
| 2021-22 | Oct 19, 2021 - Jun 30, 2022 | ~10 hours |
| 2022-23 | Oct 18, 2022 - Jun 30, 2023 | ~10 hours |
| 2023-24 | Oct 24, 2023 - Jun 30, 2024 | ~10 hours |
| 2024-25 | Oct 22, 2024 - Jun 22, 2025 | ~10 hours |
| **Total** | ~680 game dates | **~40 hours** |

**Command for full backfill:**
```bash
./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22
```

---

## Troubleshooting

### If backfill fails

1. Check log: `tail -100 /tmp/dec2021_backfill_v2.log`
2. Look for error patterns:
   - `No module named` → Missing import, check hash_utils.py
   - `calculation_error` → Check worker function
   - `PROCESSING_ERROR` → Check BQ permissions/schema

3. Resume from checkpoint:
   ```bash
   ./bin/backfill/run_phase4_backfill.sh --start-date 2021-12-01 --end-date 2021-12-31 --start-from 3
   ```
   (Checkpoint will auto-resume from last completed date)

### If PDC has same hash bug

Check line 447 in `player_daily_cache_processor.py`:
- Currently uses `hashlib.sha256(hash_str.encode()).hexdigest()`
- This is inline, should work without external module

---

## Session Summary

### Completed
- ✅ Verified PSZA ProcessPool fix (398 records, 0 errors)
- ✅ Fixed PCF missing hash_utils module (commit `93008a1`)
- ✅ Verified PCF fix (207 players, 0 errors, 613 players/sec)
- ✅ Restarted December 2021 backfill with fixes
- ✅ Killed stale background tasks from previous sessions

### In Progress
- 🔄 December 2021 backfill (PCF → PDC → ML)

### Pending
- ⏳ Validate December 2021 data
- ⏳ Plan and execute 4-season backfill

---

## Quick Reference

**Monitor backfill:**
```bash
tail -f /tmp/dec2021_backfill_v2.log
```

**Check if process running:**
```bash
ps aux | grep run_phase4_backfill
```

**Check BQ for recent data:**
```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE DATE(analysis_date) = "2021-12-15"'
```

---

**Created:** 2025-12-07
**Author:** Claude Code Session 70
**Previous Session:** SESSION69-PROCESSPOOL-OPTIMIZATION.md
