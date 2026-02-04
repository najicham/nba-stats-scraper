# Model Management Troubleshooting

## Common Issues

### 1. Model Path Not Found (503 on /health/deep)

**Symptom:** prediction-worker `/health/deep` returns 503, logs show model file not found.

**Cause:** Environment variable points to non-existent GCS file.

**Diagnosis:**
```bash
# Check current env vars
gcloud run services describe prediction-worker --region=us-west2 | grep MODEL_PATH

# Validate paths exist
./bin/model-registry.sh validate
```

**Fix:**
```bash
# Find correct path
./bin/model-registry.sh production

# Update env var
gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://correct/path.cbm"
```

**Prevention:** The deploy script now validates GCS paths before deploying (Session 106).

---

### 2. Model Not Registered

**Symptom:** Model file exists in GCS but not in registry.

**Diagnosis:**
```bash
# List GCS files
gsutil ls gs://nba-props-platform-models/catboost/v9/

# List registry
./bin/model-registry.sh list
```

**Fix:** Add to registry:
```sql
INSERT INTO nba_predictions.model_registry (
  model_id, model_version, model_type, gcs_path, feature_count,
  training_start_date, training_end_date, status, is_production,
  created_at, created_by
) VALUES (
  'model_id_here', 'v9', 'catboost', 'gs://path/to/model.cbm', 33,
  DATE '2025-11-02', DATE '2026-02-01', 'active', FALSE,
  CURRENT_TIMESTAMP(), 'manual_fix'
);
```

---

### 3. Multiple Production Models

**Symptom:** More than one model marked `is_production = TRUE`.

**Diagnosis:**
```sql
SELECT model_id, model_version, is_production
FROM nba_predictions.model_registry
WHERE is_production = TRUE
```

**Fix:** Keep only the intended production model:
```sql
-- Mark all as non-production first
UPDATE nba_predictions.model_registry
SET is_production = FALSE
WHERE model_version = 'v9';

-- Then mark the correct one
UPDATE nba_predictions.model_registry
SET is_production = TRUE
WHERE model_id = 'correct_model_id';
```

---

### 4. Training Fails - Feature Count Mismatch

**Symptom:** Training script errors with shape mismatch.

**Cause:** Feature store has different feature count than expected.

**Diagnosis:**
```sql
SELECT ARRAY_LENGTH(features) as feature_count, COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-01'
GROUP BY 1
```

**Fix:** Ensure training script uses correct slice:
```python
# For 33 features
X = pd.DataFrame([row[:33] for row in df['features'].tolist()])

# For 37 features (with trajectory)
X = pd.DataFrame([row[:37] for row in df['features'].tolist()])
```

---

### 5. Model Performs Worse After Retrain

**Symptom:** Hit rate drops after deploying new model.

**Diagnosis:**
```bash
# Compare recent performance
bq query --use_legacy_sql=false "
SELECT game_date,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1"

# Check tier bias
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN actual_points >= 25 THEN 'stars' ELSE 'other' END as tier,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1"
```

**Fix:** Rollback to previous model:
```bash
# Get previous model
./bin/model-registry.sh list

# Revert
gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://path/to/previous.cbm"

# Update registry
bq query --use_legacy_sql=false "
UPDATE nba_predictions.model_registry
SET is_production = FALSE, status = 'rolled_back'
WHERE model_id = 'bad_model';

UPDATE nba_predictions.model_registry
SET is_production = TRUE
WHERE model_id = 'previous_model'"
```

---

### 6. GCS Upload Permission Denied

**Symptom:** `gsutil cp` fails with 403 error.

**Diagnosis:**
```bash
gcloud auth list
gsutil ls gs://nba-props-platform-models/
```

**Fix:**
```bash
# Re-authenticate
gcloud auth login
gcloud auth application-default login

# Or use service account
gcloud auth activate-service-account --key-file=key.json
```

---

### 7. Deployment Blocked by Validation

**Symptom:** `./bin/deploy-service.sh` refuses to deploy with model path error.

**This is expected behavior!** The validation prevents deploying with invalid model paths.

**Fix:**
1. Check the registry for correct paths:
   ```bash
   ./bin/model-registry.sh production
   ```

2. Update the env var to use correct path:
   ```bash
   gcloud run services update prediction-worker --region=us-west2 \
       --set-env-vars="CATBOOST_V8_MODEL_PATH=gs://correct/path.cbm"
   ```

3. Re-run deployment

---

## Quick Reference

| Issue | Quick Fix |
|-------|-----------|
| 503 on /health/deep | `./bin/model-registry.sh validate` then fix path |
| Model not in registry | Add via INSERT query |
| Wrong model in production | Update `is_production` flags |
| Feature mismatch | Check `ARRAY_LENGTH(features)` in feature store |
| Poor performance | Rollback to previous model |

## Getting Help

1. Check model registry: `./bin/model-registry.sh list`
2. Validate GCS paths: `./bin/model-registry.sh validate`
3. Review training logs in `ml_experiments` table
4. Check session handoffs in `docs/09-handoff/`
