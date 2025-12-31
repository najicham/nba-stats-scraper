# Session 67: Backfill Documentation & Optimization

**Date:** 2025-12-07
**Focus:** Phase 4 backfill documentation, performance optimization, failure analysis
**Status:** Complete

---

## Objective

Create a **streamlined, documented backfill process** with:
1. Clear understanding of expected failures vs bugs
2. Performance optimizations for backfill mode
3. Documentation that future sessions can reference
4. Small sample testing approach for validation

---

## Key Accomplishments

### 1. Performance Optimization: 100x Speedup

**Commit:** `1e0284b perf: Skip dependency check in backfill mode`

**Problem:** Dependency checks were taking 54-103 seconds per date in backfill mode
**Solution:** Skip dependency freshness checks when `backfill_mode=True` (historical data won't change)
**Result:** Dependency check time reduced from 103s → ~0s

**File Changed:** `data_processors/precompute/precompute_base.py` (line 205-219)

### 2. Failure Analysis: Expected vs Bugs

**Key Finding:** Most failures are EXPECTED, not bugs.

| Season Week | Expected PSZA Failure Rate | Reason |
|-------------|---------------------------|--------|
| 1-2 | 90-100% | Bootstrap period |
| 3 | 60-75% | Most players < 10 games |
| 4 | 40-50% | ~Half qualify |
| 5+ | 25-30% | Baseline (bench/injured) |

**Failure Categories:**
- `INSUFFICIENT_DATA` → **Expected** (business logic requirement)
- `MISSING_DEPENDENCY` → **Expected** (cascade from upstream)
- `PROCESSING_ERROR` → **Investigate** (actual bug)

### 3. Documentation Created

**New File:** `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md`

Contains:
- Processor ordering diagram (TDZA+PSZA parallel → PCF → PDC → ML)
- Expected failure rates by season week
- Backfill mode optimizations
- Failure triage guide
- Validation queries

**Updated Files:**
- `docs/02-operations/runbooks/backfill/README.md` - Added Phase 4 section
- `docs/02-operations/README.md` - Added reference to Phase 4 guide

---

## Testing Philosophy: Small Samples First

### Why Small Samples?

Running full-season backfills takes hours and makes debugging difficult. Instead:

1. **Test single dates first** - Verify processor works
2. **Test small ranges (3-5 dates)** - Verify batching works
3. **Monitor failure rates** - Compare to expected rates
4. **Only then run full backfill** - With confidence

### Example Testing Workflow

```bash
# Step 1: Single date test
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'Stats: {p.stats}')
"

# Step 2: Small range test (4 dates)
.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-11-01 --end-date 2021-11-04 --skip-preflight

# Step 3: Validate results
bq query 'SELECT DATE(analysis_date), COUNT(*) FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) BETWEEN "2021-11-01" AND "2021-11-04" GROUP BY 1'

# Step 4: Check failure rates (compare to expected)
bq query 'SELECT failure_category, COUNT(*) FROM nba_processing.precompute_failures WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-04" GROUP BY 1'

# Step 5: Only if all looks good, run full month
./bin/backfill/run_phase4_backfill.sh --start 2021-11-01 --end 2021-11-30
```

### What to Validate

| Check | Query | Expected |
|-------|-------|----------|
| Records created | `SELECT COUNT(*) FROM table WHERE date = X` | > 0 |
| Failure rate (early) | Compare to expected rates table | ~90% week 1-2 |
| Failure rate (mid) | Compare to expected rates table | ~30% week 5+ |
| Processing time | Check logs | < 2 min/date with optimization |
| No PROCESSING_ERROR | Check failure table | 0 count |

---

## Commits This Session

```
1d1720b docs: Add Phase 4 precompute backfill runbook
1e0284b perf: Skip dependency check in backfill mode for 100x speedup
86b2074 fix: Add missing completeness dict fields for backfill mode (from Session 66)
```

---

## Key Files Reference

### Documentation
| File | Purpose |
|------|---------|
| `docs/02-operations/runbooks/backfill/phase4-precompute-backfill.md` | **PRIMARY** - Phase 4 backfill guide |
| `docs/02-operations/backfill-guide.md` | General backfill guide (all phases) |
| `docs/02-operations/runbooks/backfill/README.md` | Index of backfill runbooks |

### Code
| File | Purpose |
|------|---------|
| `data_processors/precompute/precompute_base.py` | Base class with dependency skip optimization |
| `backfill_jobs/precompute/*/` | Individual processor backfill scripts |
| `bin/backfill/run_phase4_backfill.sh` | Shell script for full Phase 4 backfill |

### Validation
| Query | Purpose |
|-------|---------|
| `nba_processing.precompute_failures` | Track failures by category |
| `nba_reference.processor_run_history` | Track run success/failure |
| `nba_precompute.*` | Check actual data created |

---

## Next Steps (For Future Sessions)

### Immediate
1. **Test December 2021** - Run small sample to verify November patterns hold
2. **Full season backfill** - Once confident, run Oct 2021 - Apr 2022

### Future Improvements
1. **Parallel backfill** - Run multiple dates in parallel (currently sequential)
2. **Resume capability** - Better checkpoint/resume for interrupted backfills
3. **Auto-validation** - Automatic failure rate checking vs expected

---

## Useful Commands

```bash
# Check November 2021 status
bq query 'SELECT "PSZA", COUNT(DISTINCT DATE(analysis_date)) FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) BETWEEN "2021-11-01" AND "2021-11-30"'

# Check failure breakdown
bq query 'SELECT processor_name, failure_category, COUNT(*) FROM nba_processing.precompute_failures WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY 1,2'

# Validate single date
python bin/validate_pipeline.py 2021-11-22 --phase 4 --verbose

# Run Phase 4 backfill
./bin/backfill/run_phase4_backfill.sh --start 2021-11-01 --end 2021-11-30 --skip-preflight
```

---

## Summary

This session established:
1. **100x speedup** for backfill mode (dependency check skip)
2. **Clear documentation** for Phase 4 backfills
3. **Expected failure rates** so we don't chase false bugs
4. **Testing philosophy** - Small samples before full runs

The backfill system is now documented and optimized. Future sessions should:
- Read `phase4-precompute-backfill.md` before running backfills
- Test small samples first
- Compare failure rates to expected before investigating
