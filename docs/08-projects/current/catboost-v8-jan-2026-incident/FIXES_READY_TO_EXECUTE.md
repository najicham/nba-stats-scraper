# Fixes Ready to Execute
**Date**: 2026-01-16
**Status**: ✅ ROOT CAUSES IDENTIFIED - READY TO FIX
**Estimated Time**: 1-2 hours total

---

## 🎯 Quick Summary

We found EVERYTHING:

1. **player_daily_cache failures**: Two separate issues (permissions fixed, dependency failure needs backfill)
2. **50% confidence stuck**: Model not loading (missing env var + model files)

All fixes are ready to execute. Follow this guide step-by-step.

---

## ⚡ Quick Execution (Copy & Paste)

### Step 1: Backfill Missing Data (5-10 minutes)

```bash
cd /home/naji/code/nba-stats-scraper

# Backfill player_daily_cache for Jan 8
echo "📊 Backfilling player_daily_cache for Jan 8..."
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --date 2026-01-08

# Verify Jan 8
echo "✓ Verifying Jan 8 backfill..."
bq query --use_legacy_sql=false \
  "SELECT cache_date, COUNT(DISTINCT player_lookup) as players
   FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
   WHERE cache_date = '2026-01-08'
   GROUP BY cache_date"

# Backfill player_daily_cache for Jan 12
echo "📊 Backfilling player_daily_cache for Jan 12..."
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor \
  --date 2026-01-12

# Verify Jan 12
echo "✓ Verifying Jan 12 backfill..."
bq query --use_legacy_sql=false \
  "SELECT cache_date, COUNT(DISTINCT player_lookup) as players
   FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
   WHERE cache_date = '2026-01-12'
   GROUP BY cache_date"

# Regenerate ML Feature Store for Jan 8
echo "📊 Regenerating ML Feature Store for Jan 8..."
python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
  --date 2026-01-08

# Regenerate ML Feature Store for Jan 12
echo "📊 Regenerating ML Feature Store for Jan 12..."
python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor \
  --date 2026-01-12

echo "✅ Backfills complete!"
```

**Expected Output**:
- Jan 8: 50-200 players
- Jan 12: 50-200 players

---

### Step 2: Deploy CatBoost Model (5-10 minutes)

**Option A: GCS + Environment Variable** (Recommended)

```bash
# Check if model file exists locally
ls -lh /home/naji/code/nba-stats-scraper/models/catboost_v8_33features_20260108_211817.cbm

# If it exists, upload to GCS
echo "📤 Uploading model to GCS..."
gsutil cp /home/naji/code/nba-stats-scraper/models/catboost_v8_33features_20260108_211817.cbm \
  gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm

# Set environment variable in Cloud Run
echo "⚙️  Setting environment variable in Cloud Run..."
gcloud run services update prediction-worker \
  --region=us-west2 \
  --set-env-vars CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm \
  --project=nba-props-platform

echo "✅ Model deployment complete!"
echo "⏳ Wait for next prediction run to verify model loads..."
```

**Option B: Include in Docker Image** (If model file missing locally)

If model file doesn't exist locally, you'll need to:
1. Retrain the model OR find the original model file
2. Update Dockerfile to include models/ directory
3. Rebuild and redeploy Docker image

---

### Step 3: Verify Fixes (5 minutes)

```bash
# Wait 10-15 minutes after Step 2 for next prediction run, then:

echo "🔍 Verifying fixes..."

# Check confidence distribution (should NOT be all 50%)
bq query --use_legacy_sql=false \
  "SELECT
      ROUND(confidence_score * 100) as confidence_pct,
      COUNT(*) as picks,
      AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate
   FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
   WHERE system_id = 'catboost_v8'
     AND game_date >= CURRENT_DATE()
   GROUP BY confidence_pct
   ORDER BY confidence_pct DESC"

# Check Cloud Run logs for model loading
gcloud logging read \
  "resource.type=cloud_run_revision AND
   resource.labels.service_name=prediction-worker AND
   timestamp>=timestamp(\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\")\" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform | grep -i "catboost"

# Should see: "✓ CatBoost V8 model loaded successfully"

echo "✅ Verification complete!"
```

---

## 📋 Detailed Execution Plan

### Fix #1: Backfill player_daily_cache Data

**What**: Regenerate missing player_daily_cache records for Jan 8 and Jan 12

**Why**: These dates had 0 records, causing 36% of features to be missing

**Impact**:
- Restores historical feature quality
- Enables accurate historical analysis
- Fixes phase4_partial data source percentage

**Script Location**: Use commands in Step 1 above

**Verification**:
```sql
-- Should show 50-200 players for each date
SELECT cache_date, COUNT(*) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date IN ('2026-01-08', '2026-01-12')
GROUP BY cache_date;

-- Check feature quality improved
SELECT
    game_date,
    data_source,
    COUNT(*) as records,
    AVG(feature_quality_score) as avg_quality
FROM `nba-props-platform.ml_nba.ml_feature_store_v2`
WHERE game_date IN ('2026-01-08', '2026-01-12')
GROUP BY game_date, data_source;

-- Should see phase4_partial reappear, quality 90+
```

**Rollback**: Delete records if needed
```sql
DELETE FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date IN ('2026-01-08', '2026-01-12');
```

---

### Fix #2: Deploy CatBoost V8 Model

**What**: Upload model to GCS and configure Cloud Run to load it

**Why**: Model not loading causes all predictions to use 50% confidence fallback

**Impact**:
- Restores ML model predictions (vs simple weighted average)
- Restores confidence distribution (79-95% instead of stuck at 50%)
- Enables high-confidence picks and OVER/UNDER recommendations

**Prerequisites**:
1. Model file exists: `models/catboost_v8_33features_20260108_211817.cbm`
2. GCS bucket exists: `gs://nba-props-platform-models/`
3. Cloud Run service: `prediction-worker` in region `us-west2`

**Script Location**: Use commands in Step 2 above

**Verification**:
```bash
# Check GCS upload
gsutil ls gs://nba-props-platform-models/catboost/v8/

# Check Cloud Run env var
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.containers[0].env)"

# Check logs for model loading
gcloud logging read \
  "resource.type=cloud_run_revision AND
   resource.labels.service_name=prediction-worker" \
  --limit=100 \
  --format=json | grep -i "model"

# Should see: "CatBoost V8 model loaded successfully"
```

**Rollback**: Unset environment variable
```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --clear-env-vars CATBOOST_V8_MODEL_PATH \
  --project=nba-props-platform
```

---

### Fix #3: Add Monitoring Alerts

**What**: Configure alerts to catch these issues in the future

**Why**: Both issues were silent failures - no alerts triggered

**Impact**: Early detection (hours instead of days)

**Script Location**: See `scripts/deploy_monitoring_alerts.sh` (created below)

---

## 🚨 Troubleshooting

### Issue: Backfill fails with "No data found"

**Possible causes**:
1. Phase 3 data missing for those dates
2. Upstream dependency still failing

**Solution**:
```bash
# Check if Phase 3 data exists
bq query --use_legacy_sql=false \
  "SELECT COUNT(*)
   FROM \`nba-props-platform.nba_analytics.player_game_summary\`
   WHERE game_date BETWEEN '2026-01-07' AND '2026-01-13'"

# If no data, backfill Phase 3 first
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --date 2026-01-08
```

### Issue: Model file not found locally

**Solution**:
```bash
# Option 1: Find model file elsewhere
find /home/naji/code/nba-stats-scraper -name "catboost*.cbm" -type f

# Option 2: Check if it's in a different location
ls -la /home/naji/code/nba-stats-scraper/ml_models/nba/catboost/

# Option 3: Retrain model (if necessary)
# See: docs/08-projects/current/ml-model-v8-deployment/TRAINING-DATA-STRATEGY.md
```

### Issue: GCS bucket doesn't exist

**Solution**:
```bash
# Create bucket
gsutil mb -p nba-props-platform -c STANDARD -l us-west2 gs://nba-props-platform-models/

# Set permissions
gsutil iam ch serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com:objectViewer \
  gs://nba-props-platform-models
```

### Issue: Cloud Run update fails with permissions

**Solution**:
```bash
# Check if you have permissions
gcloud projects get-iam-policy nba-props-platform --flatten="bindings[].members" --filter="bindings.members:user:$(gcloud config get-value account)"

# If not, request Owner/Editor role or use service account with permissions
```

### Issue: Model loads but confidence still 50%

**Possible causes**:
1. Environment variable not picked up (restart needed)
2. Model file corrupted
3. Feature vector validation failing

**Solution**:
```bash
# Force Cloud Run revision
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --no-traffic  # Creates new revision without traffic

# Then promote new revision
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --to-latest

# Check logs again after next prediction run
```

---

## ⏱️ Timeline

| Task | Time | When |
|------|------|------|
| Backfill data | 5-10 min | Now |
| Deploy model | 5-10 min | Now |
| Verify fixes | 5 min | After next prediction run |
| Add monitoring | 30-60 min | Today/tomorrow |
| Monitor stability | 15 min/day | Next 3 days |

**Total**: ~1-2 hours today, then daily monitoring

---

## ✅ Success Checklist

### Backfills Complete
- [ ] player_daily_cache shows 50+ players for Jan 8
- [ ] player_daily_cache shows 50+ players for Jan 12
- [ ] ml_feature_store_v2 regenerated for both dates
- [ ] phase4_partial percentage ≥40% for those dates
- [ ] Feature quality ≥90 for those dates

### Model Deployed
- [ ] Model file uploaded to GCS
- [ ] Environment variable set in Cloud Run
- [ ] Logs show "Model loaded successfully"
- [ ] Confidence distribution shows variety (not just 50%)
- [ ] High-confidence picks appearing (85%+ confidence)

### Monitoring Configured
- [ ] Cloud Scheduler failure alerts
- [ ] player_daily_cache record count alerts
- [ ] Confidence clustering alerts
- [ ] Model load failure alerts
- [ ] Alerts tested with sample data

### System Healthy
- [ ] 3+ consecutive days of normal operation
- [ ] Win rate ≥53%
- [ ] Avg error ≤5.0 points
- [ ] Confidence distribution normal
- [ ] No new failures

---

## 📊 Expected Outcomes

**Before Fixes**:
- player_daily_cache: 0 records for Jan 8 & 12
- Confidence: 100% at 50%
- Feature quality: 77-84
- phase4_partial: 0%
- Model: Fallback mode (weighted average)

**After Fixes**:
- player_daily_cache: 50-200 records for Jan 8 & 12
- Confidence: Distribution 79-95%
- Feature quality: 90+
- phase4_partial: 40%+
- Model: CatBoost V8 loaded and predicting

---

## 🔗 Related Files

- Backfill scripts: This document
- Model deployment: This document
- Monitoring alerts: `scripts/deploy_monitoring_alerts.sh`
- Investigation findings: `investigation-findings/`
- Full documentation: `README.md`

---

**Ready to execute? Start with Step 1 above!** 🚀

**Last Updated**: 2026-01-16
**Status**: Ready for execution
