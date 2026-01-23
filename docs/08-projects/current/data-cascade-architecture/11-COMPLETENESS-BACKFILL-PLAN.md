# Historical Completeness Metadata Backfill Plan

**Created:** 2026-01-23
**Status:** Ready to Execute
**Priority:** P1 - Data Quality

---

## Executive Summary

The `historical_completeness` field in `ml_feature_store_v2` is only populated for ~20% of records. To enable proper data gap detection and cascade reprocessing, we need to backfill the entire feature store.

---

## Current State

### Coverage by Season

| Season | Dates | Records | Has Completeness | % Populated |
|--------|-------|---------|------------------|-------------|
| 2024-25 (Nov-Jun) | 169 | 25,846 | 0 | **0.0%** |
| 2025-26 (Nov-Jan) | 78 | 18,434 | 4,235 | **23.0%** |
| **Total** | 277 | 44,280 | 4,235 | **9.6%** |

### Monthly Breakdown (2025-26 Season)

| Month | Dates | Records | % Populated |
|-------|-------|---------|-------------|
| Nov 2025 | 26 | 6,217 | 13.9% |
| Dec 2025 | 30 | 6,829 | 16.8% |
| Jan 2026 | 22 | 5,388 | 41.3% |

---

## Key Finding: Backfill Mode Does NOT Skip Completeness

After reviewing `ml_feature_store_processor.py`, the `backfill_mode=True` flag:
- ✅ **DOES** populate `historical_completeness` (lines 967-1069)
- ✅ Lowers player threshold (100 → 20) for dependency checks
- ✅ Uses actual roster instead of expected roster
- ❌ Does NOT skip completeness tracking

**Conclusion:** Running the backfill will correctly populate completeness metadata.

---

## Backfill Requirements

### Phase 4 Dependency Chain

The ML Feature Store is the **FINAL** processor (5/5) in Phase 4. It requires:

1. `team_defense_zone_analysis` (Phase 4 - #1)
2. `player_shot_zone_analysis` (Phase 4 - #2)
3. `player_composite_factors` (Phase 4 - #3)
4. `player_daily_cache` (Phase 4 - #4)

**Important:** Phase 4 data likely already exists from previous backfills. The feature store backfill should just re-run with completeness tracking.

### Backfill Script Location

```
backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py
```

---

## Recommended Backfill Strategy

### Option A: Full Season Reprocessing (Recommended)

Reprocess the entire 2024-25 and 2025-26 seasons to ensure all records have completeness metadata.

```bash
# 2024-25 Season (Nov 2024 - June 2025)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2025-06-30

# 2025-26 Season (Nov 2025 - Present)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-01 \
  --end-date 2026-01-22
```

**Estimated Time:**
- ~277 game dates
- ~160 players per date average
- ~5-10 seconds per date
- **Total: 30-60 minutes**

### Option B: Incremental Approach

If Phase 4 dependencies are incomplete for some dates, run in smaller chunks:

```bash
# Dry run to check dependencies first
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2024-11-30 \
  --dry-run

# Then run actual backfill
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2024-11-30
```

---

## Pre-Flight Checks

Before running the backfill:

### 1. Verify Phase 4 Dependencies Exist

```bash
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2024-11-01 \
  --end-date 2026-01-22 \
  --verbose
```

### 2. Check Current Feature Store State

```sql
SELECT
  FORMAT_DATE("%Y-%m", game_date) as month,
  COUNT(*) as records,
  COUNTIF(historical_completeness.is_complete IS NOT NULL) as has_completeness
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= "2024-11-01"
GROUP BY 1
ORDER BY 1
```

### 3. Verify Disk Space for Checkpoint

Checkpoint file location: `~/.nba_backfill_checkpoints/ml_feature_store_*.json`

---

## Execution Plan

### Step 1: Dry Run (5 minutes)

```bash
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2024-11-07 \
  --dry-run
```

Expected output:
```
✓ Dry run: ALL Phase 4 dependencies available
```

### Step 2: Small Test Run (5 minutes)

```bash
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-06 \
  --end-date 2024-11-06
```

Verify completeness is populated:
```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(historical_completeness.is_complete IS NOT NULL) as has_completeness
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = "2024-11-06"
GROUP BY 1
```

### Step 3: Full Backfill (30-60 minutes)

Run with checkpoint support for resumability:

```bash
# 2024-25 Season
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2025-06-30

# 2025-26 Season
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-01 \
  --end-date 2026-01-22
```

### Step 4: Verify Results

```sql
SELECT
  FORMAT_DATE("%Y-%m", game_date) as month,
  COUNT(*) as records,
  COUNTIF(historical_completeness.is_complete IS NOT NULL) as has_completeness,
  ROUND(COUNTIF(historical_completeness.is_complete IS NOT NULL) / COUNT(*) * 100, 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= "2024-11-01"
GROUP BY 1
ORDER BY 1
```

Expected: 100% populated for all months.

---

## Monitoring During Backfill

### Watch Progress

```bash
# Check checkpoint status
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --status

# Monitor logs
tail -f /tmp/ml_feature_store_backfill.log
```

### Resume After Interruption

```bash
# Checkpoint auto-resumes from last successful date
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2025-06-30
```

### Start Fresh (Clear Checkpoint)

```bash
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 \
  --end-date 2025-06-30 \
  --no-resume
```

---

## Post-Backfill Validation

### 1. Full Coverage Check

```sql
SELECT
  COUNTIF(historical_completeness.is_complete IS NULL) as missing,
  COUNT(*) as total,
  ROUND(COUNTIF(historical_completeness.is_complete IS NULL) / COUNT(*) * 100, 2) as pct_missing
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= "2024-11-01"
```

**Target:** 0% missing

### 2. Data Gap Detection

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(historical_completeness.is_complete = true) as complete,
  COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as data_gaps,
  COUNTIF(historical_completeness.is_bootstrap) as bootstrap
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= "2024-11-01"
GROUP BY 1
HAVING data_gaps > 0
ORDER BY 1
```

### 3. Contributing Dates Populated

```sql
SELECT
  game_date,
  player_lookup,
  historical_completeness.games_found,
  ARRAY_LENGTH(historical_completeness.contributing_game_dates) as num_dates
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = "2026-01-22"
LIMIT 5
```

---

## Rollback Plan

If issues occur, the backfill uses MERGE operations which update existing records. To restore:

1. Records are not deleted, only updated
2. Worst case: `historical_completeness` has incorrect values
3. Fix: Re-run backfill with corrected processor code

---

## Success Criteria

- [ ] 100% of records have `historical_completeness` populated
- [ ] `is_complete`, `is_bootstrap` flags are accurate
- [ ] `contributing_game_dates` array is populated
- [ ] No regressions in other feature values
- [ ] Daily health check shows completeness metrics

---

## Next Steps After Backfill

1. **Add to Daily Health Check** - Monitor completeness coverage daily
2. **Update Prediction Coordinator** - Filter features where `is_complete = false`
3. **Enable Cascade Detection** - Use `contributing_game_dates` to identify affected features after raw data backfills

---

## Commands Quick Reference

```bash
# Dry run
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 --end-date 2025-06-30 --dry-run

# Full run
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-11-01 --end-date 2025-06-30

# Check status
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --status

# Retry specific dates
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --dates 2024-11-06,2024-11-07,2024-11-08
```
