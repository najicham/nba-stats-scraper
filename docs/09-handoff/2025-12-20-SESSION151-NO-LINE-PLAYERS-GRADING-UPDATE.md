# Session 151: No-Line Players Grading Update

**Date**: 2025-12-20
**Status**: Code complete, backfill needed

---

## Summary

Added line source tracking to the grading pipeline so we can analyze prediction accuracy separately for:
- Players with real betting lines (`ACTUAL_PROP`)
- Players with estimated lines based on season average (`ESTIMATED_AVG`)

---

## Changes Made

### 1. BigQuery Schema
Added 3 columns to `nba_predictions.prediction_accuracy`:
```sql
has_prop_line BOOLEAN        -- Was there a real betting line?
line_source STRING           -- 'ACTUAL_PROP' or 'ESTIMATED_AVG'
estimated_line_value NUMERIC -- The estimated line used (if applicable)
```

### 2. Grading Processor
Updated `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`:
- Query now pulls `has_prop_line`, `line_source`, `estimated_line_value` from predictions
- Output includes these fields in graded results
- Defaults to `TRUE`/`ACTUAL_PROP` for backwards compatibility

### 3. Tests
Added 6 new test cases in `tests/processors/grading/prediction_accuracy/test_unit.py`:
- All 71 tests passing

---

## Action Required: Re-run Grading Backfill

The new columns are empty for all historical data (315,447 rows).

### Command to Run

```bash
cd /home/naji/code/nba-stats-scraper

python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-06 \
  --end-date 2025-12-19
```

### What This Does
- Re-grades all 404 game dates
- Populates `has_prop_line`, `line_source`, `estimated_line_value` columns
- Historical data will default to `TRUE`/`ACTUAL_PROP` (correct, since we only predicted lined players before v3.2)
- Idempotent - safe to re-run
- Estimated time: 30-60 minutes

### Verify After Completion

```sql
SELECT
  has_prop_line,
  line_source,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY has_prop_line, line_source
```

Expected result: All rows should have `has_prop_line=true` and `line_source='ACTUAL_PROP'` (historical data). Future grading runs will show `ESTIMATED_AVG` for no-line players.

---

## Context: Why This Matters

We generate predictions for ALL players, including those without betting lines:
- Use season PPG as a synthetic "line" to predict against
- Track that the line was estimated, not real
- Grade on point accuracy (MAE) not O/U correctness

This builds historical accuracy data for players BEFORE they get betting lines. When a bench player "graduates" to having lines, we already know how well our model predicts them.

---

## Related Files

- Grading processor: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Backfill job: `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`
- Tests: `tests/processors/grading/prediction_accuracy/test_unit.py`
- Frontend guide: `/home/naji/code/props-web/docs/07-prompts/no-line-players-backend-guide.md`

---

## Future: Analysis Queries

Once backfill completes, you can run:

```sql
-- Compare accuracy by line source
SELECT
  line_source,
  AVG(absolute_error) as mae,
  COUNTIF(within_3_points)/COUNT(*) as within_3_rate
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY line_source
```

---

*End of handoff*
