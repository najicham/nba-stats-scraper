# Prediction Backfill Analysis - Jan 23, 2026

## Issue Summary

When running a prediction backfill for Jan 21, 2026:
- Batch completed successfully (1480 predictions, 52 players, 100% success rate)
- Consolidation DID work: 432 rows were MERGED (updated existing rows)
- However, 156 players with placeholder lines were NOT processed

**Root cause**: Backfill can only process players who have betting lines available. For historical dates, betting lines aren't available after games end.

## Timeline

1. **13:57:24 UTC** - Batch `batch_2026-01-21_1769176603` started
2. **14:05:38 UTC** - Batch completed (is_complete=True in Firestore)
3. **~14:07 UTC** - Manual consolidation attempted, found "No staging tables"
4. **Result**: 0 rows merged to main table

## Evidence

Firestore batch state shows:
- `is_complete=True`
- `completed_players=52`
- `total_predictions=1480`
- No `is_consolidated` flag visible

BigQuery query shows no predictions with `created_at > 2026-01-23 13:50:00` for Jan 21.

## Root Cause (Suspected)

The consolidation should happen automatically when the batch completes, but it appears:
1. Staging tables were created and filled with data
2. Batch marked as complete in Firestore
3. Consolidation either didn't run or failed silently
4. Staging table cleanup ran (removing the tables without merging)

## Potential Issues

1. **Race condition**: Cleanup might run before consolidation
2. **Missing trigger**: Consolidation may not be triggered on batch completion
3. **Silent failure**: Consolidation error not logged or retried

## Workaround

Re-run the prediction batch for the same date. The system should generate new predictions.

## Files to Investigate

- `predictions/coordinator/coordinator.py` - Batch completion handling
- `predictions/coordinator/batch_consolidator.py` - Consolidation logic
- `predictions/coordinator/batch_state_manager.py` - Firestore state management

## Action Items

- [ ] Add logging to verify consolidation is called on batch completion
- [ ] Add `is_consolidated` flag to Firestore batch state
- [ ] Ensure staging cleanup only runs AFTER successful consolidation
- [ ] Consider adding consolidation retry mechanism
