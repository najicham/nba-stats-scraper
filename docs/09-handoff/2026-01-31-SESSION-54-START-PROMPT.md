# Session 54 Start Prompt - Model Ensemble Research

## Context

Session 53 ran model retraining experiments and found:
1. **Production V8 is a stacked ensemble** (XGBoost + LightGBM + CatBoost + Ridge meta-learner)
2. **Our single CatBoost models underperform** (51% vs 57% hit rate)
3. **Different models excel at different player tiers**:
   - V8 is best for stars (55.8%) and bench (57.5%)
   - JAN_DEC_ONLY is best for rotation (63%) and starters (59.9%)

## Immediate Goals

1. **Understand V8 ensemble architecture** - Read the code and document exactly how it works
2. **Implement tier-based model selection** - Use the best model for each player tier
3. **Design seasonal model switching** - Plan for mid-season pattern changes
4. **Backtest the tier-based approach** - Verify it outperforms V8 on January 2026 data

## Start Here

```bash
# Read the handoff and research plan
cat docs/09-handoff/2026-01-31-SESSION-53-MODEL-EXPERIMENTS-HANDOFF.md
cat docs/08-projects/current/model-ensemble-research/RESEARCH-PLAN.md

# Then explore V8 implementation
cat predictions/worker/prediction_systems/catboost_v8.py
```

## Key Questions to Answer

1. Where is the V8 stacked ensemble trained?
2. What are the base model weights in the Ridge meta-learner?
3. Can we implement tier-based selection without changing production code?
4. How would we A/B test the new approach?

## Experiment Models Available

```
ml/experiments/results/
├── catboost_v9_exp_JAN_DEC_ONLY_*.cbm        # 63% on rotation players
├── catboost_v9_exp_JAN_LAST_SEASON_*.cbm     # Best overall single model
├── catboost_v9_exp_JAN_FULL_HISTORY_*.cbm    # Trained like V8
└── *_metadata.json
```

## Success Criteria

- [ ] Document V8 ensemble architecture
- [ ] Create tier-based predictor class
- [ ] Backtest tier-based approach on Jan 2026
- [ ] Compare: Tier-based vs V8 vs Vegas blend
- [ ] Write implementation plan for production

## Reference Data

Session 53 results on January 2026:

| Model | Stars | Rotation | Overall |
|-------|-------|----------|---------|
| V8 Production | 55.8% | 59.1% | 57.3% |
| JAN_DEC_ONLY | 29.6% | 63.0% | 55.1% |
| Tier-Based (proposed) | 55.8%* | 63.0%* | ~59%* |

*Proposed: Use V8 for stars, JAN_DEC_ONLY for rotation
