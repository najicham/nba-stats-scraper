# Backfill Optimization Implementation Plan
**Date**: 2026-01-03
**Status**: 🟢 READY TO IMPLEMENT
**Estimated Time**: 2-3 hours implementation + 8-12 hours execution

---

## 🎯 EXECUTIVE SUMMARY

**Problem**: Current backfill will take 6 days (unacceptable)
**Root Cause**: BigQuery shot zone queries take 1.7-2.8 hours per day
**Solution**: Implement parallel processing with 15-20 concurrent workers
**Outcome**: 6 days → 8-12 hours (same-day completion!)

**ML Model Requirements** ✅ VERIFIED:
- Model **DOES use** shot zone features (`paint_rate_last_10`, `mid_range_rate_last_10`, etc.)
- These are indices 14-17 in the 21-feature model
- Model CAN work without them (fills with league averages: 30%, 20%, 30%, 60%)
- But performance will be degraded without real data
- **Recommendation**: Keep shot zones, use parallel processing

---

## 📊 PERFORMANCE COMPARISON

| Strategy | Implementation Time | Execution Time | ML Performance | Risk |
|----------|---------------------|----------------|----------------|------|
| **Current (no changes)** | 0 hours | 6 days | ✅ Full features | 🟢 Low |
| **Strategy 1: Skip shot zones** | 1 hour | 1 hour | ⚠️ Degraded (missing 4 features) | 🟢 Low |
| **Strategy 3: Parallel (15 workers)** | 2-3 hours | 8-12 hours | ✅ Full features | 🟡 Medium |
| **Hybrid: Skip + later backfill** | 1 hour + 6 hours later | 1 hour + 6 hours | ✅ Full (eventually) | 🟡 Medium |

**RECOMMENDATION**: **Strategy 3 (Parallel Processing)** ⭐
- Best balance of time vs ML performance
- Same-day completion with full features
- Proven pattern (already uses ThreadPoolExecutor for record processing)

---

## 🔧 IMPLEMENTATION: PARALLEL BACKFILL

### Overview

**Current Architecture**:
```python
for day in 944 days:  # Sequential
    process_day(day)  # 1.7-2.8 hours each
```

**New Architecture**:
```python
with ThreadPoolExecutor(max_workers=15) as executor:
    futures = {executor.submit(process_day, day): day for day in 944 days}
    for future in as_completed(futures):
        handle_result(future)  # Parallel execution
```

**Key Changes**:
1. Wrap day processing in `ThreadPoolExecutor`
2. Thread-safe checkpoint updates (add lock)
3. Concurrent BigQuery queries (check quotas)
4. Progress tracking with concurrent counter

---

## 📝 DETAILED IMPLEMENTATION STEPS

### Step 1: Add Parallel Processing to Backfill Script (1.5 hours)

**File**: `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

**Changes Required**:

#### 1.1: Add imports and threading support (lines 1-50)

```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict

# Add progress tracker class
@dataclass
class ProgressTracker:
    """Thread-safe progress tracking."""
    lock: threading.Lock = threading.Lock()
    processed: int = 0
    successful: int = 0
    failed: int = 0
    total_records: int = 0

    def increment(self, success: bool, records: int = 0):
        with self.lock:
            self.processed += 1
            if success:
                self.successful += 1
                self.total_records += records
            else:
                self.failed += 1

    def get_stats(self):
        with self.lock:
            return {
                'processed': self.processed,
                'successful': self.successful,
                'failed': self.failed,
                'total_records': self.total_records
            }
```

#### 1.2: Modify BackfillCheckpoint for thread safety (new method)

```python
# Add to BackfillCheckpoint class (in shared/backfill/checkpoint.py or inline)
class ThreadSafeCheckpoint:
    """Wrapper for thread-safe checkpoint operations."""

    def __init__(self, checkpoint: BackfillCheckpoint):
        self.checkpoint = checkpoint
        self.lock = threading.Lock()

    def mark_date_complete(self, date):
        with self.lock:
            self.checkpoint.mark_date_complete(date)

    def mark_date_failed(self, date, error):
        with self.lock:
            self.checkpoint.mark_date_failed(date, error)
```

#### 1.3: Create parallel processing function (new method in PlayerGameSummaryBackfill)

```python
def run_backfill_parallel(
    self,
    start_date: date,
    end_date: date,
    dry_run: bool = False,
    no_resume: bool = False,
    max_workers: int = 15
):
    """
    Run backfill with parallel day processing.

    Args:
        max_workers: Number of concurrent workers (default 15)
            - Recommended: 10-20 (balance speed vs BigQuery quotas)
            - Lower if hitting BigQuery quota limits
            - Higher for faster processing (test first!)
    """
    logger.info(f"🚀 Starting PARALLEL backfill with {max_workers} workers")
    logger.info(f"   Date range: {start_date} to {end_date}")

    if not self.validate_date_range(start_date, end_date):
        return

    # Initialize checkpoint
    checkpoint = BackfillCheckpoint(
        job_name='player_game_summary',
        start_date=start_date,
        end_date=end_date
    )
    thread_safe_checkpoint = ThreadSafeCheckpoint(checkpoint)

    # Build date list
    dates_to_process = []
    current = start_date
    while current <= end_date:
        dates_to_process.append(current)
        current += timedelta(days=1)

    # Resume from checkpoint
    if checkpoint.exists() and not no_resume:
        resume_date = checkpoint.get_resume_date()
        if resume_date and resume_date > start_date:
            logger.info(f"📂 Resuming from {resume_date}")
            dates_to_process = [d for d in dates_to_process if d >= resume_date]

    total_days = len(dates_to_process)
    logger.info(f"Processing {total_days} days with {max_workers} parallel workers")
    logger.info(f"Estimated time: {(total_days / max_workers) * 2.5 / 60:.1f} hours")

    # Progress tracker
    progress = ProgressTracker()
    failed_days = []
    failed_days_lock = threading.Lock()

    # Worker function
    def process_single_day(day: date) -> Dict:
        """Process a single day (runs in thread)."""
        try:
            result = self.run_analytics_processing(day, dry_run)

            # Update checkpoint
            if result['status'] == 'success':
                thread_safe_checkpoint.mark_date_complete(day)
                progress.increment(True, result.get('records_processed', 0))
                logger.info(f"  ✓ {day}: {result.get('records_processed', 0)} records")
            else:
                error = result.get('error', 'Processing failed')
                thread_safe_checkpoint.mark_date_failed(day, error)
                progress.increment(False)
                with failed_days_lock:
                    failed_days.append(day)
                logger.error(f"  ✗ {day}: {error}")

            return result

        except Exception as e:
            logger.error(f"Exception processing {day}: {e}", exc_info=True)
            thread_safe_checkpoint.mark_date_failed(day, str(e))
            progress.increment(False)
            with failed_days_lock:
                failed_days.append(day)
            return {'status': 'exception', 'date': day, 'error': str(e)}

    # Execute parallel processing
    logger.info("=" * 80)
    logger.info("PARALLEL PROCESSING STARTED")
    logger.info("=" * 80)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        futures = {executor.submit(process_single_day, day): day for day in dates_to_process}

        # Process results as they complete
        for future in as_completed(futures):
            day = futures[future]

            # Progress update every 10 days
            stats = progress.get_stats()
            if stats['processed'] % 10 == 0:
                pct = stats['processed'] / total_days * 100
                success_rate = stats['successful'] / stats['processed'] * 100 if stats['processed'] > 0 else 0
                avg_records = stats['total_records'] / stats['successful'] if stats['successful'] > 0 else 0

                logger.info("=" * 80)
                logger.info(f"PROGRESS: {stats['processed']}/{total_days} days ({pct:.1f}%)")
                logger.info(f"  Success: {stats['successful']} ({success_rate:.1f}%)")
                logger.info(f"  Failed: {stats['failed']}")
                logger.info(f"  Records: {stats['total_records']:,} (avg {avg_records:.0f}/day)")
                logger.info("=" * 80)

    # Final summary
    stats = progress.get_stats()
    logger.info("=" * 80)
    logger.info("PARALLEL BACKFILL COMPLETE")
    logger.info("=" * 80)
    logger.info(f"  Total days: {total_days}")
    logger.info(f"  Successful: {stats['successful']}")
    logger.info(f"  Failed: {stats['failed']}")
    logger.info(f"  Success rate: {stats['successful']/total_days*100:.1f}%")
    logger.info(f"  Total records: {stats['total_records']:,}")
    if stats['successful'] > 0:
        logger.info(f"  Avg records/day: {stats['total_records']/stats['successful']:.0f}")

    if failed_days:
        logger.info(f"\n  Failed dates ({len(failed_days)}):")
        logger.info(f"    {', '.join(str(d) for d in failed_days[:10])}")
        if len(failed_days) > 10:
            logger.info(f"    ... and {len(failed_days) - 10} more")

    logger.info("=" * 80)
```

#### 1.4: Add CLI argument for parallel mode (modify main())

```python
def main():
    parser = argparse.ArgumentParser(...)
    # ... existing arguments ...
    parser.add_argument('--parallel', action='store_true', help='Use parallel processing (faster)')
    parser.add_argument('--workers', type=int, default=15, help='Number of parallel workers (default: 15)')

    args = parser.parse_args()

    # ... existing code ...

    # Choose backfill mode
    if args.parallel:
        logger.info(f"🚀 Using PARALLEL mode with {args.workers} workers")
        backfiller.run_backfill_parallel(
            start_date, end_date,
            dry_run=args.dry_run,
            no_resume=args.no_resume,
            max_workers=args.workers
        )
    else:
        logger.info("Using SEQUENTIAL mode (slower)")
        backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, no_resume=args.no_resume)
```

---

### Step 2: Test with Small Date Range (30 min)

**Test Plan**:
```bash
# Test 1: 7 days with 3 workers (should take ~5-6 hours = 2 hours parallel)
PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-10 \
  --end-date 2022-01-17 \
  --parallel \
  --workers 3 \
  2>&1 | tee logs/backfill_test_parallel_$(date +%Y%m%d_%H%M%S).log

# Monitor logs for:
# - Concurrent processing (multiple "Processing day X" at once)
# - No errors
# - Checkpoint updates working
# - Final summary showing 7/7 successful

# Test 2: Check BigQuery quotas (monitor during test)
# - Go to: https://console.cloud.google.com/bigquery?project=nba-props-platform
# - Check "Queries" tab for concurrent queries
# - Verify no "quota exceeded" errors

# Test 3: Verify data quality (after test completes)
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as records,
  COUNTIF(minutes_played IS NULL) as null_minutes,
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN "2022-01-10" AND "2022-01-17"
'
# Expected: null_pct around 0-2% (parser fix working)
```

**Success Criteria**:
- ✅ All 7 days processed successfully
- ✅ Processing time < 3 hours (vs 14 hours sequential)
- ✅ No BigQuery quota errors
- ✅ NULL rate 0-5% (parser fix working)
- ✅ Checkpoint file updated correctly

---

### Step 3: Kill Current Backfill and Start Optimized Version (5 min)

```bash
# Kill current backfill
tmux kill-session -t backfill-2021-2024

# Verify it's stopped
ps aux | grep player_game_summary_analytics_backfill

# Start optimized parallel backfill (15 workers)
tmux new-session -d -s backfill-parallel-2021-2024 \
  "source .venv/bin/activate && PYTHONPATH=. python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --parallel \
  --workers 15 \
  2>&1 | tee logs/backfill_parallel_$(date +%Y%m%d_%H%M%S).log"

# Monitor progress
tmux attach -t backfill-parallel-2021-2024

# Or watch logs
tail -f logs/backfill_parallel_*.log | grep -E "PROGRESS:|✓|✗"
```

**Expected Timeline**:
- **With 15 workers**: 944 days / 15 ≈ 63 "batches"
- **Per batch time**: ~2.5 hours (slowest day in batch)
- **Total time**: 2.5 hours × (63/15) ≈ **10-12 hours**
- **Completion**: Jan 3, 8:00 PM - 10:00 PM PST

---

### Step 4: Monitor Execution (periodic checks)

**Monitoring Commands**:
```bash
# Check progress every hour
watch -n 3600 'tail -50 logs/backfill_parallel_*.log | grep "PROGRESS:"'

# Check for errors
tail -200 logs/backfill_parallel_*.log | grep -E "ERROR|Exception|Failed"

# Check BigQuery quota usage
# Go to: https://console.cloud.google.com/iam-admin/quotas?project=nba-props-platform
# Search for: "BigQuery API"
# Monitor: "Queries per day" and "Concurrent queries"

# Check tmux session status
tmux ls
tmux attach -t backfill-parallel-2021-2024  # Ctrl+B, D to detach
```

**What to Watch For**:
- ✅ Multiple days processing concurrently (good!)
- ⚠️ BigQuery quota exceeded errors (reduce workers if this happens)
- ⚠️ Memory errors (reduce workers if this happens)
- ✅ Progress updates every 10 days
- ✅ Checkpoint file updating regularly

---

### Step 5: Validate Results (when complete) (30 min)

Same validation queries from handoff doc:

```bash
# Primary: NULL rate check
bq query --use_legacy_sql=false --format=pretty '
SELECT
  COUNT(*) as total_records,
  COUNTIF(minutes_played IS NULL) as null_count,
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 2) as null_pct,
  ROUND(COUNTIF(minutes_played IS NOT NULL) / COUNT(*) * 100, 2) as has_data_pct,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
'

# Expected:
# - total_records: 120,000-150,000
# - null_pct: 35-45%
# - has_data_pct: 55-65%

# Secondary: Shot zones populated
bq query --use_legacy_sql=false --format=pretty '
SELECT
  COUNTIF(paint_attempts IS NOT NULL) as has_paint,
  COUNTIF(mid_range_attempts IS NOT NULL) as has_mid_range,
  COUNTIF(assisted_fg_makes IS NOT NULL) as has_assisted,
  COUNT(*) as total
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
  AND minutes_played IS NOT NULL
'

# Expected: >90% of records should have shot zone data
```

---

## ⚠️ RISK MITIGATION

### Risk 1: BigQuery Quota Exceeded

**Symptoms**: Errors like "Exceeded rate limits: too many concurrent queries"

**Mitigation**:
1. Reduce `--workers` from 15 → 10 → 5
2. Add `time.sleep(0.5)` between worker spawns
3. Check quota limits: https://cloud.google.com/bigquery/quotas

**Current GCP Quotas** (check your project):
- Concurrent queries: 100 (default)
- Interactive queries per day: 2,000 (default)
- 15 workers should be well under limits

### Risk 2: Memory Errors

**Symptoms**: Out of memory errors, process killed

**Mitigation**:
1. Reduce `--workers` to 5-10
2. Monitor memory: `watch -n 10 'ps aux | grep python | grep backfill'`
3. Each worker uses ~200MB, 15 workers = ~3GB (should be fine)

### Risk 3: Checkpoint Corruption

**Symptoms**: Lost progress, duplicate processing

**Mitigation**:
1. Thread-safe checkpoint wrapper (implemented above)
2. Backup checkpoint before starting: `cp /tmp/backfill_checkpoints/player_game_summary_*.json{,.backup}`
3. Can resume from backup if needed

### Risk 4: Data Inconsistency

**Symptoms**: Some days missing data, duplicate records

**Mitigation**:
1. Validate sample of dates after completion
2. Check for gaps: Query distinct dates in range
3. Re-run failed dates using `--dates` parameter

---

## 📈 EXPECTED OUTCOMES

### Performance Gains

| Metric | Sequential (Current) | Parallel (15 workers) | Improvement |
|--------|---------------------|----------------------|-------------|
| Processing rate | 6.3 days/hour | ~95 days/hour | **15x faster** |
| Completion time | 6 days | 10-12 hours | **14x faster** |
| Total queries | 944 | 944 (concurrent) | Same |
| BigQuery cost | $X | $X (same queries) | Same |

### Data Quality (Unchanged)

- NULL rate: 35-45% (same as sequential)
- Total records: 120K-150K (same)
- Shot zones: Full coverage (same)
- Validation: All checks pass (same)

### ML Impact

- Training data ready: **Tonight** (vs Jan 9)
- Full 21 features: ✅ (including shot zones)
- Expected MAE: 3.70-4.00 (target: <4.00)

---

## 🎯 DECISION TREE

**If test (Step 2) succeeds**:
→ Proceed to full backfill (Step 3)
→ Monitor execution (Step 4)
→ Validate and proceed to ML (Step 5)

**If test hits BigQuery quota errors**:
→ Reduce workers to 10, re-test
→ If still failing, reduce to 5
→ If still failing, fall back to sequential + skip shot zones

**If test has checkpoint/concurrency issues**:
→ Debug thread safety
→ Add more logging
→ Fall back to sequential if unfixable

**If test shows degraded data quality**:
→ Investigate root cause
→ Fix and re-test
→ Don't proceed to full backfill until resolved

---

## ✅ IMPLEMENTATION CHECKLIST

### Pre-Implementation (10 min)
- [x] Analysis complete (PERFORMANCE-BOTTLENECK-ANALYSIS.md)
- [x] Implementation plan reviewed (this document)
- [x] ML feature requirements verified (shot zones needed)
- [ ] Backup current checkpoint file
- [ ] Backup current code (git commit)

### Implementation (2-3 hours)
- [ ] Add threading imports and ProgressTracker class
- [ ] Add ThreadSafeCheckpoint wrapper
- [ ] Implement `run_backfill_parallel()` method
- [ ] Add `--parallel` and `--workers` CLI arguments
- [ ] Test code compiles (no syntax errors)

### Testing (1-2 hours)
- [ ] Run 7-day test with 3 workers
- [ ] Verify concurrent processing in logs
- [ ] Check BigQuery quota dashboard
- [ ] Validate NULL rate on test data (0-5%)
- [ ] Verify checkpoint file updated correctly

### Deployment (5 min + 10-12 hours execution)
- [ ] Kill current sequential backfill
- [ ] Start parallel backfill (15 workers)
- [ ] Monitor for first 30 minutes (watch for errors)
- [ ] Check progress after 2 hours (should be ~20-30% done)
- [ ] Final check after 8 hours (should be ~80% done)

### Validation (30 min)
- [ ] Verify backfill completed successfully
- [ ] Run NULL rate validation query (35-45% target)
- [ ] Run shot zone coverage query (>90% target)
- [ ] Run data volume query (120K-150K target)
- [ ] Spot check: Sample game data looks correct

### Proceed to ML (next session)
- [ ] Backfill SUCCESS confirmed
- [ ] Read ML training handoff doc
- [ ] Train ML v3 with full historical data
- [ ] Evaluate vs baseline (MAE <4.00 target)

---

## 📞 SUPPORT & TROUBLESHOOTING

**If you get stuck**:
1. Check logs: `tail -200 logs/backfill_parallel_*.log`
2. Check tmux: `tmux attach -t backfill-parallel-2021-2024`
3. Check process: `ps aux | grep backfill`
4. Check BigQuery console for quota errors
5. Refer to Risk Mitigation section above

**Emergency rollback**:
```bash
# Kill parallel backfill
tmux kill-session -t backfill-parallel-2021-2024

# Restore checkpoint from backup
cp /tmp/backfill_checkpoints/player_game_summary_*.json.backup \
   /tmp/backfill_checkpoints/player_game_summary_*.json

# Resume sequential backfill
tmux new-session -d -s backfill-2021-2024 \
  "source .venv/bin/activate && PYTHONPATH=. python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  2>&1 | tee logs/backfill_resume_$(date +%Y%m%d_%H%M%S).log"
```

---

**Next Steps**: Ready to implement! Proceed to Step 1 when ready.
