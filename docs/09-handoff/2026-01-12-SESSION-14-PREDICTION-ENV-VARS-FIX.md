# Session 14: Prediction Worker Environment Variables Fix

**Date:** January 12, 2026
**Session:** 14 - Debug & Fix Prediction Generation
**Status:** SUCCESS - All dates fixed and graded

---

## Executive Summary

### Root Cause Identified & Fixed
The prediction worker was missing critical environment variables, causing:
1. **Completion events lost** - Workers couldn't publish to `prediction-ready` topic
2. **CatBoost model not loading** - No model path configured

### Fixes Deployed
| Issue | Fix | Revision |
|-------|-----|----------|
| `PUBSUB_READY_TOPIC` missing | Added `prediction-ready-prod` | `prediction-worker-00029-pbg` |
| `CATBOOST_V8_MODEL_PATH` missing | Added GCS path | `prediction-worker-00030-cxv` |

---

## What Was Fixed

### 1. Pub/Sub Topic Configuration (CRITICAL)
**Problem:** Workers tried to publish completion events to `prediction-ready` (default), but the actual topic is `prediction-ready-prod`.

**Error in logs:**
```
google.api_core.exceptions.NotFound: 404 Resource not found (resource=prediction-ready)
```

**Impact:** 
- Staging writes succeeded
- Completion events failed to publish
- Coordinator never received completions
- Batch never marked complete
- Consolidation never triggered
- Predictions lost in staging tables

**Fix:**
```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="PUBSUB_READY_TOPIC=prediction-ready-prod"
```

### 2. CatBoost Model Path (HIGH)
**Problem:** `CATBOOST_V8_MODEL_PATH` environment variable was not set in Cloud Run.

**Fix:**
```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"
```

---

## Current Status

### Jan 8 Predictions: ✅ FIXED
- 42 predictions per system now in BigQuery
- All systems working (catboost_v8, ensemble_v1, moving_average, zone_matchup_v1, similarity_balanced_v1)

### Jan 11 Predictions: ⚠️ INVESTIGATION ONGOING
- Batch stuck at 83/121 completed (38 players not processing)
- 1995 predictions generated but in staging tables
- Consolidation blocked until batch completes
- **Anomaly:** Staging tables not visible in BigQuery despite successful write logs

---

## Resolution: Jan 11 Manual Consolidation

### Issue Found
- Staging tables WERE being written successfully (verified by querying them directly)
- `bq ls` command doesn't show tables starting with `_` by default
- Batch was stuck at 83/121, preventing automatic consolidation
- 38 players' Pub/Sub messages were stuck/lost (root cause unclear)

### Solution Applied
Ran manual consolidation locally:
```python
from google.cloud import bigquery
from predictions.worker.batch_staging_writer import BatchConsolidator

bq_client = bigquery.Client(project="nba-props-platform")
consolidator = BatchConsolidator(bq_client=bq_client, project_id="nba-props-platform")
result = consolidator.consolidate_batch("batch_2026-01-11_1768193582", "2026-01-11", cleanup=False)
# Result: 572 rows merged from 117 staging tables
```

### Result
- Jan 11: 121 predictions per system (catboost_v8, ensemble_v1, moving_average, zone_matchup_v1)
- similarity_balanced_v1: 103 predictions

---

## Grading Backfill Results

Ran grading for Jan 8-11:
```bash
PYTHONPATH=. python3 backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-08 --end-date 2026-01-11
```

| Date | Predictions Graded | MAE | Bias |
|------|-------------------|-----|------|
| Jan 8 | 132 | 6.81 | -2.46 |
| Jan 9 | 995 | 4.40 | -1.95 |
| Jan 10 | 905 | 5.27 | -1.09 |
| Jan 11 | 587 | 7.25 | +1.32 |
| **Total** | **2619** | - | - |

---

## Commands Used

### Check Prediction Worker Env Vars
```bash
gcloud run services describe prediction-worker --region=us-west2 --format='yaml(spec.template.spec.containers[0].env)'
```

### Trigger Predictions
```bash
COORD_URL=$(gcloud run services describe prediction-coordinator --region=us-west2 --format='value(status.url)')
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "${COORD_URL}/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{"game_date": "2026-01-11", "force": true}'
```

### Check Batch Status
```bash
curl -s "${COORD_URL}/status?batch_id=<batch_id>" -H "Authorization: Bearer ${TOKEN}"
```

### Check Prediction Counts
```sql
SELECT game_date, system_id, COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE('2026-01-08')
  AND is_active = TRUE
GROUP BY game_date, system_id
ORDER BY game_date, system_id
```

---

## Next Steps

1. **Jan 11 Investigation**
   - Check Pub/Sub dead letter queue for stuck messages
   - Investigate why staging tables aren't visible
   - Consider manual consolidation if tables exist

2. **Grading Backfill**
   - Once predictions confirmed, run grading for Jan 8-11
   
3. **Session 13B Pending**
   - Run player_lookup normalization backfill SQL
   - Regenerate upstream_player_game_context

---

## Key Files

| File | Purpose |
|------|---------|
| `predictions/worker/worker.py:136` | `PUBSUB_READY_TOPIC` default |
| `predictions/worker/prediction_systems/catboost_v8.py:86-116` | Model path loading |
| `predictions/worker/batch_staging_writer.py` | Staging table management |
| `predictions/coordinator/coordinator.py` | Batch orchestration |

---

*Last Updated: January 12, 2026 04:55 UTC*
