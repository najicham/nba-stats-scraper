# Model Ensemble Research Plan

**Created:** 2026-01-31
**Status:** Ready for next session
**Priority:** High - directly impacts prediction accuracy

---

## Research Goals

1. **Understand production V8 ensemble architecture** - How does the stacked ensemble work?
2. **Build tier-based model selection** - Use best model per player tier
3. **Implement seasonal model switching** - Adapt to mid-season patterns
4. **Create new ensemble** - Match or exceed V8 performance

---

## Phase 1: Understand V8 Ensemble Architecture

### Tasks

1. **Read V8 production code**
   ```
   predictions/worker/prediction_systems/catboost_v8.py
   ```
   - How is the stacked ensemble implemented?
   - What are the base models (XGBoost, LightGBM, CatBoost)?
   - How does the Ridge meta-learner combine predictions?

2. **Find V8 training code**
   ```bash
   find . -name "*ensemble*" -o -name "*stacked*" -o -name "*meta*"
   grep -r "Ridge" ml/
   grep -r "XGBoost" ml/
   ```

3. **Locate V8 base model files**
   ```bash
   ls -la models/
   find . -name "*.xgb" -o -name "*.lgb" -o -name "*lightgbm*"
   ```

4. **Document V8 architecture**
   - Base model count and types
   - Feature sets per model
   - Meta-learner weights/coefficients
   - Training procedure

### Expected Output
- Architecture diagram
- Training procedure documentation
- Understanding of why ensemble outperforms single models

---

## Phase 2: Implement Tier-Based Model Selection

### Concept

Different player tiers show different model performance:

| Tier | Best Performer | Hit Rate |
|------|----------------|----------|
| Star (25+) | V8 Production | 55.8% |
| Starter (15-25) | JAN_DEC_ONLY | 59.9% |
| Rotation (5-15) | JAN_DEC_ONLY | 63.0% |
| Bench (<5) | V8 Production | 57.5% |

### Implementation Plan

1. **Create TierBasedPredictor class**
   ```python
   class TierBasedPredictor:
       def __init__(self):
           self.star_model = load_v8_production()
           self.rotation_model = load_jan_dec_only()
           self.tier_thresholds = {...}

       def predict(self, player_lookup, features):
           expected_tier = self.estimate_tier(features)
           if expected_tier == 'star':
               return self.star_model.predict(features)
           elif expected_tier in ['starter', 'rotation']:
               return self.rotation_model.predict(features)
           else:
               return self.star_model.predict(features)

       def estimate_tier(self, features):
           # Use points_avg_last_10 to estimate tier
           avg = features['points_avg_last_10']
           if avg >= 22: return 'star'
           elif avg >= 14: return 'starter'
           elif avg >= 6: return 'rotation'
           else: return 'bench'
   ```

2. **Backtest tier-based selection**
   ```python
   # For each prediction in January 2026:
   # 1. Estimate player tier from features
   # 2. Select appropriate model
   # 3. Calculate hit rate by tier
   ```

3. **A/B test in production**
   - Run tier-based alongside V8
   - Compare hit rates after 1 week

### Challenges
- Tier estimation must use pre-game features only
- Edge cases: breakout players, injury returns
- Model loading overhead

---

## Phase 3: Seasonal Model Switching

### Concept

Model performance varies throughout the season:

| Period | Recommended Approach |
|--------|---------------------|
| Oct-Nov (early season) | Conservative (lower confidence thresholds) |
| Dec-Feb (mid-season) | Full confidence, use ensemble |
| Mar-Apr (playoff push) | Account for rest patterns |
| Playoffs | Different model (fewer games, higher variance) |

### Research Questions

1. **Does performance degrade mid-season?**
   ```sql
   SELECT
     FORMAT_DATE('%Y-%m', game_date) as month,
     ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v8'
     AND game_date >= '2025-10-01'
   GROUP BY 1 ORDER BY 1
   ```

2. **Are there pattern changes mid-season?**
   - Trade deadline effects
   - Rest pattern changes
   - Playoff seeding impact on effort

3. **Should we retrain monthly?**
   - Test: Train on rolling 60-day window
   - Compare to full-history model

### Implementation Options

1. **Scheduled retraining**
   - Monthly retrain with recency weighting
   - Automated pipeline

2. **Drift detection + retrain**
   - Monitor hit rate weekly
   - Trigger retrain when < 55% for 2 weeks

3. **Calendar-based model switching**
   - Pre-configured models per period
   - Manual oversight

---

## Phase 4: Build New Ensemble

### Option A: Replicate V8 Architecture

1. Train XGBoost on 2021-2024 data
2. Train LightGBM on 2021-2024 data
3. Train CatBoost on 2021-2024 data
4. Train Ridge meta-learner on 2024-25 predictions

```python
# Meta-learner training
base_predictions = np.column_stack([
    xgb_model.predict(X_val),
    lgb_model.predict(X_val),
    catboost_model.predict(X_val)
])
meta_model = Ridge(alpha=1.0)
meta_model.fit(base_predictions, y_val)
```

### Option B: Tier-Specialized Ensemble

1. Train star-specialist model (only 20+ ppg players)
2. Train rotation-specialist model (5-20 ppg players)
3. Train bench-specialist model (<5 ppg players)
4. Combine based on predicted tier

### Option C: Temporal Ensemble

1. Train recent model (last 60 days)
2. Train historical model (2021-2024)
3. Blend: 60% recent + 40% historical

### Option D: Confidence-Weighted Blend

1. Each model outputs confidence
2. Weight predictions by confidence
3. Higher confidence model gets more weight

---

## Phase 5: Integration Plan

### Database Changes

```sql
-- New table for model selection tracking
CREATE TABLE nba_predictions.model_selection_log (
    prediction_id STRING,
    player_lookup STRING,
    game_date DATE,
    estimated_tier STRING,
    model_used STRING,
    confidence_score FLOAT64,
    predicted_points FLOAT64,
    created_at TIMESTAMP
);
```

### Code Changes

1. **prediction_systems/tier_based_v1.py** - New prediction system
2. **prediction_systems/ensemble_v2.py** - Updated ensemble
3. **worker/predictor.py** - Model selection logic

### Configuration

```yaml
# config/model_selection.yaml
tier_based:
  enabled: true
  star_model: "catboost_v8"
  starter_model: "jan_dec_only"
  rotation_model: "jan_dec_only"
  bench_model: "catboost_v8"

seasonal:
  enabled: false
  switch_dates:
    - date: "2026-02-15"
      model: "trade_deadline_model"
    - date: "2026-04-01"
      model: "playoff_push_model"

ensemble:
  method: "stacked"  # or "tier_based", "temporal", "confidence_weighted"
  base_models: ["xgboost_v1", "lightgbm_v1", "catboost_v9"]
  meta_learner: "ridge"
```

### Deployment Strategy

1. **Shadow mode first** - Run new system alongside V8
2. **Gradual rollout** - 10% → 50% → 100%
3. **Easy rollback** - Feature flag to disable
4. **Monitoring** - Compare hit rates daily

---

## Validation Criteria

### Success Metrics

| Metric | Current V8 | Target |
|--------|------------|--------|
| Overall hit rate | 56.6% | 58%+ |
| Star hit rate | 55.8% | 58%+ |
| High confidence (3+ edge) | 58.8% | 62%+ |
| ROI | +4.2% | +6%+ |

### Testing Plan

1. **Backtest on Jan 2026** - Already have actuals
2. **Forward test Feb 2026** - Shadow mode
3. **Compare to V8** - Same predictions, different models
4. **Statistical significance** - Need 500+ bets for comparison

---

## Quick Start for Next Session

```bash
# 1. Read this plan
cat docs/08-projects/current/model-ensemble-research/RESEARCH-PLAN.md

# 2. Explore V8 ensemble architecture
cat predictions/worker/prediction_systems/catboost_v8.py

# 3. Search for ensemble training code
grep -r "Ridge" ml/ --include="*.py"
grep -r "stacked" . --include="*.py"

# 4. Check existing base models
ls -la models/

# 5. Start with Phase 1 tasks
```

---

## Research Questions to Answer

1. How exactly does V8's stacked ensemble work?
2. What are the Ridge meta-learner coefficients?
3. Can we train a new ensemble that matches V8?
4. Is tier-based selection better than a single ensemble?
5. How do we handle players who switch tiers mid-game?
6. What's the optimal retraining frequency?
7. Should we use Vegas lines as a feature or blend target?

---

## Files to Read

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v8.py` | V8 implementation |
| `ml/model_loader.py` | How models are loaded |
| `ml/model_contract.py` | Model registry interface |
| `ml/experiments/train_walkforward.py` | Training script |
| `docs/05-development/ml/training-procedures.md` | Training docs |

---

## Session 53 Experiment Models Location

```
ml/experiments/results/
├── catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm        # Best for rotation
├── catboost_v9_exp_JAN_NOV_DEC_20260131_085112.cbm         # Competitive
├── catboost_v9_exp_JAN_LAST_SEASON_20260131_085238.cbm     # Best single model
├── catboost_v9_exp_JAN_FULL_HISTORY_20260131_085719.cbm    # Same as V8 period
└── *_metadata.json                                          # Training metadata
```

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
