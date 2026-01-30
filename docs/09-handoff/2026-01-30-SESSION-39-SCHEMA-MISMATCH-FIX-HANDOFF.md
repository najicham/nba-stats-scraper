# Session 39 Handoff - Schema Mismatch Fix

**Date:** 2026-01-30
**Status:** Fix deployed, staging tables cleaned up

---

## Session Summary

Fixed the schema mismatch issue that was preventing consolidation of staging tables into the main `player_prop_predictions` table. The root cause was that the MERGE query used `SELECT *` and `INSERT ROW`, which failed when staging tables had fewer columns than the main table.

---

## Fix Applied

### Code Change: `predictions/shared/batch_staging_writer.py`

**Problem:** The `_build_merge_query()` method used:
- `SELECT * FROM staging_table` - selected all columns from staging
- `INSERT ROW` - tried to insert all columns into main table
- This failed because staging tables have 58 columns but main table has 72

**Solution:**
1. Added `_get_staging_columns()` method to detect staging table schema
2. Modified `_build_merge_query()` to:
   - Explicitly list staging columns in SELECT
   - Build UPDATE SET clause dynamically from staging columns
   - Use explicit `INSERT (columns) VALUES (values)` instead of `INSERT ROW`

**Key lines changed:** 313-340 (new method), 388-480 (updated method)

### Deployment

- Deployed `prediction-coordinator` service with fix
- New revision: `prediction-coordinator-00112-smd`

---

## Cleanup Performed

Deleted over 1,600 orphaned staging tables from previous batches:

| Date | Batch Count | Tables Deleted |
|------|-------------|----------------|
| 2026-01-23 | 5 batches | ~400 tables |
| 2026-01-25 | 3 batches | ~250 tables |
| 2026-01-27 | 1 batch | 2 tables |
| 2026-01-29 | 1 batch | 113 tables |
| 2026-01-30 | 9 batches | ~900 tables |

---

## Current State

### Predictions Table (2026-01-30)
```
911 predictions
141 unique players
```

### Staging Tables
- Active staging tables exist from current prediction batches (expected)
- Old orphaned tables cleaned up

### Missing Columns (14 total, not 9 as originally thought)
The staging tables are missing these columns compared to main table:
- calibrated_confidence_score, calibration_method
- early_season_flag
- feature_count, feature_data_source, feature_quality_score, feature_version
- invalidated_at, invalidation_reason
- prediction_error_code, raw_confidence_score
- teammate_opportunity_score, teammate_out_starters, teammate_usage_boost

These columns will be NULL for new predictions until the worker code is updated to include them.

---

## Remaining Issues

### 1. Completion Event Tracking (~50% loss)
Still unresolved from Session 38. Workers publish events, coordinator receives them (204), but only ~50% update Firestore.

**Next steps:**
- Investigate coordinator `/complete` handler (lines 1126-1215 in `coordinator.py`)
- Check `record_completion()` in `batch_state_manager.py` (lines 279-400)

### 2. Worker Schema Drift
Workers create staging tables with schema from main table, but worker code doesn't populate all 72 columns. This causes NULL values for 14 columns.

**Next steps:**
- Update prediction generation code to include missing columns
- Or accept NULL values as expected behavior

---

## Verification Commands

```bash
# Check staging tables count
bq ls nba_predictions 2>&1 | grep -c '_staging_'

# Check predictions for today
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()"

# Test MERGE query generation
python3 -c "
from google.cloud import bigquery
from predictions.shared.batch_staging_writer import BatchConsolidator
client = bigquery.Client(project='nba-props-platform')
consolidator = BatchConsolidator(client, 'nba-props-platform')
cols = consolidator._get_staging_columns('nba-props-platform.nba_predictions._staging_table_name')
print(f'Staging columns: {len(cols)}')"
```

---

## Files Modified

| File | Changes |
|------|---------|
| `predictions/shared/batch_staging_writer.py` | Added `_get_staging_columns()`, updated `_build_merge_query()` |

---

## Session Metrics

- Duration: ~30 minutes
- Code changes: 1 file, ~70 lines modified
- Tables deleted: ~1,600 orphaned staging tables
- Deployment: prediction-coordinator

---

*Session 39 complete. Schema mismatch fix deployed. Consolidation should now work for batches with fewer columns.*
