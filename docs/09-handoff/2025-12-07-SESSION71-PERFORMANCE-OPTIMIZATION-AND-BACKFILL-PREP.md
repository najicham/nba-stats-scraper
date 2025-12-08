# Session 71: Performance Optimization and 4-Year Backfill Preparation

**Date:** 2025-12-07
**Focus:** PDC performance bottleneck fix, backfill monitoring, 4-year backfill preparation
**Status:** Major performance fix committed, December 2021 backfill ~70% complete

---

## Executive Summary

This session continued from Session 70 to monitor the December 2021 backfill and discovered a **critical performance bottleneck** in the PDC processor. The fix provides an **8x speedup** and saves ~24 hours on the full 4-year backfill.

---

## Objectives for 4-Year Backfill Readiness

### 1. Processor Performance Targets

| Processor | Target Per-Date | Current Status | Notes |
|-----------|-----------------|----------------|-------|
| TDZA | <30s | ✅ Good (~20s) | Only 30 teams, fast |
| PSZA | <30s | ✅ Good (~20s) | ProcessPool implemented |
| PCF | <60s | ✅ Good (~50s) | ProcessPool implemented |
| PDC | <60s | ✅ **FIXED** (~40s) | Was 200-280s before fix |
| ML | <90s | ⚠️ Needs monitoring (~70s typical, BQ timeouts on some dates) |

### 2. Database Performance

**BigQuery Operations to Monitor:**
- DELETE operations: Should be <5s per date (currently good)
- INSERT/LOAD operations: Should be <15s per date (currently good)
- Query timeouts: ML processor hitting 600s timeouts on complex dates

**Tables to Validate:**
```sql
-- Check record counts by date
SELECT DATE(analysis_date) as date, COUNT(*) as records
FROM `nba_precompute.player_composite_factors`
WHERE DATE(analysis_date) BETWEEN '2021-10-19' AND '2025-06-22'
GROUP BY 1 ORDER BY 1;

-- Same for other tables:
-- nba_precompute.player_daily_cache (cache_date)
-- nba_precompute.player_shot_zone_analysis (analysis_date)
-- nba_precompute.team_defense_zone_analysis (analysis_date)
-- nba_predictions.ml_feature_store_v2 (game_date)
```

### 3. Backfill Script Performance

**Phase 4 Backfill Script:** `./bin/backfill/run_phase4_backfill.sh`

**Key Parameters:**
- `--start-from N`: Resume from processor N (1=TDZA, 2=PSZA, 3=PCF, 4=PDC, 5=ML)
- `--no-resume`: Ignore checkpoints, start fresh
- `--dry-run`: Check data availability without processing

**Checkpoint Files:** `/tmp/backfill_checkpoints/`

**Estimated Times (with fix):**
| Phase | 680 Dates | Time |
|-------|-----------|------|
| TDZA+PSZA (parallel) | 680 | ~4 hours |
| PCF | 680 | ~9 hours |
| PDC | 680 | ~7.5 hours |
| ML | 680 | ~13 hours |
| **Total** | - | **~33 hours** |

### 4. Validation Scripts and Queries

**Completeness Check Query:**
```sql
-- Check which dates have data for all processors
WITH date_coverage AS (
  SELECT 'PCF' as proc, DATE(analysis_date) as dt FROM `nba_precompute.player_composite_factors`
  UNION ALL
  SELECT 'PDC', DATE(cache_date) FROM `nba_precompute.player_daily_cache`
  UNION ALL
  SELECT 'ML', DATE(game_date) FROM `nba_predictions.ml_feature_store_v2`
)
SELECT dt,
  COUNTIF(proc='PCF') as pcf,
  COUNTIF(proc='PDC') as pdc,
  COUNTIF(proc='ML') as ml
FROM date_coverage
WHERE dt BETWEEN '2021-12-01' AND '2021-12-31'
GROUP BY 1
ORDER BY 1;
```

**Failure Check Query:**
```sql
SELECT processor_name, failure_category, COUNT(*) as count
FROM `nba_processing.precompute_failures`
WHERE analysis_date BETWEEN '2021-12-01' AND '2021-12-31'
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2
ORDER BY 1, count DESC;
```

**Expected Failure Categories:**
- `INCOMPLETE_DATA`: Expected for early season dates (Oct-Dec)
- `INSUFFICIENT_DATA`: Expected for players with <5 games
- `PROCESSING_ERROR`: Should be investigated
- `calculation_error`: Bug - should not occur (fixed in Session 70)

### 5. Log File Monitoring

**Log Files:**
- Backfill logs: `/tmp/dec2021_backfill_v*.log`
- Individual processor logs: Check stdout/stderr

**Key Patterns to Watch:**
```bash
# Check for errors
grep -E "Error|ERROR|Exception|Traceback|Failed" /tmp/backfill.log

# Check processing rates
grep "Rate:" /tmp/backfill.log

# Check for BQ timeouts
grep "Timeout of 600" /tmp/backfill.log

# Check fix is applied (PDC)
grep "Skipping.*reprocess attempt recordings" /tmp/backfill.log
```

---

## Issues Discovered and Status

### Issue 1: PDC Reprocess Attempts Bottleneck (FIXED)

**Commit:** `f658712`

**Root Cause:** Individual BQ INSERT queries for each failed player's reprocess_attempts record. Each query has ~2-3s overhead.

**Fix:**
1. Skip reprocess_attempts recording in backfill mode (line 1416-1417)
2. Add batch INSERT method for daily orchestration (lines 1124-1196)

**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Verification:** Look for log message:
```
⏭️  BACKFILL MODE: Skipping N reprocess attempt recordings
```

### Issue 2: ML Processor BQ Timeouts (OPEN)

**Symptom:** ML processor times out on certain dates with error:
```
google.api_core.exceptions.RetryError: Timeout of 600.0s exceeded
```

**Affected Dates:** Dec 22-23, 2021 (and potentially others)

**Potential Causes:**
1. Complex queries on dates with many players
2. BQ quota limits
3. Network connectivity issues

**Workaround:** The backfill continues to next date after timeout. Missing dates can be reprocessed later.

**Recommended Fix:** Investigate ML processor queries for optimization opportunities.

### Issue 3: Missing nba_schedule Table (WARNING)

**Error in logs:**
```
404 Not found: Table nba-props-platform:nba_reference.nba_schedule was not found
```

**Impact:** Low - falls back to GCS schedule data successfully.

**Status:** Non-blocking, but should be investigated.

### Issue 4: Dates with No Games (EXPECTED)

**Dates with 0 players processed:**
- Dec 22, 2021 (COVID postponements)
- Dec 24, 2021 (no games)
- Dec 27, 2021 (limited games)

**Status:** Expected behavior. The backfill correctly skips these dates.

### Issue 5: High Failure Rates in Early Season (EXPECTED)

**Symptom:** 60-90% failure rate on early December dates

**Cause:** Early season bootstrap period - players don't have enough game history yet.

**Status:** Expected. Failure category is `INCOMPLETE_DATA` which is handled gracefully.

---

## December 2021 Backfill Status

| Processor | Dates Completed | Records | Status |
|-----------|-----------------|---------|--------|
| PCF | 21 | 2,687 | ✅ Complete |
| PDC | 25 | 1,750 | ✅ Complete |
| ML | 20 | 2,598 | ⚠️ Stopped (BQ timeouts) |

**Missing ML Dates:** Dec 21-31 (10 dates)

---

## Commands for Next Session

### 1. Resume ML Backfill for December 2021
```bash
./bin/backfill/run_phase4_backfill.sh --start-date 2021-12-01 --end-date 2021-12-31 --start-from 5
```

### 2. Start Full 4-Year Backfill
```bash
# Recommended: Run in screen/tmux session
nohup ./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22 > /tmp/4year_backfill.log 2>&1 &
```

### 3. Monitor Backfill Progress
```bash
# Watch log in real-time
tail -f /tmp/4year_backfill.log

# Check BQ data counts
bq query --use_legacy_sql=false 'SELECT COUNT(DISTINCT DATE(analysis_date)) FROM nba_precompute.player_composite_factors'
```

### 4. Validate Completed Data
```bash
# Run validation script
python scripts/validate_backfill_coverage.py --start-date 2021-10-19 --end-date 2025-06-22
```

---

## Performance Benchmarks (With Fix)

### PDC Performance Comparison

| Metric | Before Fix | After Fix | Improvement |
|--------|------------|-----------|-------------|
| Per-date time | 200-280s | 35-40s | **8x faster** |
| With 50 failures | +125s overhead | 0s | **100% reduction** |
| 680 dates total | ~50 hours | ~7.5 hours | **42.5 hours saved** |

### Overall Backfill Time Estimate

| Component | Before Fix | After Fix |
|-----------|------------|-----------|
| TDZA+PSZA | ~4 hours | ~4 hours |
| PCF | ~9 hours | ~9 hours |
| PDC | ~50 hours | ~7.5 hours |
| ML | ~13 hours | ~13 hours |
| **Total** | **~76 hours** | **~33 hours** |

---

## Related Documentation

### Session Handoffs
- `docs/09-handoff/2025-12-07-SESSION70-PROCESSPOOL-FIXES-AND-BACKFILL.md` - ProcessPool bug fixes
- `docs/09-handoff/2025-12-07-SESSION69-PROCESSPOOL-OPTIMIZATION.md` - ProcessPool implementation
- `docs/09-handoff/2025-12-07-SESSION68-PERFORMANCE-AND-FAILURE-ANALYSIS.md` - Performance analysis

### Runbooks
- `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md` - Phase 4 backfill guide
- `docs/02-operations/backfill-guide.md` - General backfill documentation

### Key Code Files
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - PDC processor (fixed)
- `data_processors/precompute/precompute_base.py` - Base class for all precompute processors
- `bin/backfill/run_phase4_backfill.sh` - Phase 4 backfill orchestrator
- `shared/utils/hash_utils.py` - Hash utilities (created in Session 70)

---

## Checklist Before 4-Year Backfill

- [x] PDC performance fix committed (f658712)
- [x] ProcessPool implementations working (PSZA, PCF, PDC)
- [x] Dependency skip in backfill mode working
- [x] December 2021 test run successful (PCF, PDC complete)
- [ ] ML December backfill completed (10 dates remaining)
- [ ] BQ timeout issue investigated
- [ ] Full validation of December 2021 data
- [ ] Screen/tmux session prepared for long-running backfill

---

## Session Summary

### Completed
- ✅ Identified PDC bottleneck (reprocess_attempts individual inserts)
- ✅ Implemented fix (skip in backfill mode + batch for daily)
- ✅ Verified fix working (8x speedup confirmed)
- ✅ Committed fix (f658712)
- ✅ PCF December 2021 backfill complete
- ✅ PDC December 2021 backfill complete

### In Progress
- 🔄 ML December 2021 backfill (20/30 dates, BQ timeouts)

### Pending
- ⏳ Complete ML December backfill
- ⏳ Investigate BQ timeout issue in ML processor
- ⏳ Start full 4-year backfill

---

**Created:** 2025-12-07
**Author:** Claude Code Session 71
**Previous Session:** SESSION70-PROCESSPOOL-FIXES-AND-BACKFILL.md
