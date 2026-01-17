# MLB Multi-Model Architecture - Deployment Runbook

**Version**: 2.0.0
**Date**: 2026-01-17
**Estimated Time**: 2-3 hours (including validation)

---

## Prerequisites

- [ ] GCP access with permissions for:
  - BigQuery (dataset admin)
  - Cloud Run (admin)
  - Cloud Storage (viewer for model files)
- [ ] `gcloud` CLI configured
  - [ ] Run: `gcloud auth login`
  - [ ] Run: `gcloud config set project nba-props-platform`
- [ ] `bq` CLI available
- [ ] Python 3.11+ installed (for validation script)
- [ ] Git repository up to date on `main` branch

---

## Pre-Deployment Checklist

### 1. Code Verification

- [ ] All new files exist:
  ```bash
  ls predictions/mlb/base_predictor.py
  ls predictions/mlb/prediction_systems/v1_baseline_predictor.py
  ls predictions/mlb/prediction_systems/v1_6_rolling_predictor.py
  ls predictions/mlb/prediction_systems/ensemble_v1.py
  ls predictions/mlb/worker.py
  ls schemas/bigquery/mlb_predictions/migration_add_system_id.sql
  ls schemas/bigquery/mlb_predictions/multi_system_views.sql
  ls scripts/deploy_mlb_multi_model.sh
  ls scripts/validate_mlb_multi_model.py
  ```

- [ ] Python syntax validation:
  ```bash
  python3 -m py_compile predictions/mlb/base_predictor.py
  python3 -m py_compile predictions/mlb/prediction_systems/*.py
  python3 -m py_compile predictions/mlb/worker.py
  ```

- [ ] Run unit tests (optional but recommended):
  ```bash
  pytest tests/mlb/ -v
  ```

### 2. Model Files Verification

- [ ] Verify V1 model exists in GCS:
  ```bash
  gsutil ls gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
  gsutil ls gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456_metadata.json
  ```

- [ ] Verify V1.6 model exists in GCS:
  ```bash
  gsutil ls gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
  gsutil ls gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json
  ```

### 3. Backup Current State

- [ ] Document current service configuration:
  ```bash
  gcloud run services describe mlb-prediction-worker \
    --region us-central1 \
    --format=yaml > /tmp/mlb-worker-backup-$(date +%Y%m%d).yaml
  ```

- [ ] Note current model version:
  ```bash
  curl https://mlb-prediction-worker-XXXXX.run.app/ | jq '.model'
  ```

---

## Phase 1: BigQuery Migration

**Goal**: Add `system_id` column and create monitoring views

### Step 1: Add system_id Column

- [ ] Run migration SQL:
  ```bash
  bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/migration_add_system_id.sql
  ```

- [ ] Verify column added:
  ```bash
  bq show --schema --format=prettyjson nba-props-platform:mlb_predictions.pitcher_strikeouts | grep system_id
  ```

  Expected output: Should see `system_id` field definition

- [ ] Verify backfill worked (check last 7 days):
  ```bash
  bq query --use_legacy_sql=false "
  SELECT
    system_id,
    COUNT(*) as count,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
  FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY system_id"
  ```

  Expected: All rows should have `system_id` populated (either `v1_baseline` or `v1_6_rolling`)

### Step 2: Create Monitoring Views

- [ ] Create views:
  ```bash
  bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/multi_system_views.sql
  ```

- [ ] Verify views created:
  ```bash
  bq ls mlb_predictions | grep -E "todays_picks|system_comparison|system_performance|daily_coverage|system_agreement"
  ```

  Expected: All 5 views should be listed

- [ ] Test a view:
  ```bash
  bq query --use_legacy_sql=false "SELECT * FROM \`nba-props-platform.mlb_predictions.daily_coverage\` LIMIT 5"
  ```

**✅ Checkpoint**: BigQuery migration complete. All views created.

---

## Phase 2: Deploy V1 Baseline Only (Safe Mode)

**Goal**: Validate new architecture with single system before enabling all

### Step 1: Deploy with V1 Only

- [ ] Make deployment script executable:
  ```bash
  chmod +x scripts/deploy_mlb_multi_model.sh
  ```

- [ ] Deploy Phase 1:
  ```bash
  ./scripts/deploy_mlb_multi_model.sh phase1
  ```

  When prompted "Deploy to production? (yes/no):", type `yes`

- [ ] Wait for deployment to complete (~2-3 minutes)

### Step 2: Validate Deployment

- [ ] Get service URL from deployment output
- [ ] Save URL for next steps:
  ```bash
  export SERVICE_URL=https://mlb-prediction-worker-XXXXX.run.app
  ```

- [ ] Run validation script:
  ```bash
  chmod +x scripts/validate_mlb_multi_model.py
  python3 scripts/validate_mlb_multi_model.py --service-url $SERVICE_URL
  ```

  Expected: All checks should PASS (or warnings for no predictions yet if off-season)

- [ ] Manual health check:
  ```bash
  curl $SERVICE_URL/ | jq .
  ```

  Expected output should include:
  ```json
  {
    "version": "2.0.0",
    "architecture": "multi-model",
    "active_systems": ["v1_baseline"],
    ...
  }
  ```

### Step 3: Test Predictions

- [ ] Test batch prediction endpoint (use future date):
  ```bash
  curl -X POST $SERVICE_URL/predict-batch \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2026-04-01", "write_to_bigquery": false}' | jq .
  ```

  Expected: Should return predictions with `"systems_used": ["v1_baseline"]`

### Step 4: Monitor for 24 Hours

- [ ] Check Cloud Run logs:
  ```bash
  gcloud logging tail \
    --project=nba-props-platform \
    --resource-type=cloud_run_revision \
    --filter='resource.labels.service_name=mlb-prediction-worker' \
    --format='table(timestamp,textPayload)' \
    --limit=50
  ```

- [ ] Look for errors:
  ```bash
  gcloud logging read \
    "resource.type=cloud_run_revision AND severity>=ERROR AND textPayload=~'mlb'" \
    --limit=50 \
    --format=json
  ```

**✅ Checkpoint**: V1 Baseline running successfully for 24 hours.

**🛑 STOP HERE** if any errors occur. Troubleshoot before proceeding.

---

## Phase 3: Enable All Systems

**Goal**: Deploy V1 + V1.6 + Ensemble

### Step 1: Deploy All Systems

- [ ] Deploy Phase 3:
  ```bash
  ./scripts/deploy_mlb_multi_model.sh phase3
  ```

  When prompted, type `yes`

- [ ] Wait for deployment (~2-3 minutes)

### Step 2: Validate All Systems Active

- [ ] Run validation:
  ```bash
  python3 scripts/validate_mlb_multi_model.py --service-url $SERVICE_URL
  ```

  Expected: All checks PASS

- [ ] Verify 3 systems active:
  ```bash
  curl $SERVICE_URL/ | jq '.active_systems'
  ```

  Expected: `["v1_baseline", "v1_6_rolling", "ensemble_v1"]`

- [ ] Verify all systems have metadata:
  ```bash
  curl $SERVICE_URL/ | jq '.systems'
  ```

  Expected: 3 system entries with MAE and feature counts

### Step 3: Test Multi-System Predictions

- [ ] Test batch predictions:
  ```bash
  curl -X POST $SERVICE_URL/predict-batch \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2026-04-01", "write_to_bigquery": false}' | jq .
  ```

  Expected:
  - `"systems_used": ["v1_baseline", "v1_6_rolling", "ensemble_v1"]`
  - `predictions_count` should be 3x number of pitchers

### Step 4: Wait for Next Game Day

**⏳ WAIT**: Wait for the next MLB game day when predictions will actually run in production.

### Step 5: Verify Daily Coverage (After Predictions Run)

- [ ] Check daily coverage the morning after predictions run:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT *
  FROM \`nba-props-platform.mlb_predictions.daily_coverage\`
  WHERE game_date = CURRENT_DATE()"
  ```

  Expected output:
  ```
  unique_pitchers: 30-50
  systems_per_date: 3
  systems_used: v1_baseline,v1_6_rolling,ensemble_v1
  v1_count: 30-50
  v1_6_count: 30-50
  ensemble_count: 30-50
  min_systems_per_pitcher: 3
  max_systems_per_pitcher: 3
  ```

  **🚨 CRITICAL**: `min_systems_per_pitcher` and `max_systems_per_pitcher` must both equal 3!

- [ ] If coverage is incomplete, check logs:
  ```bash
  gcloud logging read \
    "resource.type=cloud_run_revision AND textPayload=~'Prediction failed'" \
    --limit=20
  ```

### Step 6: Verify System Comparison

- [ ] Check system comparison view:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT
    pitcher_lookup,
    v1_prediction,
    v1_6_prediction,
    ensemble_prediction,
    agreement_level
  FROM \`nba-props-platform.mlb_predictions.system_comparison\`
  LIMIT 10"
  ```

  Expected: Should see all 3 predictions for each pitcher

**✅ Checkpoint**: All 3 systems running successfully with complete coverage.

---

## Phase 4: Post-Deployment Validation

**Goal**: Confirm system is stable and performant

### Immediate Validation (Day 1)

- [ ] All systems running:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT system_id, COUNT(*)
  FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
  WHERE game_date = CURRENT_DATE()
  GROUP BY system_id"
  ```

  Expected: 3 rows with equal counts

- [ ] System agreement check:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT *
  FROM \`nba-props-platform.mlb_predictions.system_agreement\`
  WHERE game_date = CURRENT_DATE()"
  ```

  Expected: `strong_agreement + moderate_agreement` should be > 70%

- [ ] No critical errors:
  ```bash
  gcloud logging read \
    "resource.type=cloud_run_revision AND severity=ERROR" \
    --limit=10 \
    --format=json
  ```

  Expected: No errors (or only minor warnings)

### Weekly Validation (Day 7)

- [ ] System performance comparison:
  ```bash
  bq query --use_legacy_sql=false "
  SELECT *
  FROM \`nba-props-platform.mlb_predictions.system_performance\`"
  ```

  Monitor:
  - Total predictions per system (should be equal)
  - MAE per system (ensemble should be ≤ best individual system)
  - Recommendation accuracy (ensemble should be ≥ V1.6)

- [ ] Check for circuit breaker events:
  ```bash
  gcloud logging read \
    "textPayload=~'circuit breaker' OR textPayload=~'System.*failed'" \
    --limit=50
  ```

  Expected: Zero or very few circuit breaker activations

### Monthly Validation (Day 30)

- [ ] Make `system_id` NOT NULL (after 30-day dual-write period):
  ```bash
  bq query --use_legacy_sql=false "
  ALTER TABLE \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
  ALTER COLUMN system_id SET NOT NULL"
  ```

- [ ] Update documentation to reflect production status

**✅ Checkpoint**: System stable in production.

---

## Rollback Procedures

### Quick Rollback (V1 Only)

If issues detected, revert to single system:

```bash
./scripts/deploy_mlb_multi_model.sh rollback
```

This keeps the code changes but runs only V1 baseline.

### Emergency Rollback (Previous Code)

If critical issues, revert to previous code:

```bash
# 1. Revert worker.py
git checkout HEAD~1 predictions/mlb/worker.py

# 2. Redeploy
gcloud run deploy mlb-prediction-worker \
  --source . \
  --region us-central1

# 3. Verify
curl https://mlb-prediction-worker-XXXXX.run.app/ | jq .
```

**Note**: BigQuery schema changes are safe to keep even after rollback.

---

## Monitoring Dashboards

### Daily Checks

Run these queries daily for the first week:

1. **System Coverage**:
   ```bash
   bq query --use_legacy_sql=false "SELECT * FROM \`mlb_predictions.daily_coverage\` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
   ```

2. **System Performance**:
   ```bash
   bq query --use_legacy_sql=false "SELECT * FROM \`mlb_predictions.system_performance\`"
   ```

3. **Today's Picks** (Ensemble):
   ```bash
   bq query --use_legacy_sql=false "SELECT pitcher_lookup, predicted_strikeouts, recommendation, confidence FROM \`mlb_predictions.todays_picks\` LIMIT 20"
   ```

### Alerts to Configure

Set up alerts for:

1. **Critical**:
   - All systems failing (zero predictions)
   - API 500 errors > 5%
   - System coverage < 3 systems per pitcher

2. **Warning**:
   - Single system circuit breaker open
   - System agreement < 80%

---

## Success Criteria

After 30 days, verify:

- ✅ All 3 systems running daily
- ✅ System coverage: 100% of pitchers have 3 predictions
- ✅ Ensemble MAE ≤ best individual system MAE
- ✅ Ensemble win rate ≥ V1.6 baseline (82.3%)
- ✅ Zero production incidents
- ✅ Zero API breaking changes

---

## Troubleshooting

### Issue: system_id is NULL in predictions

**Solution**: Re-run migration:
```bash
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/migration_add_system_id.sql
```

### Issue: Views not found

**Solution**: Create views:
```bash
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/multi_system_views.sql
```

### Issue: Only 1 or 2 systems running

**Solution**: Check environment variables:
```bash
gcloud run services describe mlb-prediction-worker --region us-central1 --format=yaml | grep MLB_ACTIVE_SYSTEMS
```

Should be: `MLB_ACTIVE_SYSTEMS: v1_baseline,v1_6_rolling,ensemble_v1`

### Issue: Predictions failing

**Solution**: Check logs for specific errors:
```bash
gcloud logging tail --resource-type=cloud_run_revision --filter='severity>=ERROR'
```

### Issue: Ensemble predictions missing

**Solution**: Verify both V1 and V1.6 are active (ensemble requires both)

---

## Contact & Support

- **Implementation Documentation**: `predictions/mlb/MULTI_MODEL_IMPLEMENTATION.md`
- **Code Documentation**: `predictions/mlb/README.md`
- **Session Handoff**: `docs/handoffs/session_80_mlb_multi_model_implementation.md`

---

**End of Runbook**

**Last Updated**: 2026-01-17
**Version**: 2.0.0
