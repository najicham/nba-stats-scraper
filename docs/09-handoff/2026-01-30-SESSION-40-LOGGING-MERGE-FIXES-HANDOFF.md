# Session 40 Handoff - Logging and MERGE Query Fixes

**Date:** 2026-01-30
**Status:** COMPLETE - Core issues fixed, auto-consolidation working

---

## Session Summary

Investigated and fixed coordinator logging and consolidation issues. Application logs now visible in Cloud Run, and MERGE query bugs that caused consolidation failures have been fixed.

---

## Fixes Applied

| Issue | Root Cause | Fix | Commit |
|-------|------------|-----|--------|
| Application logs not visible | Dockerfile not using gunicorn_config.py | Use `--config gunicorn_config.py` in CMD | fe5dba82 |
| MERGE "updated_at assigned twice" | updated_at in both update_columns and explicit SET | Add updated_at to special_columns | fe5dba82 |
| prediction_id getting overwritten | prediction_id included in UPDATE clause | Add prediction_id to special_columns | fe5dba82 |

---

## Root Causes Identified

### 1. Logging Not Visible
The coordinator Dockerfile was running gunicorn with inline command-line arguments:
```dockerfile
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  ...
  coordinator:app
```

This bypassed `gunicorn_config.py` which contains `logconfig_dict` that properly configures Python logging to route to stdout/stderr for Cloud Run.

**Fix:** Changed to `CMD exec gunicorn --config gunicorn_config.py coordinator:app`

### 2. MERGE Query Failures

Two separate bugs in `_build_merge_query()`:

**Bug A:** `updated_at` was being set twice:
- Once from the dynamic update_columns list: `updated_at = S.updated_at`
- Once explicitly: `updated_at = CURRENT_TIMESTAMP()`

**Bug B:** `prediction_id` was being updated on MATCHED rows, causing ID shuffling when staging had different prediction_ids for the same business key.

**Fix:** Added `updated_at` and `prediction_id` to `special_columns` set.

### 3. Batch Fragmentation
Multiple batches were created throughout the day due to scheduler retries and container restarts. Workers sent completions to whichever batch_id was in their original request, causing completion events to be spread across batches.

---

## Data Recovery

Jan 30 predictions were accidentally deleted during debugging. Recovered using BigQuery time travel:

```sql
CREATE TABLE _restore AS
SELECT * FROM player_prop_predictions
FOR SYSTEM_TIME AS OF TIMESTAMP('2026-01-30 20:30:00 UTC')
WHERE game_date = '2026-01-30'
```

After cleanup and deduplication: **966 predictions for 141 players** (consistent with other dates).

---

## Current State

| Metric | Value |
|--------|-------|
| Jan 30 predictions | 966 |
| Jan 30 players | 141 |
| Coordinator revision | prediction-coordinator-00116-xmz |
| Commit deployed | fe5dba82 |
| Logging working | Yes |
| Consolidation working | Yes (verified in logs) |

---

## Verification

After fixes, coordinator logs now show complete flow:
```
coordinator - INFO - Completion: stephencurry (batch=..., predictions=30)
batch_state_manager - INFO - Recorded completion for stephencurry
coordinator - INFO - Recorded: stephencurry -> batch_complete=True
coordinator - INFO - Batch ... complete! Triggering consolidation...
batch_staging_writer - INFO - Acquiring consolidation lock...
```

---

## Remaining Issues

### 1. Batch Fragmentation
When multiple batches are created for the same day, completions get scattered. Consider:
- Adding batch_id deduplication at scheduler level
- Implementing batch recovery/merging logic
- Using a single "daily batch" pattern instead of timestamp-based IDs

### 2. Schema Mismatch (Lower Priority)
Staging tables have 63 columns, target has 72. The 9 missing error tracking fields are handled by the MERGE using explicit column lists, but could be added to worker output.

---

## Next Session Checklist

1. [ ] Monitor auto-consolidation for tomorrow's predictions
2. [ ] Review batch creation logic to reduce fragmentation
3. [ ] Consider adding scheduled consolidation as backup
4. [ ] Update worker to include error tracking fields (optional)

---

## Key Learnings

1. **Always verify config files are loaded** - The gunicorn_config.py existed but wasn't being used
2. **MERGE queries need careful column handling** - Exclude columns that are set explicitly or should be preserved
3. **BigQuery time travel is valuable** - Can recover from accidental deletes up to 7 days
4. **Test consolidation with visible logging first** - The logging fix was essential for debugging

---

## Commands for Next Session

```bash
# Check predictions for a date
bq query --use_legacy_sql=false "
SELECT COUNT(*), COUNT(DISTINCT player_lookup)
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
"

# Check coordinator logs
gcloud logging read 'resource.labels.service_name="prediction-coordinator"' --limit=50

# Manual consolidation trigger
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/check-stalled-batches \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"stall_threshold_minutes": 5, "min_completion_pct": 90}'
```
