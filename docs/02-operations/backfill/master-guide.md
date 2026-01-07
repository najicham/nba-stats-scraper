# Backfill Master Guide

**Purpose**: Complete guide for backfilling pipeline data across all phases
**Last Updated**: January 6, 2026
**Applies To**: Phases 2-6 of the NBA props pipeline

---

## Table of Contents

1. [Overview](#overview)
2. [When to Run Backfills](#when-to-run-backfills)
3. [Prerequisites](#prerequisites)
4. [Phase Dependencies](#phase-dependencies)
5. [Execution Procedure](#execution-procedure)
6. [Performance Optimization](#performance-optimization)
7. [Validation & Quality Checks](#validation--quality-checks)
8. [Troubleshooting](#troubleshooting)
9. [Historical Examples](#historical-examples)

---

## Overview

### What is a Backfill?

A backfill is the process of retroactively populating pipeline data for historical dates that were either:
- Never processed (gaps in coverage)
- Processed incorrectly and need reprocessing
- Missing due to pipeline failures

### Backfill vs Normal Processing

| Normal Processing | Backfill |
|-------------------|----------|
| Processes today's games | Processes historical dates |
| Triggered by schedules/events | Triggered manually |
| Real-time data sources | Historical data already in lower phases |
| Single date | Date range (often 100s of dates) |
| Fast (minutes) | Slow (hours to days) |

### Current Pipeline Structure

```
Phase 1: Scrapers → Raw data collection
Phase 2: Raw Processing → Normalize and store
Phase 3: Analytics → Game summaries and stats
Phase 4: Precompute → Performance analysis and factors
Phase 5: Predictions → Generate predictions + grading
Phase 6: Publishing → Export to GCS for frontend
```

**This guide covers Phases 2-6**. Phase 1 (scrapers) rarely needs backfills since it fetches live data.

---

## When to Run Backfills

### Required Scenarios ✅

1. **New Table Added**: When you add a new analytics/precompute table, backfill historical data
2. **Pipeline Fix Deployed**: After fixing a bug that affected data quality, reprocess affected dates
3. **Data Gaps Discovered**: Coverage analysis reveals missing dates (e.g., only 400/918 dates present)
4. **Schema Migration**: After changing table schema, may need to reprocess to populate new columns
5. **ML Model Training**: Need complete historical dataset for training

### Optional Scenarios ⚠️

1. **Performance Improvement**: Logic improved but old data still valid (low priority)
2. **Enrichment**: Adding supplementary data that doesn't invalidate existing data

### Don't Backfill ❌

1. **Minor Formatting Changes**: If data is semantically correct, don't reprocess
2. **Recent Data Only**: If last 7 days have complete coverage, focus on gaps not recent data
3. **Speculative Improvements**: Don't backfill "just in case"

---

## Prerequisites

### Before Starting Any Backfill

#### 1. Data Completeness Validation

**Critical**: Validate prior phase has required data coverage

```sql
-- Example: Before backfilling Phase 3, check Phase 2
SELECT
  COUNT(DISTINCT game_date) as dates_available,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= '2021-10-19'  -- Adjust date range
```

**Requirement**: ≥95% completeness in prior phase before backfilling next phase

**Why?**: Incomplete upstream data produces incomplete downstream data, creating cascading gaps

#### 2. Phase Dependencies Check

Use this dependency tree:

```
Phase 2 (standalone - reads from Phase 1 GCS files)
    ↓
Phase 3 (requires Phase 2 ≥95% complete)
    ↓
Phase 4 (requires Phase 3 ≥95% complete)
    ↓
Phase 5 (requires Phase 4 ≥95% complete)
    ↓
Phase 6 (requires Phase 5 completion)
```

**Never run Phase N backfill until Phase N-1 is ≥95% complete**

#### 3. BigQuery Quota

**Check quota**:
```bash
# Current quota usage
bq ls --max_results=1  # Test query
```

**Requirements**:
- Phase 2-3: ~1,000 queries per 100 dates
- Phase 4: ~2,000 queries per 100 dates
- Phase 5: ~500 queries per 100 dates

**Free tier limit**: 10,000 queries/day

**Large backfills (>500 dates)**: May hit quota. Use `--workers` to throttle or split across days.

#### 4. No Concurrent Backfills

**Critical**: Only run ONE backfill at a time per phase

**Why?**: Concurrent backfills can cause:
- BigQuery MERGE conflicts (duplicate rows)
- Quota exhaustion
- Data corruption

**Check for running backfills**:
```bash
ps aux | grep backfill
# Or check for specific PIDs in logs
```

#### 5. Validation Framework Available

The validation framework provides critical data quality gates:

```bash
# Verify validation framework is deployed
ls -la validation/validators/
```

See [Validation Framework Documentation](../../validation-framework/README.md) for details.

---

## Phase Dependencies

### Detailed Dependency Chain

#### Phase 2 → Phase 3
**Phase 3 tables require**:
- `nba_raw.nbac_player_boxscores` (player stats)
- `nba_raw.bdl_player_box_scores` (supplementary stats)
- `nba_raw.nbac_play_by_play` (game events)
- `nba_raw.odds_game_lines` (betting lines)

**Validation Query**:
```sql
-- Check Phase 2 coverage before Phase 3 backfill
SELECT
  COUNT(DISTINCT game_date) as dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / 918, 1) as pct_complete
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2026-01-03'
```

**Requirement**: ≥870 dates (95% of 918)

#### Phase 3 → Phase 4
**Phase 4 tables require**:
- `nba_analytics.player_game_summary` (complete player stats)
- `nba_analytics.team_offense_game_summary` (team offense)
- `nba_analytics.team_defense_game_summary` (team defense)

**Validation Query**:
```sql
-- Check Phase 3 coverage before Phase 4 backfill
SELECT
  COUNT(DISTINCT game_date) as dates,
  ROUND(100.0 * COUNT(DISTINCT game_date) / 918, 1) as pct_complete
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2026-01-03'
```

**Requirement**: ≥870 dates (95%)

#### Phase 4 → Phase 5
**Phase 5 prediction engine requires**:
- `nba_precompute.player_composite_factors` (player performance factors)
- `nba_precompute.player_daily_cache` (recent form cache)
- `nba_precompute.team_defense_zone_analysis` (defensive matchups)

**Validation Query**:
```sql
-- Check Phase 4 coverage before Phase 5 backfill
SELECT
  COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-19'
```

**Requirement**: ≥848 dates (92% - Phase 4 has bootstrap periods that are expected gaps)

#### Phase 5 → Phase 6
**Phase 6 exports require**:
- `nba_predictions.player_prop_predictions` (prediction data)
- `nba_predictions.prediction_grading` (historical grades)

**No percentage requirement** - Phase 6 exports whatever Phase 5 produced

---

## Execution Procedure

### Step 1: Choose Execution Pattern

Two patterns available:

#### Pattern A: Sequential (Safe, Slow)
**When to use**:
- First time backfilling a table
- Debugging issues
- Small date ranges (<100 dates)

**Characteristics**:
- Processes dates one at a time
- Easy to monitor and debug
- Slow (1-3 dates/minute)

**Command**:
```bash
PYTHONPATH=. python3 backfill_jobs/analytics/{table}/{table}_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03
```

#### Pattern B: Parallel (Fast, Complex)
**When to use**:
- Large date ranges (>200 dates)
- Table backfilled successfully before
- Production-grade backfills

**Characteristics**:
- Processes multiple dates concurrently
- Requires worker tuning
- Fast (10-50 dates/minute with optimal workers)
- Checkpoint/resume capable

**Command**:
```bash
PYTHONPATH=. python3 backfill_jobs/analytics/{table}/{table}_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 15
```

### Step 2: Configure Workers

Worker count affects:
- **Speed**: More workers = faster processing
- **Quota**: More workers = higher query rate
- **Reliability**: Too many workers = BigQuery throttling

**Recommended Worker Counts**:

| Date Range | Phase 3 | Phase 4 | Phase 5 |
|------------|---------|---------|---------|
| <100 dates | 5 | 5 | 3 |
| 100-500 dates | 15 | 10 | 5 |
| 500+ dates | 25 | 15 | 8 |

**Performance Data** (from Jan 2026 backfills):
- Phase 3 (918 dates, 25 workers): 24 hours
- Phase 4 (918 dates, 15 workers): 30 hours

### Step 3: Enable Checkpointing

**Critical for large backfills**: Enable checkpoints for resume capability

Checkpoints are automatically enabled in all backfill scripts. They save to `/tmp/backfill_checkpoints/`

**Check checkpoint status**:
```bash
ls -lh /tmp/backfill_checkpoints/
cat /tmp/backfill_checkpoints/{table}_*.json
```

**Resume from checkpoint**: Just re-run the same command. Script automatically detects and resumes.

### Step 4: Run Backfill

**Best practice**: Use `nohup` for long-running backfills

```bash
# Create logs directory if needed
mkdir -p logs

# Run with output logging
nohup PYTHONPATH=. python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 25 \
  > logs/player_game_summary_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Capture PID
echo $! > /tmp/backfill_pid.txt
```

### Step 5: Monitor Progress

**Real-time log monitoring**:
```bash
tail -f logs/player_game_summary_*.log
```

**Look for**:
- ✅ `Processing date: YYYY-MM-DD` (progress indicator)
- ✅ `Checkpoint saved` (resume capability confirmed)
- ✅ `MERGE completed: N rows` (data inserted)
- ⚠️ `WARN` messages (non-critical issues)
- ❌ `ERROR` messages (investigate immediately)

**Progress percentage**:
```bash
# For Phase 3 (918 dates total)
cat logs/player_game_summary_*.log | grep "Processing date:" | wc -l
# Divide by 918 to get percentage
```

**Check database coverage** (more reliable than logs):
```sql
SELECT COUNT(DISTINCT game_date) as dates_processed
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2026-01-03'
```

### Step 6: Validate Completion

**Required validations after backfill completes**:

#### Coverage Validation
```sql
-- Check date coverage
SELECT
  COUNT(DISTINCT game_date) as dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  ROUND(100.0 * COUNT(DISTINCT game_date) / 918, 1) as pct_complete
FROM `nba-props-platform.nba_analytics.{table}`
WHERE game_date >= '2021-10-19'
```

**Expected**: ≥95% coverage (≥870 dates)

#### Duplicate Detection
```sql
-- Check for duplicates (CRITICAL)
SELECT
  game_date,
  player_lookup,
  COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
GROUP BY game_date, player_lookup
HAVING COUNT(*) > 1
LIMIT 100
```

**Expected**: 0 duplicates

**If duplicates found**: See [Troubleshooting: Duplicate Rows](#duplicate-rows) below

#### Data Quality Validation
```sql
-- Check for NULL critical fields
SELECT
  COUNT(*) as rows_with_null_minutes_played
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND minutes_played IS NULL
  AND minutes_played_str IS NOT NULL  -- Player did play
```

**Expected**: 0 rows (no incorrect NULLs)

---

## Performance Optimization

### Parallelization Breakthrough (Jan 2026)

During Jan 2026 backfills, we discovered optimal parallelization saves **200+ hours**:

**Before**: Sequential processing
- Phase 3 (918 dates): ~150 hours
- Phase 4 (918 dates): ~180 hours

**After**: Parallel with 15-25 workers
- Phase 3 (918 dates): 24 hours (6.25x speedup)
- Phase 4 (918 dates): 30 hours (6x speedup)

### Worker Optimization Formula

Optimal workers = `min(date_count / 30, quota_limit / queries_per_date)`

**Example** (Phase 3, 918 dates):
- Theoretical max: 918 / 30 = 30 workers
- Quota limit: 10,000 / 300 = 33 workers
- **Practical optimum**: 25 workers (leaves quota buffer)

### Checkpoint Strategy

**Checkpoint frequency**: Every 10 dates processed

**Why?**:
- Resume capability if interrupted
- Minimal overhead (checkpoint write is fast)
- Granular progress tracking

**Storage**: `/tmp/backfill_checkpoints/{table}_{start_date}_{end_date}.json`

### BigQuery MERGE vs DELETE+INSERT

**Critical**: Always use SQL MERGE, never DELETE+INSERT

**Problem with DELETE+INSERT**:
```python
# ❌ BAD - Creates duplicates under concurrent load
bq_client.query(f"DELETE FROM table WHERE game_date = '{date}'")
bq_client.query(f"INSERT INTO table SELECT * FROM temp_table")
# Race condition between DELETE and INSERT
```

**Solution: Proper MERGE pattern**:
```python
# ✅ GOOD - Atomic operation, no duplicates
merge_query = f"""
MERGE `nba-props-platform.nba_analytics.player_game_summary` T
USING temp_table S
ON T.game_date = S.game_date AND T.player_lookup = S.player_lookup
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
"""
bq_client.query(merge_query)
```

**See**: `docs/05-development/patterns/merge-pattern.md` for template

---

## Validation & Quality Checks

### Pre-Flight Validation Checklist

Before starting backfill:

- [ ] Prior phase ≥95% complete
- [ ] No concurrent backfills running
- [ ] BigQuery quota available
- [ ] Validation framework deployed
- [ ] Backfill script tested on 1-2 dates
- [ ] Checkpoint directory writable

### In-Flight Monitoring

**Every 2 hours** during backfill:

- [ ] Check logs for ERROR messages
- [ ] Verify progress with database query
- [ ] Check quota usage
- [ ] Verify checkpoint file updating

### Post-Flight Validation

After backfill completes:

- [ ] Coverage ≥95% (≥870/918 dates for full backfill)
- [ ] Zero duplicate rows (run duplicate detection query)
- [ ] Zero NULL critical fields (run data quality query)
- [ ] Checkpoint file shows 100% complete
- [ ] Logs show "Backfill complete" message

### Validation Framework Integration

For Phase 3-4 tables, run validation framework:

```bash
cd validation
PYTHONPATH=. python3 validators/analytics/player_game_summary_validator.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03
```

**Expected**: All validations pass with 0 critical errors

See: [Validation Framework](../../validation-framework/README.md)

---

## Troubleshooting

### Common Issues

#### Duplicate Rows

**Symptom**: Multiple rows for same (game_date, player_lookup)

**Cause**: Using DELETE+INSERT pattern instead of MERGE

**Detection**:
```sql
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT game_date, player_lookup, COUNT(*) as cnt
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  GROUP BY game_date, player_lookup
  HAVING COUNT(*) > 1
)
```

**Fix**:
```sql
-- Deduplicate table
CREATE OR REPLACE TABLE `nba-props-platform.nba_analytics.player_game_summary` AS
SELECT * EXCEPT(row_num)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY _sys_timestamp DESC) as row_num
  FROM `nba-props-platform.nba_analytics.player_game_summary`
)
WHERE row_num = 1
```

**Prevention**: Use MERGE pattern in backfill scripts

**Reference**: [MERGE Bug Fix Commit](https://github.com/.../commit/6845287)

#### Game ID Format Mismatch

**Symptom**: Wrong team assignments (home/away swapped)

**Cause**: Inconsistent `is_home` calculation between data sources

**Detection**: Manual inspection or team mismatch count query

**Fix**: Update backfill script with corrected game_id parsing

**Reference**: [Game ID Bug Postmortem](../postmortems/2026/game-id-format-bug.md)

#### BigQuery Quota Exceeded

**Symptom**: `Quota exceeded` errors in logs

**Immediate fix**:
1. Kill backfill process: `kill $(cat /tmp/backfill_pid.txt)`
2. Wait for quota reset (midnight UTC)
3. Resume with fewer workers: `--workers 10` (reduce from 25)

**Long-term fix**:
- Reduce worker count
- Split backfill across multiple days
- Upgrade BigQuery quota (costs money)

#### Missing Upstream Data

**Symptom**: Backfill completes but coverage <95%

**Cause**: Prior phase missing data for those dates

**Detection**:
```sql
-- Find missing dates in Phase 3 that exist in Phase 2
SELECT DISTINCT game_date
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date NOT IN (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
)
  AND game_date >= '2021-10-19'
ORDER BY game_date
```

**Fix**: Backfill prior phase first, then retry current phase

#### Process Killed/Interrupted

**Symptom**: Backfill stopped mid-execution

**Detection**: No new log entries, process PID dead

**Recovery**:
1. Check checkpoint file: `cat /tmp/backfill_checkpoints/{table}_*.json`
2. Re-run same command - automatically resumes from checkpoint
3. Monitor logs for "Resuming from checkpoint" message

---

## Historical Examples

For detailed execution logs, performance data, and lessons learned from past backfills:

### January 2026: Complete Pipeline Backfill
**[Project Documentation](../../08-projects/completed/2026-01/complete-pipeline-backfill-2026-01/)**

- **Scope**: All phases, 918 dates, 2021-10-19 to 2026-01-03
- **Duration**: ~42 hours (Jan 5-7, 2026)
- **Key Achievement**: Parallelization breakthrough (200+ hours saved)
- **Issues Encountered**: MERGE bug, game ID format mismatch
- **Outcome**: 100% coverage achieved across all phases

**Performance Data**:
| Phase | Tables | Dates | Workers | Time | Speedup |
|-------|--------|-------|---------|------|---------|
| Phase 3 | 5 | 918 | 25 | 24h | 6.25x |
| Phase 4 | 4 | 918 | 15 | 30h | 6.0x |

### December 2025: Four-Season Backfill
**[Project Documentation](../../08-projects/completed/2025-12/four-season-backfill/)**

- **Scope**: Phase 5 only, 2021-2025 seasons
- **Pattern**: Sequential execution (pre-parallelization)
- **Lessons**: Led to development of parallel execution pattern

### November 2025: Phase 3 Initial Backfill
**[Project Documentation](../../08-projects/completed/2025-11/...)** (if exists)

- **Scope**: Phase 3 analytics tables
- **Issues**: Event-driven orchestration failures
- **Lesson**: Direct execution more reliable than event-driven

---

## Best Practices Summary

### Do's ✅

1. **Always validate prior phase** before backfilling next phase (≥95% coverage)
2. **Use parallel execution** for large date ranges (>200 dates)
3. **Enable checkpoints** for all backfills
4. **Monitor progress** every 2 hours during long backfills
5. **Run validation queries** after completion (coverage, duplicates, data quality)
6. **Use MERGE pattern** for upserts, never DELETE+INSERT
7. **Document unusual findings** in project directory or lessons-learned
8. **Test on small range first** (10-20 dates) before full backfill

### Don'ts ❌

1. **Never run concurrent backfills** of same table (causes duplicates)
2. **Never skip validation** of prior phase completeness
3. **Don't backfill without checkpoints** on large date ranges
4. **Don't use DELETE+INSERT** (use MERGE instead)
5. **Don't ignore quota warnings** (will hit hard limit and fail)
6. **Don't backfill speculatively** (only when needed)
7. **Don't forget to deduplicate** after backfill if duplicates found
8. **Don't run Phase N before Phase N-1 is ready** (creates incomplete data)

---

## Quick Reference Commands

### Start Parallel Backfill
```bash
nohup PYTHONPATH=. python3 backfill_jobs/analytics/{table}/{table}_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 25 \
  > logs/{table}_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo $! > /tmp/backfill_{table}_pid.txt
```

### Monitor Progress
```bash
# Live logs
tail -f logs/{table}_*.log

# Database coverage
bq query --use_legacy_sql=false \
  "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_analytics.{table}\` WHERE game_date >= '2021-10-19'"
```

### Check for Duplicates
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicates
FROM (
  SELECT game_date, player_lookup, COUNT(*) as cnt
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  GROUP BY game_date, player_lookup
  HAVING COUNT(*) > 1
)"
```

### Resume from Checkpoint
```bash
# Just re-run the same command - auto-resumes
PYTHONPATH=. python3 backfill_jobs/analytics/{table}/{table}_analytics_backfill.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --parallel \
  --workers 25
```

---

## Related Documentation

- [Troubleshooting Guide](./troubleshooting.md) - Detailed troubleshooting for specific errors
- [Validation Framework](../../validation-framework/README.md) - Data quality validation
- [Pipeline Dependencies](../../01-architecture/pipeline-dependencies.md) - Phase dependency graph
- [MERGE Pattern](../../05-development/patterns/merge-pattern.md) - Proper upsert template
- [Completed Projects](../../08-projects/completed/) - Historical backfill execution logs

---

**Questions or Issues?**

1. Check [Troubleshooting](#troubleshooting) section above
2. Review [Historical Examples](#historical-examples) for similar scenarios
3. Check project documentation in `docs/08-projects/completed/` for detailed execution logs

---

**Last Updated**: January 6, 2026
**Maintained By**: Data Engineering Team
**Next Review**: When significant backfill process changes occur
