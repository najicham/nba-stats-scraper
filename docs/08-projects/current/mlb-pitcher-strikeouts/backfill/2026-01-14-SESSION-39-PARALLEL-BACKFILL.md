# Session 39: Parallel Backfill Implementation

**Date:** 2026-01-14
**Focus:** Speed optimization for historical betting lines backfill

## Summary

Implemented parallel processing to dramatically speed up the MLB historical backfill:
- **Phase 1 (GCS scraping):** 12x faster with 9 parallel workers
- **Phase 2 (BigQuery loading):** 40x faster with batch NDJSON loading

## What Was Done

### 1. Created Batch Loader (40x speedup)
**File:** `scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py`

Old approach: Load each file individually (~5 sec/file)
New approach: Accumulate rows, single batch insert (~1000 rows/sec)

```python
# Key optimization: NDJSON batch loading
ndjson_data = "\n".join(json.dumps(row) for row in rows)
load_job = bq_client.load_table_from_file(
    io.BytesIO(ndjson_bytes), table_id, job_config=job_config
)
```

**Performance:**
- Old: ~0.8 dates/min
- New: ~33 dates/min

### 2. Parallel Workers for Phase 1 (12x speedup)
Instead of single sequential scraper, run multiple workers on different date ranges:

```bash
# Worker 1: Sep-Nov 2024
# Worker 2: Nov 2024 - Mar 2025 (off-season, 0 dates)
# Worker 3: Mar-Jun 2025
# Worker 4: Jun-Sep 2025
# Worker 5-11: Additional date ranges
```

**Performance:**
- Old: ~8 dates/hour (sequential)
- New: ~100 dates/hour (9 workers)

### 3. Progress Dashboard
**File:** `scripts/mlb/historical_odds_backfill/check_backfill_progress.py`

Single command to see status of all phases:
```bash
python scripts/mlb/historical_odds_backfill/check_backfill_progress.py
```

### 4. Automated Phase Runner
**File:** `scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py`

After Phase 1 completes, run all remaining phases:
```bash
python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
```

## Current Status (as of session end)

```
Phase 1 (GCS scraping): 88% complete (43 dates remaining)
Phase 2 (BigQuery):     71% complete
Coverage:               62.6% (5,092 matchable predictions)
```

**Estimated completion:** ~15-20 minutes for Phase 1

## Files Created/Modified

### New Files
- `scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py` - Batch loader
- `scripts/mlb/historical_odds_backfill/backfill_parallel.py` - Parallel scraper (attempted)
- `scripts/mlb/historical_odds_backfill/check_backfill_progress.py` - Progress dashboard
- `scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py` - Phase runner
- `docs/08-projects/current/mlb-pitcher-strikeouts/backfill/` - Documentation

### Running Processes
```bash
# Check running workers
ps aux | grep "backfill_historical" | grep python

# Check batch loader
ps aux | grep "batch_load" | grep python
```

## Next Steps

1. **Wait for Phase 1 to complete** (~15-20 min)
2. **Run phases 2-5:**
   ```bash
   python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
   ```
3. **Review hit rate results**
4. **Make go/no-go decision** based on hit rate

## Key Learnings

1. **Subprocess parallelism is tricky** - ThreadPoolExecutor doesn't parallelize subprocess calls well. Solution: run multiple separate processes.

2. **Batch loading is crucial** - Individual BigQuery inserts are slow due to API overhead. NDJSON batch loading is dramatically faster.

3. **GCS scanning is expensive** - Pre-scan existing files once instead of checking per-file.

## Commands Reference

```bash
# Check progress
python scripts/mlb/historical_odds_backfill/check_backfill_progress.py

# Add more parallel workers (if needed)
python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py \
  --start-date 2025-08-20 --end-date 2025-09-10 --delay 0.1 --resume &

# Sync BigQuery with GCS
python scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py

# Run all remaining phases
python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py
```
