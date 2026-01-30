# Session 28 Continuation Handoff

**Date:** 2026-01-30
**Status:** Model improvements implemented, duplicate cleanup issue needs architectural fix
**Priority for next session:** Fix streaming buffer deactivation race condition

---

## What This Session Accomplished

### 1. Recency-Weighted Training (Complete)

Added ability to weight recent games more heavily during model training.

**File:** `ml/experiments/train_walkforward.py`

**Changes:**
- Added `calculate_sample_weights()` function with exponential decay
- Added `--use-recency-weights` and `--half-life` CLI arguments
- Half-life of 180 days means games from 6 months ago have 50% weight

**To run experiment:**
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id RECENCY_WEIGHTED \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --use-recency-weights --half-life 180 \
    --verbose
```

### 2. Player Trajectory Features (Complete)

Added 3 new features to capture player performance trends.

**Files:**
- `data_processors/precompute/ml_feature_store/feature_calculator.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**New Features (34-36):**
| Feature | Description | Calculation |
|---------|-------------|-------------|
| `pts_slope_10g` | Points trend direction | Linear regression slope over L10 games |
| `pts_vs_season_zscore` | Performance vs baseline | (L5_avg - season_avg) / season_std |
| `breakout_flag` | Exceptional performance | 1.0 if L5 > season_avg + 1.5*std |

**Next step:** Backfill feature store to populate these for historical data:
```bash
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2025-10-01 --end-date 2026-01-29
```

### 3. Drift Monitoring (Complete)

Added model drift detection to `/validate-daily` skill.

**File:** `.claude/skills/validate-daily/SKILL.md`

**Added checks:**
- Weekly hit rate trend (alert if <55% for 2+ weeks)
- Player tier performance breakdown (stars vs bench)
- Model vs Vegas comparison

---

## Issue Discovered: Streaming Buffer Blocks Duplicate Cleanup

### The Problem

Duplicates exist in `player_prop_predictions` table (4,415 as of this session), but we cannot clean them up because BigQuery's streaming buffer blocks UPDATE/DELETE/MERGE operations on recently-inserted rows.

### Why Duplicates Exist

```
Timeline of a typical prediction batch:

07:41:28 UTC - Batch 1 runs MERGE → inserts predictions to main table
              ↓
              These rows enter streaming buffer (locked for 30-90 min)
              ↓
07:41:30 UTC - _deactivate_older_predictions() runs UPDATE
              ↓
              ERROR: Can't UPDATE rows in streaming buffer!
              ↓
              Duplicates remain active
              ↓
08:37:08 UTC - Batch 2 runs MERGE → inserts MORE predictions
              ↓
              Even more duplicates created
```

### Root Cause

The `_deactivate_older_predictions()` method in `predictions/shared/batch_staging_writer.py` (lines 405-459) runs immediately after MERGE consolidation. But the MERGE just inserted rows that are now in the streaming buffer, so the subsequent UPDATE cannot modify them.

```python
# batch_staging_writer.py line 717
# This runs immediately after MERGE - but rows are in streaming buffer!
deactivated = self._deactivate_older_predictions(game_date)
```

### Current Mitigation

The grading processor already handles duplicates via ROW_NUMBER deduplication (v5.0 fix from earlier in Session 28):

```sql
-- prediction_accuracy_processor.py uses this pattern
WITH deduped AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY player_lookup, game_date, system_id
    ORDER BY created_at DESC
  ) as rn
  FROM player_prop_predictions
  WHERE is_active = TRUE
)
SELECT * FROM deduped WHERE rn = 1
```

**Verified working:** 642 active predictions → 321 after dedup = 321 duplicates correctly filtered.

### Why This Matters

1. **Grading works correctly** - duplicates don't affect graded results
2. **Source table is messy** - duplicates accumulate over time
3. **Manual cleanup blocked** - can't run UPDATE to fix without waiting
4. **Automated cleanup broken** - the deactivation code exists but can't run

---

## Proposed Solutions for Next Session

### Option A: Delayed Cleanup Job (Recommended)

Create a Cloud Scheduler job that runs 2 hours after predictions, when streaming buffer has cleared.

```python
# New file: predictions/coordinator/delayed_dedup_cleanup.py

def cleanup_duplicate_predictions(game_date: str):
    """Run 2 hours after predictions to clean up duplicates."""
    query = """
    UPDATE nba_predictions.player_prop_predictions AS target
    SET is_active = FALSE
    WHERE EXISTS (
      SELECT 1 FROM nba_predictions.player_prop_predictions AS dupe
      WHERE dupe.player_lookup = target.player_lookup
        AND dupe.game_date = target.game_date
        AND dupe.system_id = target.system_id
        AND dupe.is_active = TRUE
        AND dupe.created_at > target.created_at
    )
    AND target.game_date = @game_date
    AND target.is_active = TRUE
    """
    # Run cleanup
```

**Pros:** Simple, reliable, doesn't change core prediction flow
**Cons:** Duplicates exist for 2 hours (but grading handles them anyway)

### Option B: Use Soft Deletes with Batch Loading

Instead of UPDATE to set `is_active = FALSE`, use a different pattern:

1. Load all predictions to a temp table
2. MERGE with deduplication logic that only keeps newest
3. This way dedup happens at MERGE time, not after

**Pros:** No streaming buffer issue
**Cons:** More complex MERGE logic, potential performance impact

### Option C: Accept Duplicates in Source

Since grading already handles duplicates:

1. Remove `_deactivate_older_predictions()` call entirely
2. Keep ROW_NUMBER dedup in all downstream queries
3. Run a weekly cleanup job (scheduled for low-traffic time)

**Pros:** Simplest change
**Cons:** Source table grows with duplicates, queries need dedup

### Option D: Pre-MERGE Deduplication

Modify the MERGE query to deduplicate BEFORE inserting:

```sql
MERGE INTO main_table T
USING (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY game_id, player_lookup, system_id
      ORDER BY created_at DESC
    ) as rn
    FROM staging_tables
  ) WHERE rn = 1
) S
ON T.game_id = S.game_id AND ...
WHEN MATCHED THEN UPDATE ...
WHEN NOT MATCHED THEN INSERT ...
```

**Pros:** Prevents duplicates at source
**Cons:** Only handles within-batch duplicates, not cross-batch

---

## Files to Review

| File | Relevance |
|------|-----------|
| `predictions/shared/batch_staging_writer.py` | Contains `_deactivate_older_predictions()` that fails |
| `predictions/coordinator/coordinator.py` | Calls `consolidate_batch()` |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Has working ROW_NUMBER dedup |

---

## Commits This Session

```
9340f493 feat: Add recency-weighted training and player trajectory features
```

---

## Quick Validation Commands

```bash
# Check current duplicate count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicates
FROM nba_predictions.player_prop_predictions AS t
WHERE EXISTS (
  SELECT 1 FROM nba_predictions.player_prop_predictions AS d
  WHERE d.player_lookup = t.player_lookup
    AND d.game_date = t.game_date
    AND d.system_id = t.system_id
    AND d.is_active = TRUE
    AND d.created_at > t.created_at
)
AND t.game_date >= '2026-01-09'
AND t.is_active = TRUE"

# Check if streaming buffer has cleared (try the UPDATE)
bq query --use_legacy_sql=false "
UPDATE nba_predictions.player_prop_predictions SET is_active = FALSE WHERE FALSE"
# If this succeeds (0 rows affected), buffer is clear

# Verify grading dedup works
bq query --use_legacy_sql=false "
WITH deduped AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY player_lookup, game_date, system_id
    ORDER BY created_at DESC
  ) as rn
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE() - 1 AND is_active = TRUE
)
SELECT
  COUNT(*) as total,
  COUNTIF(rn = 1) as unique,
  COUNTIF(rn > 1) as duplicates
FROM deduped"
```

---

## Recommended Next Steps

1. **Decide on solution** - Review Options A-D above
2. **Implement fix** - Probably Option A (delayed cleanup) is simplest
3. **Run recency-weighted experiment** - Test if it improves model performance
4. **Backfill trajectory features** - Populate historical data
5. **Train new model** - Combine recency weighting + trajectory features

---

*Session 28 Continuation Handoff - 2026-01-30*
