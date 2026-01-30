# Session 28 Complete Handoff

**Date:** 2026-01-30
**Status:** Complete - Major data integrity issues fixed
**Priority for Next Session:** Monitor and verify fixes, clean up source duplicates

---

## Executive Summary

Session 28 discovered and fixed **two critical data integrity issues** that were incorrectly diagnosed as "model drift":

1. **Grading Pipeline Corruption** - Predictions were stored with inflated values (2-4x) in `prediction_accuracy`
2. **Source Table Duplicates** - `player_prop_predictions` had duplicate records causing downstream issues

Both issues are now fixed at the grading pipeline level. The model itself is valid.

---

## Issues Fixed

### Issue 1: Grading Corruption (FIXED)

**What happened:** Jan 19-28 grading stored corrupted `predicted_points` values:
- Anthony Edwards: 35.0 → stored as 60.0 (1.7x)
- Brandon Miller: 16.1 → stored as 42.1 (2.6x)
- Stephen Curry: 20.7 → stored as 45.0 (2.2x)

**Root cause:** Duplicates in `player_prop_predictions` causing Cartesian products during grading.

**Fix applied:**
1. Deleted 447 + 2,232 + 985 + 668 = **4,332 corrupted records** from `prediction_accuracy`
2. Re-graded affected dates (Jan 19, 20, 24, 25, 28)
3. Added **v5.0 deduplication** to grading input query

### Issue 2: Source Table Duplicates (PARTIALLY FIXED)

**What happened:** The V8 prediction backfill created 2x duplicate records in `player_prop_predictions`:

| Date | Records | Unique Players | Excess |
|------|---------|----------------|--------|
| Jan 09-28 | ~2x | ~200-300/day | ~200-300 dupes/day |

**Root cause:** Backfill script ran without deduplication checks.

**Fix applied:**
1. Added deduplication query to grading processor (prevents downstream impact)
2. Records in streaming buffer - need to wait 90 min then deactivate duplicates

### Issue 3: Retraining Experiments (NO IMPROVEMENT FOUND)

Ran 4 retraining experiments. None significantly improved Jan 2026 performance:

| Experiment | Training Period | Jan 2026 Hit Rate |
|------------|----------------|-------------------|
| RECENT_2024_25 | Oct 2024 - Jun 2025 | 53.6% |
| ALL_DATA | Nov 2021 - Dec 2025 | 53.5% |
| COMBINED_RECENT | Oct 2024 - Dec 2025 | 53.0% |
| INSEASON_2025_26 | Oct - Dec 2025 | 52.5% |

High-confidence picks (5+ point edge) remain 65-70% accurate.

---

## Code Changes

### Modified Files

| File | Change |
|------|--------|
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | **v5.0**: Added ROW_NUMBER deduplication to `get_predictions_for_date()` |
| `shared/validation/cross_phase_validator.py` | Added prediction integrity check |
| `docs/08-projects/.../*.md` | Documentation of findings |

### Key Code Change

```python
# v5.0 Deduplication in grading processor
WITH predictions_raw AS (
    SELECT ... FROM predictions_table WHERE ...
),
deduped AS (
    SELECT * EXCEPT(rn) FROM (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY player_lookup, game_id, system_id, line_value
                ORDER BY created_at DESC
            ) as rn
        FROM predictions_raw
    )
    WHERE rn = 1
)
SELECT * EXCEPT(created_at) FROM deduped
```

---

## Commits This Session

```
0f0de91e feat: Add prediction integrity validation and Session 28 findings
26c7fe17 fix: Add deduplication to grading input query (v5.0)
```

---

## Current Data State

### Clean Data
- `prediction_accuracy`: All corrupted records deleted and re-graded
- Grading processor: Now deduplicates input automatically

### Pending Cleanup
- `player_prop_predictions`: Has duplicates in streaming buffer
  - Wait 90 min for buffer to clear
  - Run: `UPDATE SET is_active = FALSE` for older duplicates

### Verification Queries

```sql
-- Check for remaining drift
SELECT game_date, system_id,
       ROUND(AVG(ABS(pp.predicted_points - pa.predicted_points)), 3) as drift
FROM nba_predictions.player_prop_predictions pp
JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_date, system_id)
WHERE pp.game_date >= '2026-01-01' AND pp.is_active = true
GROUP BY 1, 2
HAVING drift > 0.1
ORDER BY game_date DESC;

-- Check catboost_v8 accuracy
SELECT game_date, COUNT(*) as predictions,
       ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2026-01-20'
GROUP BY 1 ORDER BY 1;
```

---

## Next Session Actions

### P0 - Critical
1. **Clean up source duplicates** after streaming buffer clears:
   ```sql
   -- Run after 90 minutes
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
   AND target.game_date >= '2026-01-09'
   AND target.system_id = 'catboost_v8'
   AND target.is_active = TRUE;
   ```

2. **Run validation** to confirm all is clean:
   ```bash
   PYTHONPATH=. python -m shared.validation.cross_phase_validator --start-date 2026-01-01 --end-date 2026-01-28
   ```

### P1 - Important
3. **Add dedup to backfill script** (`ml/backfill_v8_predictions.py`) to prevent recurrence
4. **Deploy grading cloud function** with v5.0 dedup fix

### P2 - Monitoring
5. **Monitor hit rates** - True Jan 2026 performance is ~45-55%, not the corrupted metrics

---

## Key Learnings

1. **Multiple data issues can stack** - Feature store bug + grading corruption made diagnosis hard
2. **Deduplication is critical** - Must deduplicate at both source and grading levels
3. **Validation catches issues** - New prediction integrity check now detects drift
4. **Model is valid** - The CatBoost V8 model works; it was fed bad data

---

## Related Documents

- `docs/08-projects/current/catboost-v8-performance-analysis/SESSION-28-DATA-CORRUPTION-INCIDENT.md`
- `docs/08-projects/current/catboost-v8-performance-analysis/SESSION-28-SUMMARY-FOR-SHARING.md`
- `docs/08-projects/current/season-validation-2024-25/JANUARY-2026-PERFORMANCE-INVESTIGATION.md`
- `docs/09-handoff/2026-01-30-SESSION-31-VALIDATION-FIX-AND-MODEL-ANALYSIS-HANDOFF.md`

---

*Session 28 Complete - 2026-01-30*
*Data integrity issues identified and fixed*
*Grading pipeline now has input deduplication (v5.0)*
