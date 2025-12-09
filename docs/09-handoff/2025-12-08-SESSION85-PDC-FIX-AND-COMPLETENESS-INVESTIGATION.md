# Session 85 Handoff: PDC Fix and Completeness Check Investigation

**Date:** 2025-12-08
**Focus:** PDC NUMERIC precision fix, completeness checker performance investigation

---

## CRITICAL: Read These Docs First

```bash
# Comprehensive backfill guide
cat docs/02-operations/backfill/backfill-guide.md

# Previous session handoff (Phase 4 progress)
cat docs/09-handoff/2025-12-08-SESSION84-PHASE4-BACKFILL-PROGRESS.md

# Quick reference
cat docs/02-operations/backfill/quick-start.md
```

---

## Session Summary

### What Was Fixed

1. **PDC NUMERIC Precision Bug** (FIXED in previous session, verified this session)
   - **Root Cause:** `assisted_rate_last_10` calculation produced 17+ decimal places (e.g., `0.6666666666666666` from 2/3)
   - **Impact:** BigQuery NUMERIC type only supports 9 decimal places, causing batch insert failures
   - **Fix Applied:** `assisted_rate_last_10 = round(float(total_assisted / total_fg_makes), 9)`
   - **Files Modified:**
     - `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` (lines 321, 1943)
     - `data_processors/precompute/ml_feature_store/feature_calculator.py` (lines 267, 306)

2. **Fix Verified Working:**
   - Dec 1, 2021: Successfully loaded 123 rows with NO precision errors
   - Previously: 100% failure rate on December dates

### Current Backfill Status

| Table | Nov 2021 | Dec 2021 | Status |
|-------|----------|----------|--------|
| TDZA | Complete | Complete | Done |
| PSZA | Complete | Complete | Done |
| PCF | Complete | Complete | Done |
| PDC | 28 dates (4,883 records) | 1 date (123 records) | **Running but slow** |
| MLFS | Not started | Not started | Pending |

---

## PERFORMANCE ISSUE: Completeness Checker

### The Problem

The PDC backfill is extremely slow (~10+ minutes per date) due to the completeness checker's schedule lookup operations.

**Symptoms:**
- Dec 1: Completed in ~35 seconds
- Dec 2: Stuck for 10+ minutes on completeness checking

**Log evidence:**
```
INFO:shared.utils.completeness_checker:Checking completeness for 100 players (games window: 5)
INFO:shared.utils.completeness_checker:Checking completeness for 100 players (games window: 10)
INFO:shared.utils.completeness_checker:Checking completeness for 100 players (days window: 7)
INFO:shared.utils.completeness_checker:Checking completeness for 100 players (days window: 14)
INFO:shared.utils.completeness_checker:Player schedule check: 100 players with teams, avg expected: 6.6 games
INFO:shared.utils.completeness_checker:Player schedule check: 100 players with teams, avg expected: 5.0 games
<process hangs here>
```

### Root Cause Analysis

The completeness checker does **4 schedule lookups per player** for multi-window checking:
- L5 (last 5 games)
- L10 (last 10 games)
- L7d (last 7 days)
- L14d (last 14 days)

For 100 players × 4 windows = **400 schedule service calls**, which is causing massive delays.

### Investigation Tasks

**INVESTIGATE:** Can the completeness check be skipped entirely in backfill mode?

Look at:
```bash
# The completeness checker
cat shared/utils/completeness_checker.py

# How PDC uses it
grep -n "completeness" data_processors/precompute/player_daily_cache/player_daily_cache_processor.py | head -30

# The backfill mode flag handling
grep -n "backfill_mode" data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
```

**INVESTIGATE:** Can schedule lookups be batched?

Currently each player gets individual schedule lookups. Could batch all players' teams and query once.

**INVESTIGATE:** Can completeness metadata be skipped for backfills?

The completeness data (`l5_completeness_pct`, `l10_is_complete`, etc.) may not be needed for historical backfills since we're just populating data, not making real-time decisions.

---

## Running Processes

Check if the PDC backfill is still running:
```bash
# Check process
ps aux | grep player_daily_cache | grep -v grep

# Check log
tail -50 /tmp/pdc_dec2021_fix.log

# Check progress
grep -c "Successfully loaded" /tmp/pdc_dec2021_fix.log
```

If it's stuck or dead, kill and restart:
```bash
# Kill any stuck processes
pkill -f "player_daily_cache_precompute_backfill"

# Check current BigQuery state
bq query --use_legacy_sql=false '
SELECT cache_date, COUNT(*) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN "2021-12-01" AND "2021-12-31"
GROUP BY cache_date ORDER BY cache_date'
```

---

## TODO List for Next Session

### High Priority
1. [ ] **Investigate completeness checker performance**
   - Can it be skipped in backfill mode?
   - Can schedule lookups be batched?
   - Is the completeness metadata even needed for backfills?

2. [ ] **Complete PDC December 2021 backfill**
   - Either fix completeness checker or create a faster backfill script
   - Target: 30 dates with ~100-200 players each

3. [ ] **Run MLFS backfill for Nov-Dec 2021**
   - Depends on PDC completion
   - Command: `PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --start-date 2021-11-01 --end-date 2021-12-31`

### Medium Priority
4. [ ] **Validate all Phase 4 data coverage**
   - Run coverage query for all precompute tables
   - Ensure Nov-Dec 2021 is complete

5. [ ] **Document completeness checker improvement if made**
   - Update backfill guide with findings

---

## Key File Paths

### Backfill Documentation
```
docs/02-operations/backfill/
├── backfill-guide.md              # Comprehensive guide
├── backfill-mode-reference.md     # Backfill mode details
├── data-integrity-guide.md        # Data quality guidelines
├── gap-detection.md               # Gap detection tool docs
├── nov-dec-2021-backfill-plan.md  # Specific plan for Nov-Dec 2021
└── quick-start.md                 # Quick reference
```

### Processors to Investigate
```
# PDC processor (slow one)
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py

# Completeness checker (performance bottleneck)
shared/utils/completeness_checker.py

# MLFS (next to run)
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
data_processors/precompute/ml_feature_store/feature_calculator.py
```

### Backfill Scripts
```
backfill_jobs/precompute/
├── player_daily_cache/player_daily_cache_precompute_backfill.py
└── ml_feature_store/ml_feature_store_precompute_backfill.py
```

### Log Files (this session)
```
/tmp/pdc_dec2021_fix.log           # Current PDC backfill (Dec only)
/tmp/pdc_nov_dec_2021.log          # Earlier PDC attempt (full range)
```

---

## Quick Commands

### Check PDC Status
```bash
# BigQuery count
bq query --use_legacy_sql=false '
SELECT
  COUNT(DISTINCT cache_date) as dates,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN "2021-11-01" AND "2021-12-31"'

# Expected: ~58 dates, ~8000+ records when complete
```

### Fast PDC Backfill (if you fix completeness checker)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
    --start-date 2021-12-01 --end-date 2021-12-31 --no-resume 2>&1 | tee /tmp/pdc_dec2021_fast.log &
```

### Start MLFS After PDC Complete
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2021-11-01 --end-date 2021-12-31 2>&1 | tee /tmp/mlfs_nov_dec_2021.log &
```

---

## Context from This Session

### Why November Worked but December Failed (Original Bug)

The `assisted_rate_last_10` is calculated as `assisted_fg_makes / total_fg_makes`. Certain player stats in December produced repeating decimals:
- `0.6666666666666666` = 2/3 (12 occurrences in Dec)
- `0.6363636363636364` = 7/11 (12 occurrences in Dec)
- `0.7727272727272727` = 17/22

November happened to have denominators that produced "clean" or shorter decimals by random chance.

### Fix Applied
```python
# Before (broken)
assisted_rate_last_10 = float(total_assisted / total_fg_makes)

# After (fixed)
assisted_rate_last_10 = round(float(total_assisted / total_fg_makes), 9)
```

Same fix applied to MLFS `feature_calculator.py` for `pct_free_throw` and `team_win_pct`.

---

## Performance Optimization Ideas

If you need to create a faster backfill:

1. **Skip completeness checking entirely for backfills**
   - The completeness metadata is for production decisions, not historical data
   - Set all completeness fields to defaults/nulls

2. **Batch schedule lookups**
   - Get all team schedules once, cache in memory
   - Look up expected games from cache instead of individual queries

3. **Parallelize date processing**
   - Process multiple dates concurrently instead of sequentially
   - Be careful with BigQuery rate limits

4. **Skip circuit breaker checks for backfills**
   - These are for production retry logic, not needed for backfills

---

## Cascade Dependency Map

```
Phase 3 (COMPLETE)              Phase 4 (In Progress)         Phase 5
─────────────────              ───────────────────           ───────

player_game_summary ──────────→ PSZA ✅ ──────┐
                                    │         │
                                    │         ├──→ PCF ✅ ──→ PDC 🔄 ──→ MLFS ⏳
                                    │         │
team_defense_game_summary ────→ TDZA ✅ ──────┘
```

**Order matters!**
1. TDZA + PSZA (parallel) ✅ DONE
2. PCF (needs TDZA) ✅ DONE
3. PDC (needs PSZA + PCF) 🔄 IN PROGRESS (slow due to completeness checker)
4. MLFS (needs all above) ⏳ PENDING
