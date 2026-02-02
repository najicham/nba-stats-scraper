# Model Attribution Tracking System

**Session**: 84
**Date**: February 2, 2026
**Status**: ✅ Code Complete, Ready for Deployment

---

## Quick Summary

Adds comprehensive model attribution tracking to NBA predictions, enabling us to track which exact model file generated which predictions.

**Problem**: Could not determine which model version produced the 75.9% historical hit rate reported in Session 83.

**Solution**: Every prediction now includes:
- Exact model file name (`catboost_v9_feb_02_retrain.cbm`)
- Training period (`2025-11-02` to `2026-01-31`)
- Expected performance (MAE: 4.12, HR: 74.6%)
- Model training timestamp

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `DESIGN.md` | Design document with architecture, data model, and decisions |
| `IMPLEMENTATION.md` | Implementation guide with deployment steps and verification |
| `README.md` | This file - quick overview and navigation |

---

## Quick Start

### 1. Review Design

Read `DESIGN.md` to understand:
- Why we need model attribution
- What fields are being added
- How the system works

### 2. Deploy Changes

```bash
# 1. Commit changes
git add .
git commit -m "feat: Add model attribution tracking (Session 84)"

# 2. Deploy prediction-worker
./bin/deploy-service.sh prediction-worker

# 3. Wait for next prediction run (2:30 AM, 7 AM, or 11:30 AM ET)

# 4. Verify it works
./bin/verify-model-attribution.sh
```

### 3. Read Implementation Details

See `IMPLEMENTATION.md` for:
- Complete deployment checklist
- Verification queries
- Troubleshooting guide

---

## Key Achievements

### Before Session 84

```
❌ No model file tracking
❌ Can't distinguish OLD vs NEW model performance
❌ No audit trail for model versions
❌ Historical analysis impossible
```

**Example Problem**:
- Session 83: "v9_top5 has 75.9% historical hit rate"
- **Question**: Which model version? OLD (MAE 5.08) or NEW (MAE 4.12)?
- **Answer**: Unknown - no tracking!

### After Session 84

```
✅ Every prediction has model file name
✅ Training period and expected performance stored
✅ Full audit trail for compliance
✅ Historical analysis possible
```

**Example Solution**:
```sql
SELECT
  model_file_name,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
GROUP BY model_file_name;
```

**Output**:
```
catboost_v9_feb_02_retrain.cbm  | 1,245 | 75.9%  ← NEW model
catboost_v9_2026_02.cbm         |   832 | 50.8%  ← OLD model
```

Now we KNOW which model produced which results!

---

## Schema Changes

### player_prop_predictions Table

Added 6 new fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `model_file_name` | STRING | Exact model file name | `catboost_v9_feb_02_retrain.cbm` |
| `model_training_start_date` | DATE | Start of training window | `2025-11-02` |
| `model_training_end_date` | DATE | End of training window | `2026-01-31` |
| `model_expected_mae` | FLOAT64 | Expected MAE from validation | `4.12` |
| `model_expected_hit_rate` | FLOAT64 | Expected high-edge hit rate | `74.6` |
| `model_trained_at` | TIMESTAMP | When model was trained | `2026-02-02T10:15:00Z` |

### prediction_execution_log Table

Added 5 new fields for batch-level tracking (future use).

---

## Code Changes

### 1. catboost_v9.py

Enhanced to emit model metadata:

```python
# Track model file name during loading
self._model_file_name = Path(model_path).name

# Include in prediction metadata
result['metadata']['model_file_name'] = self._model_file_name
result['metadata']['model_training_start_date'] = "2025-11-02"
result['metadata']['model_training_end_date'] = "2026-01-31"
result['metadata']['model_expected_mae'] = 4.12
result['metadata']['model_expected_hit_rate'] = 74.6
```

### 2. worker.py

Extract and store model metadata:

```python
# In format_prediction_for_bigquery()
record.update({
    'model_file_name': metadata.get('model_file_name'),
    'model_training_start_date': metadata.get('model_training_start_date'),
    'model_training_end_date': metadata.get('model_training_end_date'),
    'model_expected_mae': metadata.get('model_expected_mae'),
    'model_expected_hit_rate': metadata.get('model_expected_hit_rate'),
    'model_trained_at': metadata.get('model_trained_at'),
})
```

---

## Verification

### Run Verification Script

```bash
./bin/verify-model-attribution.sh
```

**Expected Output (Success)**:
```
Step 1: Checking model attribution coverage...
game_date   | system_id   | total | with_file_name | coverage_pct
2026-02-03  | catboost_v9 |   142 |            142 |        100.0

✅ PASS: Model attribution is working correctly
```

**Expected Output (Failure)**:
```
Step 1: Checking model attribution coverage...
game_date   | system_id   | total | with_file_name | coverage_pct
2026-02-03  | catboost_v9 |   142 |              0 |          0.0

❌ FAIL: Model attribution is not working
```

### Manual Verification Queries

See `IMPLEMENTATION.md` for detailed verification queries.

---

## Use Cases

### 1. Historical Analysis

**Question**: Which model version produced the 75.9% hit rate?

```sql
SELECT
  model_file_name,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE subset_id = 'v9_top5'
  AND game_date BETWEEN '2026-01-10' AND '2026-02-01'
GROUP BY model_file_name;
```

### 2. Model A/B Testing

**Question**: Which model performs better - OLD or NEW?

```sql
SELECT
  CASE
    WHEN model_file_name LIKE '%feb_02%' THEN 'NEW'
    WHEN model_file_name LIKE '%2026_02%' THEN 'OLD'
  END as model_version,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
  AND ABS(predicted_points - line_value) >= 5  -- High-edge
GROUP BY model_version;
```

### 3. Deployment Audit

**Question**: When was each model deployed?

```sql
SELECT
  model_file_name,
  MIN(game_date) as first_used,
  MAX(game_date) as last_used,
  COUNT(DISTINCT game_date) as days_active
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
GROUP BY model_file_name
ORDER BY first_used DESC;
```

### 4. Performance Validation

**Question**: Does actual performance match expected performance?

```sql
SELECT
  model_file_name,
  model_expected_mae,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as actual_mae,
  ROUND(AVG(ABS(predicted_points - actual_points)) - model_expected_mae, 2) as mae_diff
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy pa
  ON p.prediction_id = pa.prediction_id
WHERE p.system_id = 'catboost_v9'
  AND p.model_file_name IS NOT NULL
GROUP BY model_file_name, model_expected_mae;
```

---

## Future Enhancements

### Phase 2 (Future Sessions)

1. **Model Registry Service**
   - Central registry of all models with metadata
   - Automatic versioning and deployment tracking
   - Model lineage and feature importance tracking

2. **Automated Backfill**
   - Backfill historical predictions with model metadata
   - Use deployment timestamps and git history

3. **Notification Enhancement**
   - Include model attribution in daily picks notifications
   - Show model performance in Slack/Email/SMS

4. **Dashboard Integration**
   - Model version distribution charts
   - Performance comparison by model
   - Drift detection and alerts

---

## Troubleshooting

### Coverage < 100%

**Symptom**: Some predictions missing model attribution

**Cause**: Old worker instances or deployment not complete

**Fix**:
```bash
./bin/check-deployment-drift.sh --verbose
./bin/deploy-service.sh prediction-worker
```

### model_file_name is NULL

**Symptom**: All predictions have NULL model_file_name

**Cause**: Code not deployed or model loading failed

**Fix**: Check worker logs and redeploy

See `IMPLEMENTATION.md` for detailed troubleshooting.

---

## Related Sessions

- **Session 82**: Deployed NEW V9 model (`catboost_v9_feb_02_retrain.cbm`)
- **Session 83**: Discovered we couldn't track which model produced 75.9% HR
- **Session 84**: Implemented model attribution tracking (this session)

---

## References

- Design: `DESIGN.md`
- Implementation: `IMPLEMENTATION.md`
- Verification: `bin/verify-model-attribution.sh`
- Schema: `schemas/bigquery/predictions/migrations/2026-02-02-model-attribution.sql`

---

**Last Updated**: February 2, 2026
**Status**: Ready for Deployment
**Next**: Deploy prediction-worker and verify
