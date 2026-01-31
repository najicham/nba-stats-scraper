# Model Ensemble Research - Recommendations

**Date:** 2026-01-31
**Session:** 54
**Priority:** High - Direct impact on prediction accuracy and ROI

---

## Summary

Session 54 completed rigorous backtesting of the tier-based model selection hypothesis from Session 53. **The hypothesis was disproven.** The simpler approach of using a single recently-trained model (JAN_DEC_only) outperforms both V8 and tier-based routing.

---

## Current State (Problems)

### 1. V8 Production Is NOT Using Full Ensemble

The `catboost_v8.py` docstring claims "stacked ensemble (XGBoost + LightGBM + CatBoost with Ridge meta-learner)" but the code only loads CatBoost:

```python
# predictions/worker/prediction_systems/catboost_v8.py line 480
model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))
self.model = cb.CatBoostRegressor()
self.model.load_model(str(model_path))
# XGBoost and LightGBM models exist in models/ but are NOT loaded!
```

**Impact:** 0.8% MAE improvement left on the table (3.40 stacked vs 3.43 CatBoost-only)

### 2. V8 Underperforms on January 2026 Data

| Model | Hit Rate (3+ edge) | ROI | MAE |
|-------|-------------------|-----|-----|
| V8-only | 49.4% | -5.6% | 4.89 |
| JAN_DEC_only | **54.7%** | **+4.4%** | **4.53** |

V8 is below breakeven (52.4%), losing money on every bet.

### 3. Tier-Based Routing Hurts Performance

Session 53 hypothesized using V8 for stars/bench and JAN_DEC for starters/rotation. Testing showed JAN_DEC beats V8 for ALL tiers:

| Tier | V8 Hit Rate | JAN_DEC Hit Rate | Winner |
|------|-------------|------------------|--------|
| Star (22+ ppg) | 50.0% | 53.5% | JAN_DEC +3.5% |
| Starter (14-22 ppg) | 46.4% | 55.8% | JAN_DEC +9.4% |
| Rotation (6-14 ppg) | 49.1% | 52.1% | JAN_DEC +3.0% |
| Bench (<6 ppg) | 62.8% | 63.5% | JAN_DEC +0.7% |

---

## Recommendations

### Immediate Actions (This Week)

#### 1. Deploy JAN_DEC Model in Shadow Mode

Run JAN_DEC predictions alongside V8 without using them for actual recommendations:

```python
# In prediction_worker.py
def predict_with_shadow(player_lookup, features, betting_line):
    # Current production prediction
    v8_result = catboost_v8.predict(player_lookup, features, betting_line)

    # Shadow prediction - log but don't use
    try:
        jan_dec_result = jan_dec_model.predict(features[:37])
        log_shadow_prediction(
            player_lookup=player_lookup,
            game_date=features.get('game_date'),
            v8_prediction=v8_result['predicted_points'],
            jan_dec_prediction=jan_dec_result,
            betting_line=betting_line,
        )
    except Exception as e:
        logger.warning(f"Shadow prediction failed: {e}")

    return v8_result  # Still use V8 for now
```

**Files to modify:**
- `predictions/worker/predictor.py`
- Add JAN_DEC model loading

**Model to deploy:**
- `ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm` → GCS

#### 2. Increase Edge Threshold

Based on Session 53 data, V8 at 90% confidence + 3+ edge achieves 78.6% hit rate. Until a better model is deployed:

```python
# In prediction recommendation logic
MIN_EDGE_THRESHOLD = 3.0  # Up from 1.0
MIN_CONFIDENCE = 90       # Already in place
```

#### 3. Fix V8 Docstring

Update `catboost_v8.py` to accurately describe what's deployed:

```python
"""
CatBoost V8 Prediction System

Uses the CatBoost model from the V8 stacked ensemble training.

IMPORTANT: This production code only loads the CatBoost base model.
The full stacked ensemble (XGB + LGB + CB + Ridge) achieves better
MAE (3.40 vs 3.43) but is not implemented in production.

See: docs/08-projects/current/model-ensemble-research/V8-ARCHITECTURE-ANALYSIS.md
"""
```

---

### Short-Term Actions (Next 2 Weeks)

#### 4. Replace V8 with JAN_DEC in Production

After shadow mode validation shows JAN_DEC outperforms:

1. **Deploy JAN_DEC model to GCS**
   ```bash
   gsutil cp ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm \
       gs://nba-props-models/catboost_jan_dec_v1.cbm
   ```

2. **Add environment variable for model selection**
   ```python
   # In catboost_v8.py or new prediction_system
   MODEL_VERSION = os.environ.get('PREDICTION_MODEL', 'v8')
   if MODEL_VERSION == 'jan_dec':
       # Load JAN_DEC model
   ```

3. **Gradual rollout**
   - 10% of predictions → monitor 2 days
   - 50% of predictions → monitor 3 days
   - 100% of predictions

#### 5. Set Up Monthly Retraining Pipeline

JAN_DEC's advantage comes from recency. Automate monthly retraining:

```python
# ml/training/monthly_retrain.py
def retrain_monthly():
    """Train new model on last 60 days of data."""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=60)

    # Load training data
    df = load_training_data(start_date, end_date)

    # Train model
    model = train_catboost(df, features=ALL_37_FEATURES)

    # Validate on holdout
    holdout_mae = evaluate_model(model, holdout_df)

    # Deploy if better than current
    if holdout_mae < current_model_mae:
        deploy_model(model, f"catboost_monthly_{end_date}.cbm")
```

**Schedule:** First of each month, or after trade deadline

---

### Long-Term Actions (Next Month)

#### 6. Implement True Stacked Ensemble

Deploy the full ensemble that training creates:

```python
# predictions/worker/prediction_systems/stacked_ensemble_v1.py

class StackedEnsembleV1:
    def __init__(self):
        self.xgb = load_xgboost_model()   # xgboost_v8_33features_*.json
        self.lgb = load_lightgbm_model()  # lightgbm_v8_33features_*.txt
        self.cb = load_catboost_model()   # catboost_v8_33features_*.cbm

        # Ridge coefficients from training
        self.ridge_coefs = [0.38, -0.10, 0.74]

    def predict(self, features):
        xgb_pred = self.xgb.predict(features)
        lgb_pred = self.lgb.predict(features)
        cb_pred = self.cb.predict(features)

        # Apply Ridge meta-learner
        stacked_pred = (
            self.ridge_coefs[0] * xgb_pred +
            self.ridge_coefs[1] * lgb_pred +
            self.ridge_coefs[2] * cb_pred
        )
        return stacked_pred
```

**Considerations:**
- 3x model loading time
- 3x memory footprint
- 3x inference latency
- Worth it for 0.8% MAE improvement?

#### 7. Confidence Calibration

V8's confidence scores don't match actual accuracy. Implement calibration:

```python
# Calibration mapping based on historical performance
CONFIDENCE_CALIBRATION = {
    90: 0.786,  # 90% confidence → 78.6% actual at 3+ edge
    80: 0.65,   # Estimated
    70: 0.55,   # Estimated
}

def calibrate_confidence(raw_confidence):
    """Convert model confidence to calibrated probability."""
    return CONFIDENCE_CALIBRATION.get(int(raw_confidence), raw_confidence / 100)
```

---

## Validation Criteria

Before deploying any change, verify:

| Metric | Current V8 | Target | Method |
|--------|------------|--------|--------|
| Hit rate (3+ edge) | 49.4% | 54%+ | Backtest on last 30 days |
| ROI | -5.6% | +2%+ | Backtest on last 30 days |
| MAE | 4.89 | <4.6 | Compare on holdout |

---

## Files Reference

| File | Purpose |
|------|---------|
| `ml/experiments/tier_based_backtest.py` | Backtest script for validation |
| `ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_*.cbm` | Best performing model |
| `models/ensemble_v8_*_metadata.json` | Ridge coefficients for stacked ensemble |
| `predictions/worker/prediction_systems/catboost_v8.py` | Current production code |

---

## Commands to Run

```bash
# Run tier-based backtest to verify findings
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/tier_based_backtest.py \
    --eval-start 2026-01-01 \
    --eval-end 2026-01-30 \
    --min-edge 3.0

# Train new model on recent data
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 \
    --train-end 2026-01-30 \
    --experiment-id FEB_RECENT

# Evaluate model
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_FEB_RECENT_*.cbm" \
    --eval-start 2026-01-15 \
    --eval-end 2026-01-30 \
    --experiment-id FEB_RECENT
```

---

## Decision Points for Next Session

1. **Shadow mode or direct deployment?** - JAN_DEC is clearly better, but shadow mode is safer
2. **Monthly retraining or continuous?** - Monthly is simpler, continuous adapts faster
3. **True stacked ensemble?** - 3x resources for 0.8% MAE improvement

---

## Appendix: Backtest Results Summary

```
================================================================================
 January 2026 Backtest (Edge >= 3.0)
================================================================================

V8_only:
  Overall: 49.4% (529/1070), ROI: -5.6%
  By tier: Star 50.0%, Starter 46.4%, Rotation 49.1%, Bench 62.8%

JAN_DEC_only:
  Overall: 54.7% (333/609), ROI: +4.4%
  By tier: Star 53.5%, Starter 55.8%, Rotation 52.1%, Bench 63.5%

tier_based (V8 for star/bench, JAN_DEC for starter/rotation):
  Overall: 54.1% (377/697), ROI: +3.3%
  By tier: Star 50.0%, Starter 55.8%, Rotation 52.1%, Bench 62.8%

CONCLUSION: JAN_DEC_only is best. Tier-based routing provides no benefit.
================================================================================
```

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
