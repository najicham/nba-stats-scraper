# Phase 5 Prediction Tables - Schema Reference

**Dataset:** `nba-props-platform.nba_predictions`  
**Purpose:** Multi-system prediction framework with ML integration  
**Update Schedule:** Daily (6-8 AM) + real-time when lines change

---

## 📋 Table Organization

### Core Prediction Tables
- `00_prediction_systems.sql` - Registry of all prediction systems
- `01_player_prop_predictions.sql` - All predictions (CRITICAL TABLE)
- `02_prediction_results.sql` - Actual outcomes vs predictions
- `03_system_daily_performance.sql` - Daily performance metrics

### Feature Storage (Array-Based Design)
- `04_ml_feature_store_v2.sql` - Flexible array features (25→47+)
- `05_feature_versions.sql` - Feature definitions
- `06_prediction_quality_log.sql` - Data quality tracking

### ML Model Management
- `07_ml_models.sql` - Trained ML model registry
- `08_ml_training_runs.sql` - Training history
- `09_ml_prediction_metadata.sql` - ML prediction details

### Configuration Management
- `10_weight_adjustment_log.sql` - Configuration change history

### Views
- `views/` directory - Helper views for analysis and monitoring

---

## 🚀 Quick Start

### Create All Tables
```bash
cd schemas/bigquery/predictions

# Deploy all tables
for file in [0-1][0-9]*.sql; do
  echo "Creating $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done

# Deploy views
for file in views/*.sql; do
  echo "Creating view $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done
```

### Verify Tables Created
```bash
bq ls nba-props-platform:nba_predictions
```

---

## 🎯 Session 2 Critical Tables

For implementing base predictor + moving average:

**Must create first:**
1. `00_prediction_systems.sql` ⭐
2. `01_player_prop_predictions.sql` ⭐
3. `04_ml_feature_store_v2.sql` ⭐
4. `05_feature_versions.sql` ⭐

**Can defer:**
- Tables 02, 03, 06-10 (production features)
- Views (nice to have, not critical)

---

## ⚠️ Important Notes

**Feature Store Design:**
- Using `ml_feature_store_v2` with ARRAY<FLOAT64>
- Start with 25 features (v1_baseline_25)
- Can expand to 47+ without schema changes

**Multi-System Architecture:**
- Multiple systems predict for same player/game
- Each system writes to `player_prop_predictions`
- "Champion" system designated for primary recommendations

---

## 📚 Related Documentation

- DEPLOYMENT_GUIDE.md - Deployment instructions
- Phase 5 Implementation Strategy
- Phase 5 Algorithm Specifications
