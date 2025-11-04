# Phase 5 Schema Deployment Guide

**Purpose:** Deploy all Phase 5 prediction tables to BigQuery

---

## ✅ Files Required

You should have these 11 SQL files:
- 00_prediction_systems.sql ⭐
- 01_player_prop_predictions.sql ⭐
- 02_prediction_results.sql
- 03_system_daily_performance.sql
- 04_ml_feature_store_v2.sql ⭐
- 05_feature_versions.sql ⭐
- 06_prediction_quality_log.sql
- 07_ml_models.sql
- 08_ml_training_runs.sql
- 09_ml_prediction_metadata.sql
- 10_weight_adjustment_log.sql

Plus 5 view files in `views/` subdirectory.

---

## 🚀 Quick Deployment

### Option 1: Deploy Everything (15 minutes)
```bash
cd ~/code/nba-stats-scraper/schemas/bigquery/predictions

# Deploy all tables
for file in [0-1][0-9]*.sql; do
  echo "Creating $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done

# Deploy all views
for file in views/*.sql; do
  echo "Creating view $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done
```

### Option 2: Session 2 Minimal (2 minutes)

Only deploy what you need to start coding:
```bash
cd ~/code/nba-stats-scraper/schemas/bigquery/predictions

bq query --project_id=nba-props-platform --use_legacy_sql=false < 00_prediction_systems.sql
bq query --project_id=nba-props-platform --use_legacy_sql=false < 01_player_prop_predictions.sql
bq query --project_id=nba-props-platform --use_legacy_sql=false < 04_ml_feature_store_v2.sql
bq query --project_id=nba-props-platform --use_legacy_sql=false < 05_feature_versions.sql
```

---

## 🔍 Verify Deployment
```bash
# List all tables
bq ls nba-props-platform:nba_predictions

# Check 5 systems were inserted
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.prediction_systems`'

# Check feature version
bq query --use_legacy_sql=false \
  'SELECT feature_version, feature_count, active 
   FROM `nba-props-platform.nba_predictions.feature_versions`'
```

---

## ✅ Post-Deployment Checklist

- [ ] All tables created
- [ ] Views created (optional)
- [ ] 5 systems in prediction_systems
- [ ] v1_baseline_25 in feature_versions
- [ ] Ready to start Session 2!

---

## ⏭️ Next Steps

Start Session 2: Base Predictor + Moving Average System! 🚀
```

---

## 📂 Complete File Structure
```
schemas/bigquery/predictions/
├── 00_prediction_systems.sql          ✅ You have
├── 01_player_prop_predictions.sql     ✅ You have
├── 02_prediction_results.sql          ✅ You have
├── 03_system_daily_performance.sql    ✅ You have
├── 04_ml_feature_store_v2.sql         ✅ You have
├── 05_feature_versions.sql            ✅ You have
├── 06_prediction_quality_log.sql      ✅ You have
├── 07_ml_models.sql                   ✅ You have
├── 08_ml_training_runs.sql            ✅ You have
├── 09_ml_prediction_metadata.sql      ✅ You have
├── 10_weight_adjustment_log.sql       ✅ You have
├── README.md                          📥 Copy from above
├── DEPLOYMENT_GUIDE.md                📥 Copy from above
└── views/                             📁 Create directory
    ├── v_todays_predictions_summary.sql        📥 Copy from above
    ├── v_system_comparison_today.sql           📥 Copy from above
    ├── v_system_agreement.sql                  📥 Copy from above
    ├── v_system_accuracy_leaderboard.sql       📥 Copy from above
    └── v_system_performance_comparison.sql     📥 Copy from above
