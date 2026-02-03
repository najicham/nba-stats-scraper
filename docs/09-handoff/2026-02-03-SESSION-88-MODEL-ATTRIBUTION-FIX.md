# Session 88 Continuation - Model Attribution NULL Bug Fix

**Date:** 2026-02-03
**Duration:** ~45 min
**Status:** Fix Deployed, Awaiting Verification

## Session Summary

Fixed the root cause of model attribution fields being NULL in BigQuery. The bug was in `predictions/worker/worker.py` where nested metadata was accessed incorrectly.

## Root Cause

The CatBoost model returns prediction results with this structure:
```python
result = {
    'predicted_points': 25.5,
    'metadata': {
        'model_file_name': 'catboost_v9_feb_02_retrain.cbm',
        'model_training_start_date': '2025-11-01',
        # ... other attribution fields
    }
}
```

When storing predictions (line 1390), the full result is stored:
```python
system_predictions[CATBOOST_SYSTEM_ID] = {
    'metadata': result  # Full result stored here
}
```

But when extracting (line 1812), the code incorrectly accessed:
```python
# WRONG - looks for result['model_file_name']
metadata = prediction['metadata']  # This is the full result dict
record['model_file_name'] = metadata.get('model_file_name')  # Not found!

# CORRECT - must access result['metadata']['model_file_name']
catboost_result = prediction['metadata']
catboost_meta = catboost_result.get('metadata', {})  # Get nested metadata
record['model_file_name'] = catboost_meta.get('model_file_name')  # Found!
```

## Fix Applied

**File:** `predictions/worker/worker.py` (lines 1811-1834)

**Commit:** `4ada201f` - "fix: Access nested metadata for catboost model attribution"

**Change:**
```python
# Before (lines 1812-1829):
metadata = prediction['metadata']
record.update({
    'model_file_name': metadata.get('model_file_name'),  # Always None
    ...
})

# After:
catboost_result = prediction['metadata']
catboost_meta = catboost_result.get('metadata', {})
record.update({
    'model_file_name': catboost_meta.get('model_file_name'),  # Now works!
    ...
})
```

## Deployment Status

| Item | Value |
|------|-------|
| Commit | `4ada201f` |
| Revision | `prediction-worker-00087-8nb` |
| Deployed | 2026-02-03 ~03:00 UTC |
| Status | Live |

## Verification

**Run after next prediction run (10:00 UTC / 5 AM ET):**

```bash
bq query --use_legacy_sql=false "
SELECT model_file_name, model_training_start_date, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE created_at >= TIMESTAMP('2026-02-03 10:00:00')
  AND system_id = 'catboost_v9'
GROUP BY 1, 2"
```

**Expected:**
- `model_file_name` = `catboost_v9_feb_02_retrain.cbm`
- `model_training_start_date` = `2025-11-01`

**If still NULL:** Check if the catboost_v9.py `_get_metadata()` method is being called. May need to add logging.

## Daily Validation Notes

Validation was started but hit context limit. Findings that need investigation:

1. **Phase 3 incomplete:** 3/5 processors showed complete
2. **Low hit rates:** 22-39% observed (needs edge filtering verification)
3. **Minutes coverage:** 59.2% (below 90% threshold)
4. **RED signal day:** Heavy UNDER skew detected

These may be normal (e.g., Phase 3 mode-aware, edge filtering) but warrant fresh investigation.

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Lines 1811-1834 - Fixed nested metadata access |

## Next Session Checklist

1. **Verify model attribution fix** (after 10:00 UTC)
   - Run verification query above
   - If populated: proceed to Phase 2 (model attribution exporters)
   - If still NULL: add debug logging

2. **Complete daily validation** (fresh investigation)
   - Check Phase 3 mode-aware status
   - Verify edge filtering is applied correctly
   - Investigate low hit rate readings

3. **Deploy Phase 6 exporters** (from Session 90)
   - Commit ~20 untracked files
   - Deploy phase5_to_phase6 orchestrator
   - Update Cloud Schedulers

## Key Learning

When debugging NULL fields in BigQuery:
1. Trace the data flow from source (model output) to sink (BigQuery write)
2. Log intermediate values at each transformation step
3. Check for nested structures that may require multiple levels of access

---

**Session Complete**
