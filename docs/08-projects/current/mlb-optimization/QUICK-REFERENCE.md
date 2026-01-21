# MLB Optimization - Quick Reference

**Status**: ✅ Implementation Complete | ⏳ Ready for Deployment

---

## 🎯 What Was Done

Built 4 optimizations to improve MLB prediction system performance:

1. **Shared Feature Loader** - Load features once, share across all systems (-66% queries)
2. **Feature Coverage Tracking** - Monitor data quality, adjust confidence accordingly
3. **IL Cache Retry Logic** - Exponential backoff, safer failure handling
4. **Reduced Cache TTL** - 3hrs (from 6hrs) for fresher injury data

---

## 📊 Expected Impact

| What | Before | After | Improvement |
|------|--------|-------|-------------|
| BigQuery queries | 3/batch | 1/batch | **-66%** |
| Batch time (20 pitchers) | 15-20s | 8-12s | **-30-40%** |
| Systems in batch | 1 | 3 | **+200%** |
| Feature coverage | None | All preds | **+100%** |

---

## 🚀 Quick Deploy

### 1. Run Migration
```bash
cd /home/naji/code/nba-stats-scraper
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/migration_add_feature_coverage.sql
```

### 2. Deploy Worker
```bash
cd bin/predictions/deploy/mlb
./deploy_mlb_prediction_worker.sh
```

### 3. Test
```bash
# Health check
curl https://mlb-prediction-worker-756957797294.us-central1.run.app/health

# Batch test
curl -X POST https://mlb-prediction-worker.../predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-09-20", "pitcher_lookups": ["gerrit-cole"]}'
```

---

## 📁 Key Files

**Code**:
- `predictions/mlb/pitcher_loader.py` - Shared feature loader
- `predictions/mlb/worker.py` - Multi-system orchestration
- `predictions/mlb/base_predictor.py` - Coverage + IL cache
- `predictions/mlb/prediction_systems/*` - All updated

**Schema**:
- `schemas/bigquery/mlb_predictions/migration_add_feature_coverage.sql`

**Docs**:
- `docs/08-projects/current/mlb-optimization/IMPLEMENTATION-COMPLETE.md` - Full summary
- `docs/08-projects/current/mlb-optimization/DEPLOYMENT-CHECKLIST.md` - Step-by-step guide
- `docs/08-projects/current/mlb-optimization/QUICK-REFERENCE.md` - This file

**Testing**:
- `bin/mlb/test_optimizations.py` - Validation test script

---

## ✅ Verification

After deployment, check:

1. **Health**: `curl .../health` → `{"status": "healthy"}`
2. **Systems**: `curl .../` → Shows 3 active systems
3. **Predictions**: All include `feature_coverage_pct` field
4. **Logs**: "Loaded features for N pitchers" appears 1x per batch (not 3x)
5. **BigQuery**: Query predictions table for feature_coverage_pct

---

## 🔄 Rollback

If issues:
```bash
# Revert to previous Cloud Run revision
gcloud run services update-traffic mlb-prediction-worker \
  --to-revisions=PREVIOUS_REVISION=100 \
  --region=us-central1
```

---

## 📈 Monitor

**BigQuery Query**:
```sql
SELECT
    system_id,
    ROUND(AVG(feature_coverage_pct), 1) as avg_coverage,
    COUNT(*) as predictions
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= CURRENT_DATE()
GROUP BY system_id;
```

**Cloud Logs**:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=mlb-prediction-worker" \
  --limit=50
```

---

## 🎓 What to Remember

1. **Batch predictions now use all 3 systems** (v1_baseline, v1_6_rolling, ensemble_v1)
2. **Feature coverage** adjusts confidence (-5 to -25 points for low coverage)
3. **IL cache** is safer (retry logic, 3hr TTL, fail-safe behavior)
4. **All changes are backward compatible** - easy rollback if needed

---

**Ready to Deploy**: ✅ YES
**Risk Level**: 🟢 LOW
**Estimated Time**: 15-30 minutes
