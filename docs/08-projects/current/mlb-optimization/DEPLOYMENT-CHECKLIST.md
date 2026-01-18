# MLB Optimization Deployment Checklist

**Project**: Option A - MLB Performance Optimization
**Date**: 2026-01-17
**Status**: Ready for Deployment

---

## Pre-Deployment

### ✅ Code Changes Complete
- [x] Shared feature loader implemented
- [x] Feature coverage tracking added
- [x] IL cache retry logic implemented
- [x] Cache TTL reduced to 3 hours
- [x] All prediction systems updated
- [x] BigQuery migration script created
- [x] Documentation complete

### ⏳ Optional: Local Testing

```bash
cd /home/naji/code/nba-stats-scraper

# Make test script executable
chmod +x bin/mlb/test_optimizations.py

# Run all validation tests
python bin/mlb/test_optimizations.py --test all

# Expected output:
# ✅ ALL TESTS PASSED - Ready for deployment!
```

**Tests Performed**:
- [ ] Feature loader loads features for multiple pitchers
- [ ] Feature coverage calculation works correctly
- [ ] Multi-system predictions generate results
- [ ] IL cache hits and refreshes properly

---

## Deployment Steps

### Step 1: Run BigQuery Migration ⏳

```bash
cd /home/naji/code/nba-stats-scraper

# Add feature_coverage_pct column to pitcher_strikeouts table
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/migration_add_feature_coverage.sql
```

**Verify**:
```bash
# Check column was added
bq show --schema --format=prettyjson nba-props-platform:mlb_predictions.pitcher_strikeouts | grep feature_coverage_pct

# Should show:
# {
#   "name": "feature_coverage_pct",
#   "type": "FLOAT",
#   "description": "Percentage of expected features with non-null values (0-100)"
# }
```

**Checklist**:
- [ ] Migration executed successfully
- [ ] feature_coverage_pct column added
- [ ] feature_coverage_monitoring view created
- [ ] No errors in BigQuery

---

### Step 2: Deploy Optimized Worker ⏳

```bash
cd /home/naji/code/nba-stats-scraper/bin/predictions/deploy/mlb

# Deploy to Cloud Run
./deploy_mlb_prediction_worker.sh

# Or if script doesn't exist, use:
gcloud run deploy mlb-prediction-worker \
  --source=. \
  --region=us-central1 \
  --platform=managed \
  --project=nba-props-platform
```

**Expected Output**:
```
✓ Deploying... Done.
✓ Creating Revision... Done.
✓ Routing traffic... Done.
Service [mlb-prediction-worker] revision [mlb-prediction-worker-00XXX-XXX] has been deployed
```

**Checklist**:
- [ ] Deployment successful
- [ ] New revision created
- [ ] Traffic routed to new revision
- [ ] No build errors

---

### Step 3: Validate Deployment ⏳

**Test 1: Health Check**
```bash
curl https://mlb-prediction-worker-756957797294.us-central1.run.app/health

# Expected: {"status": "healthy"}
```

**Test 2: Service Info**
```bash
curl https://mlb-prediction-worker-756957797294.us-central1.run.app/

# Expected: JSON with active_systems: ["v1_baseline", "v1_6_rolling", "ensemble_v1"]
```

**Test 3: Batch Prediction**
```bash
curl -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict-batch \
  -H "Content-Type: application/json" \
  -d '{
    "game_date": "2025-09-20",
    "pitcher_lookups": ["gerrit-cole", "shohei-ohtani"]
  }'
```

**Expected Response**:
```json
{
  "predictions": [
    {
      "pitcher_lookup": "gerrit-cole",
      "system_id": "v1_baseline",
      "predicted_strikeouts": 6.8,
      "confidence": 72.5,
      "feature_coverage_pct": 94.3,
      ...
    },
    {
      "pitcher_lookup": "gerrit-cole",
      "system_id": "v1_6_rolling",
      "predicted_strikeouts": 7.1,
      "confidence": 75.2,
      "feature_coverage_pct": 97.1,
      ...
    },
    {
      "pitcher_lookup": "gerrit-cole",
      "system_id": "ensemble_v1",
      "predicted_strikeouts": 7.0,
      "confidence": 74.1,
      "feature_coverage_pct": 94.3,
      ...
    },
    ... (3 predictions per pitcher)
  ],
  "summary": {
    "total_predictions": 6,
    "systems_used": 3
  }
}
```

**Validation Checklist**:
- [ ] Health endpoint returns healthy
- [ ] Service info shows 3 active systems
- [ ] Batch predictions return results for all systems
- [ ] All predictions include feature_coverage_pct field
- [ ] Response time is reasonable (should be faster than before)

---

### Step 4: Monitor Performance ⏳

**Check Cloud Run Logs**
```bash
# View recent logs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=mlb-prediction-worker" \
  --limit=100 \
  --format=json

# Or use Cloud Console:
# https://console.cloud.google.com/run/detail/us-central1/mlb-prediction-worker/logs
```

**Look For**:
- [x] "Loaded features for N pitchers" - Should appear 1x per batch (not 3x)
- [x] "Generated M predictions from K systems" - K should be 3
- [x] Batch completion times - Should be 30-40% faster
- [x] No errors or warnings about feature loading
- [x] Feature coverage warnings for low-quality data (expected)

**Query BigQuery for Feature Coverage**
```sql
-- Check feature coverage distribution
SELECT
    system_id,
    ROUND(AVG(feature_coverage_pct), 1) as avg_coverage,
    ROUND(MIN(feature_coverage_pct), 1) as min_coverage,
    ROUND(MAX(feature_coverage_pct), 1) as max_coverage,
    COUNTIF(feature_coverage_pct < 80.0) as low_coverage_count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= CURRENT_DATE()
  AND feature_coverage_pct IS NOT NULL
GROUP BY system_id;
```

**Monitoring Checklist**:
- [ ] Logs show single feature load per batch
- [ ] All 3 systems generating predictions
- [ ] Feature coverage populated for new predictions
- [ ] No increase in error rates
- [ ] Batch latency reduced (if measurable)

---

## Performance Validation

### Benchmark Comparison

**Before Optimization** (baseline):
```bash
# Measure baseline performance (if old version available)
time curl -X POST https://mlb-prediction-worker.../predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-09-20"}'

# Expected: ~15-20 seconds for 20 pitchers
```

**After Optimization**:
```bash
# Measure optimized performance
time curl -X POST https://mlb-prediction-worker.../predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-09-20"}'

# Expected: ~8-12 seconds for 20 pitchers (30-40% improvement)
```

**Performance Checklist**:
- [ ] Batch time measured
- [ ] Improvement documented
- [ ] No degradation in accuracy
- [ ] All systems producing results

---

## Success Criteria

| Metric | Target | Status |
|--------|--------|--------|
| BigQuery queries per batch | 1 (from 3) | ⏳ |
| Batch time (20 pitchers) | 8-12s (from 15-20s) | ⏳ |
| Active systems in batch mode | 3 (from 1) | ⏳ |
| Feature coverage tracking | 100% of predictions | ⏳ |
| IL cache TTL | 3 hours (from 6) | ✅ |
| Zero production incidents | No errors | ⏳ |

---

## Rollback Plan

**If Issues Occur**:

```bash
# Option 1: Revert to previous Cloud Run revision
gcloud run services update-traffic mlb-prediction-worker \
  --to-revisions=PREVIOUS_REVISION=100 \
  --region=us-central1 \
  --project=nba-props-platform

# Option 2: Redeploy from previous git commit
git log --oneline -10  # Find previous commit
git checkout <previous-commit-hash>
cd bin/predictions/deploy/mlb
./deploy_mlb_prediction_worker.sh
git checkout main  # Return to main branch
```

**Rollback Checklist**:
- [ ] Previous revision identified
- [ ] Traffic routed to previous revision
- [ ] System functioning normally
- [ ] Issue documented for investigation

---

## Post-Deployment

### Documentation Updates

- [ ] Update main handoff document with deployment results
- [ ] Document actual performance improvements
- [ ] Note any issues encountered
- [ ] Record success metrics

### Monitoring Setup

**Create Alerts** (optional):
```sql
-- Low feature coverage alert (>20% of predictions with <80% coverage)
SELECT
    COUNT(*) as total_predictions,
    COUNTIF(feature_coverage_pct < 80.0) as low_coverage_count,
    ROUND(100.0 * COUNTIF(feature_coverage_pct < 80.0) / COUNT(*), 1) as low_coverage_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date = CURRENT_DATE()
  AND feature_coverage_pct IS NOT NULL
HAVING low_coverage_rate > 20.0;
```

**Monitoring Checklist**:
- [ ] Feature coverage dashboard created (optional)
- [ ] Performance metrics tracked
- [ ] Error rates monitored
- [ ] Success metrics documented

---

## Final Sign-Off

### Deployment Complete ✅

- [ ] BigQuery migration successful
- [ ] Worker deployed to Cloud Run
- [ ] All validation tests passed
- [ ] Performance improvements confirmed
- [ ] Documentation updated
- [ ] No production incidents

### Next Steps

1. Monitor performance over next 24-48 hours
2. Collect performance metrics for final report
3. Consider additional optimizations if needed
4. Plan for next iteration (Options B, C, or D)

---

**Deployment Status**: ⏳ **READY TO DEPLOY**
**Risk Level**: 🟢 **LOW** (Backward compatible, easy rollback)
**Estimated Deployment Time**: 15-30 minutes
