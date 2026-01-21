# NBA ML Models - Training Scripts

This directory contains production ML model training scripts for NBA player predictions.

## XGBoost V1 Production Model

### Overview

`train_xgboost_v1.py` trains the production XGBoost V1 model that replaces the mock_xgboost_model currently used in predictions.

**Features:**
- 33 features from ml_feature_store_v2 (v2_33features)
- Chronological train/validation split (80/20)
- Early stopping on validation MAE
- Model versioning with timestamps
- Optional GCS upload for production deployment

**Target Performance:**
- Training MAE: ≤ 4.0 points
- Validation MAE: ≤ 4.5 points
- Better than mock model (~4.8 MAE)

---

## 📋 SESSION 88 - CURRENT STATUS (2026-01-17)

### What We're Doing Now: Option D (Phase 5 Deployment)

**Context:**
- Just completed Option A (MLB Optimization) - deployed to production
- Starting Option D: Phase 5 Full Deployment
- Following fast-track approach: Train initial model → Deploy → Improve as backfill completes

### Current Plan: Two-Phase Training Strategy

#### Phase 1: Initial Model (NOW - Next 2 hours)
**Status:** 🟡 In Progress

Train initial XGBoost V1 model using available 2021 data:

```bash
# Train on 2021 data (~60 dates available from completed backfill)
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2021-12-31 \
  --output-path gs://nba-scraped-data/ml-models/
```

**Expected Results:**
- Training samples: ~1,500-2,000 games (limited but usable)
- Validation MAE: ~4.5-5.0 points (acceptable for initial deployment)
- Model size: ~10-30 MB
- Purpose: Test infrastructure, validate deployment pipeline
- **Status: NOT production-quality but DEPLOYMENT-ready**

**Why this approach:**
- ✅ Gets Phase 5 infrastructure deployed immediately
- ✅ Validates end-to-end pipeline while backfill continues
- ✅ Model works even if overfitted (we'll replace it soon)
- ✅ No waiting 7-9 hours for backfill to complete

#### Phase 2: Production Model (When backfill completes ~9 hours)
**Status:** ⏳ Pending Backfill

Retrain with full historical data:

```bash
# Retrain with complete 2021-2025 data (~850+ dates)
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2026-01-17 \
  --upload-gcs
```

**Expected Results:**
- Training samples: ~76,000+ games
- Validation MAE: ~3.8-4.2 points (production quality)
- Better generalization, less overfitting
- **Status: PRODUCTION-READY**

### Backfill Status

**Completed:**
- ✅ 2021: 100% (59 dates) - Phase 4 complete

**In Progress (Running in background):**
- 🟡 2022: Step 1 ~79% complete (169/213 dates)
- 🟡 2023: Step 1 ~83% complete (168/203 dates)
- 🟡 2024: Step 1 ~81% complete (170/210 dates)
- 🟡 2025: Step 1 ~84% complete (182/217 dates)

**Estimated Completion:**
- Step 1 (TDZA + PSZA): ~30 minutes
- Step 2 (PCF): ~3-4 hours
- Step 3 (MLFS): ~3-4 hours
- **Total: ~7-9 hours from now**

### Usage

#### Initial Model Training (Use 2021 Data)

```bash
# From project root
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2021-12-31
```

This will:
1. Query BigQuery for 2021 data from ml_feature_store_v2
2. Train XGBoost V1 model
3. Save model to `models/xgboost_v1_33features_YYYYMMDD_HHMMSS.json`
4. Save metadata to `models/xgboost_v1_33features_YYYYMMDD_HHMMSS_metadata.json`
5. Upload to GCS: `gs://nba-scraped-data/ml-models/`

#### Production Model Training (When Backfill Complete)

```bash
# Train with full historical data
PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py \
  --start-date 2021-11-01 \
  --end-date 2026-01-17 \
  --upload-gcs
```

Expected improvement with full data:
- Training samples: ~1,500 → ~76,000+ games (50x more data!)
- Validation MAE: ~4.5-5.0 → ~3.8-4.2 (15-20% improvement)
- Better generalization, less overfitting
- Competitive with CatBoost V8 (3.4 MAE)

### Features (33 Total)

#### Base Features (25)
From `ml_feature_store_v2`:
- Recent performance: points_avg_last_5, points_avg_last_10, points_avg_season
- Volatility: points_std_last_10
- Workload: games_in_last_7_days, fatigue_score
- Matchup: shot_zone_mismatch_score, opponent_def_rating, opponent_pace
- Context: is_home, back_to_back, playoff_game
- Shot distribution: pct_paint, pct_mid_range, pct_three, pct_free_throw
- Team context: team_pace, team_off_rating, team_win_pct
- Composite: pace_score, usage_spike_score, rest_advantage, injury_risk, recent_trend, minutes_change

#### Vegas Features (4)
- vegas_points_line: Market consensus
- vegas_opening_line: Opening line
- vegas_line_move: Line movement
- has_vegas_line: Coverage indicator

#### Opponent History (2)
- avg_points_vs_opponent: Historical performance vs this team
- games_vs_opponent: Sample size

#### Minutes/Efficiency (2)
- minutes_avg_last_10: Recent playing time
- ppm_avg_last_10: Points per minute efficiency

### Hyperparameters

Based on proven configuration from XGBoost V7:

```python
{
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 1000,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'early_stopping_rounds': 50
}
```

These prevent overfitting through regularization.

### Output Files

#### Model File
`models/xgboost_v1_33features_YYYYMMDD_HHMMSS.json`
- XGBoost booster in JSON format
- Can be loaded by prediction worker

#### Metadata File
`models/xgboost_v1_33features_YYYYMMDD_HHMMSS_metadata.json`

Contains:
- Model ID and version
- Training timestamp
- Feature list and count
- Hyperparameters
- Performance metrics (train/val MAE, RMSE, accuracy)
- Feature importance (top 10)
- Date range
- Baseline comparisons
- GCS paths (if uploaded)

### Integration with Prediction Worker

Once trained, update the prediction worker to load the model:

1. **Update environment variable:**
   ```bash
   export XGBOOST_V1_MODEL_PATH="gs://nba-ml-models/xgboost_v1/xgboost_v1_33features_YYYYMMDD_HHMMSS.json"
   ```

2. **Update deployment script:**
   ```bash
   # In bin/predictions/deploy/deploy_prediction_worker.sh
   --set-env-vars="XGBOOST_V1_MODEL_PATH=gs://nba-ml-models/xgboost_v1/[MODEL_ID].json"
   ```

3. **Prediction worker will:**
   - Load model from GCS on startup
   - Use real trained model instead of mock
   - Generate predictions with same interface

### Baselines

Performance targets relative to:

- **Mock XGBoost V1**: 4.80 MAE (heuristic-based)
- **Mock XGBoost V2**: 4.50 MAE (improved heuristics)
- **CatBoost V8**: 3.40 MAE (current champion)

**Success criteria:**
- ✓ Beat Mock V1 (< 4.80 MAE)
- ✓ Beat Mock V2 (< 4.50 MAE)
- ✓ Meet target (≤ 4.5 MAE validation)
- Stretch: Approach V8 (< 3.8 MAE)

### Troubleshooting

#### "Not enough training data"
- Check Option C backfill status
- Minimum: ~1,000 games (Nov-Dec 2021)
- Recommended: ~76,000+ games (full historical)

#### "Validation MAE > 5.0"
- Expected with limited data (<10,000 games)
- Model is overfitting
- Wait for Option C completion
- Use for testing only, not production

#### "Feature version mismatch"
- Ensure ml_feature_store_v2 has feature_version='v2_33features'
- Check feature_count=33
- Run ml_feature_store_processor for missing dates

#### "GCS upload failed"
- Check GCS_MODEL_BUCKET exists
- Verify service account permissions
- Model still saved locally

### Monitoring & Retraining

**When to retrain:**
- Weekly: If new historical data available (Option C progress)
- Monthly: Once production-ready with full data
- As needed: If prediction accuracy degrades

**Automated retraining:**
- See: `/bin/predictions/setup_automated_training.sh` (to be created in Phase 5D)

### Next Steps

1. **Test training with current data:**
   ```bash
   PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py --start-date 2021-11-01 --end-date 2021-12-31
   ```

2. **Validate model loads in worker:**
   - Update XGBOOST_V1_MODEL_PATH
   - Test prediction endpoint
   - Compare vs mock predictions

3. **Wait for Option C completion:**
   - Monitor backfill progress
   - Retrain when 80%+ complete
   - Deploy production model

4. **Production deployment:**
   - Upload to GCS
   - Update worker environment
   - Gradual rollout (10% → 50% → 100%)
   - Monitor accuracy vs Session 85 grading

### Related Files

- **Prediction worker**: `/predictions/worker/worker.py`
- **XGBoost V1 system**: `/predictions/worker/prediction_systems/xgboost_v1.py`
- **Mock model**: `/predictions/shared/mock_xgboost_model.py`
- **Feature store**: `/data_processors/precompute/ml_feature_store/`
- **Project docs**: `/docs/08-projects/current/option-d-ml-deployment/`

---

**Created**: 2026-01-17
**Version**: 1.0
**Author**: Option D Phase 5A Implementation
**Status**: Ready for testing with limited data
