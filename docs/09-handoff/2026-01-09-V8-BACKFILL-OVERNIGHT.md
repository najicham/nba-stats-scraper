# V8 Backfill Overnight - January 9, 2026

**Started**: 11:43 PM PT
**ETA**: ~24 minutes (~12:07 AM PT)
**Status**: RUNNING

---

## What's Running

```bash
PYTHONPATH=. python ml/backfill_v8_predictions.py
```

Backfilling CatBoost V8 predictions for all historical games:
- **852 dates** (2021-11-02 to 2026-01-09)
- **~121K predictions**
- **Rate**: ~150 predictions/second

---

## Check Progress

```bash
# View latest log entries
tail -20 backfill_v8_output.log

# Check if still running
ps aux | grep backfill_v8

# View full log
cat backfill_v8.log
```

---

## When Complete

### 1. Verify Predictions Inserted

```sql
-- Count v8 predictions
SELECT COUNT(*) as v8_predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8';

-- Should be ~121K
```

### 2. (Optional) Delete Old xgboost_v1 Predictions

```sql
-- Check count first
SELECT COUNT(*) as mock_predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'xgboost_v1';

-- Delete if desired (can keep for historical record)
DELETE FROM nba_predictions.player_prop_predictions
WHERE system_id = 'xgboost_v1';
```

### 3. Re-run Phase 6 Export

Phase 6 exports predictions to the website. To update with v8:

```bash
# Export all predictions (may need to specify date range)
PYTHONPATH=. python predictions/phase6/export_predictions.py

# Or use the Phase 6 runner if available
PYTHONPATH=. python predictions/phase6_runner.py --backfill
```

Check existing Phase 6 scripts:
```bash
ls -la predictions/phase6*/
ls -la bin/exporters/
```

---

## Rollback (If Needed)

If backfill fails or needs to restart:

```bash
# Delete partial v8 predictions
bq query --use_legacy_sql=false "
DELETE FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND processing_decision_reason = 'backfill_v8'
"

# Restart from specific date
PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2024-01-01
```

---

## Summary of Tonight's Changes

1. **Pushed 7 commits** including v8 production deployment
2. **Created GCS bucket** `gs://nba-props-platform-ml-models/`
3. **Uploaded v8 model** to GCS
4. **Started backfill** of ~121K historical predictions

---

## Files Created/Modified

| File | Purpose |
|------|---------|
| `ml/backfill_v8_predictions.py` | Backfill script |
| `predictions/worker/worker.py` | Now uses CatBoostV8 |
| `docs/08-projects/current/ml-model-v8-deployment/PRODUCTION-DEPLOYMENT.md` | Deployment guide |
| `backfill_v8_output.log` | Backfill output log |
| `backfill_v8.log` | Detailed backfill log |
