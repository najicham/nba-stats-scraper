# Jan 9-28 Prediction Regeneration Plan

**Created:** 2026-02-01 (Session 64)
**Status:** Ready for Execution
**Priority:** HIGH

---

## Context

**Problem:** Jan 9-28 predictions were generated on Jan 30 07:41 UTC with broken code (before ea88e526 fix was deployed).

**Session 52 Update:** The ML feature store was already backfilled with fixed `usage_spike_score` values on Jan 31. The features are correct; only predictions need regeneration.

**Current State:**

| Metric | Value |
|--------|-------|
| Total predictions (Jan 9-28) | 8,972 |
| Broken batch (Jan 30 07:41) | 8,564 |
| After-fix batch (Jan 31) | 408 |
| Current hit rate | 50.4% |
| Expected hit rate | >58% |

---

## Execution Plan

### Step 1: Pre-Backfill Verification

```bash
# Verify prediction-worker has the fix deployed
./bin/verify-deployment-before-backfill.sh prediction-worker
```

### Step 2: Mark Broken Predictions as Superseded

```sql
-- Mark the Jan 30 07:41 batch as superseded
UPDATE nba_predictions.player_prop_predictions
SET
  superseded = TRUE,
  superseded_at = CURRENT_TIMESTAMP(),
  superseded_reason = 'Session 64: Regenerating with fixed code (ea88e526)',
  is_active = FALSE
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  AND created_at >= '2026-01-30 07:00:00'
  AND created_at < '2026-01-30 19:00:00';

-- Verify count
SELECT COUNT(*) as superseded_count
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  AND superseded = TRUE
  AND superseded_reason LIKE '%Session 64%';
-- Should be ~8,564
```

### Step 3: Run Prediction Backfill

```bash
# Dry run first
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28 \
  --dry-run

# Actual backfill
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28
```

### Step 4: Verify New Predictions Created

```sql
-- Check new predictions were created
SELECT
  game_date,
  COUNT(*) as predictions,
  MIN(created_at) as first_created,
  MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  AND created_at >= '2026-02-01'  -- Today
GROUP BY 1
ORDER BY 1;
```

### Step 5: Re-grade Predictions

The grading system needs to run to evaluate the new predictions against actual results.

```sql
-- Check if prediction_accuracy has entries for new predictions
-- (May need to wait for grading job to run)
SELECT
  COUNT(*) as new_predictions,
  COUNTIF(pa.prediction_correct IS NOT NULL) as graded
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON p.player_lookup = pa.player_lookup
  AND p.game_date = pa.game_date
  AND p.system_id = pa.system_id
WHERE p.system_id = 'catboost_v8'
  AND p.game_date >= '2026-01-09'
  AND p.game_date <= '2026-01-28'
  AND p.created_at >= '2026-02-01';
```

### Step 6: Verify Hit Rate Improvement

```sql
-- Compare old vs new predictions hit rate
-- This requires the grading to complete first

-- Old (superseded) predictions
SELECT
  'Old (superseded)' as batch,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  -- Filter for old batch (before regeneration)

UNION ALL

-- New predictions
SELECT
  'New (regenerated)' as batch,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-09'
  AND game_date <= '2026-01-28'
  -- Filter for new batch (after regeneration)
```

---

## Important Considerations

### Grading System

The `prediction_accuracy` table is populated by a grading job. After regenerating predictions:

1. New predictions will have new `prediction_id` values
2. The grading job needs to run to populate `prediction_accuracy` for new predictions
3. The old graded records in `prediction_accuracy` may still reference the superseded predictions

**Question:** Does the grading job use `player_lookup + game_date` or `prediction_id` to match?

Check grading logic before proceeding.

### Duplicate Prevention

The backfill script uses `insert_rows_json` which will insert new rows. To avoid duplicates:

1. Ensure old predictions are superseded BEFORE running backfill
2. New predictions will have new `prediction_id` values
3. Use `is_active = TRUE` filter when querying for current predictions

### Feature Store State

Session 52 already backfilled the feature store with fixed `usage_spike_score`. The regenerated predictions will use these corrected features.

---

## Expected Results

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Hit rate (Jan 9-28) | 50.4% | >58% | +8 pts |
| High-edge hit rate | ~50% | >60% | +10 pts |
| MAE | 5.8 pts | <5.0 pts | -15% |

---

## Rollback Plan

If regeneration makes things worse:

1. Mark new predictions as superseded
2. Restore old predictions' `is_active = TRUE`
3. Investigate what went wrong

```sql
-- Rollback if needed
UPDATE nba_predictions.player_prop_predictions
SET is_active = TRUE, superseded = FALSE
WHERE superseded_reason LIKE '%Session 64%';
```

---

## Checklist

- [ ] Verify deployment: `./bin/verify-deployment-before-backfill.sh prediction-worker`
- [ ] Mark old predictions superseded
- [ ] Run dry-run backfill
- [ ] Run actual backfill
- [ ] Verify new predictions created
- [ ] Wait for grading job to complete
- [ ] Verify hit rate improvement
- [ ] Document results

---

*Created: 2026-02-01 Session 64*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
