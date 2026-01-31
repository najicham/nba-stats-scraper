# Session 55 Start Prompt - Combined Model Research

## Context (Two Sessions Merged)

**Session 52 findings:**
- 60-day recency weighting achieves **65% hit rate** on high-confidence picks (5+ pt edge)
- January 2026 had higher variance, stars underperforming by -1.1 pts
- UNDER picks outperform (64.7% vs 60% for OVER)
- But these experiments were on **single CatBoost models**

**Session 53 findings:**
- Production V8 is actually a **stacked ensemble** (XGBoost + LightGBM + CatBoost + Ridge meta-learner)
- Single CatBoost models underperform the ensemble (51% vs 57%)
- Different tiers need different models:
  - V8 is best for **stars** (55.8%) and **bench** (57.5%)
  - JAN_DEC_ONLY is best for **rotation** (63%) and **starters** (59.9%)

**The gap:** We don't know if 60-day recency weighting helps the ENSEMBLE, only that it helps single CatBoost.

---

## Immediate Goals (Priority Order)

### 1. Understand V8 Ensemble Architecture
Read and document how the production stacked ensemble works:
```bash
cat predictions/worker/prediction_systems/catboost_v8.py
# Find: Where is ensemble trained? What are base model weights?
```

### 2. Test Recency Weighting on Ensemble
Session 52's best finding needs validation:
- Does 60-day recency help the full ensemble, or just single CatBoost?
- Train ensemble with recency-weighted base models

### 3. Implement Tier-Based Model Selection
Combine best models per tier:
| Tier | Best Model | Hit Rate |
|------|------------|----------|
| Stars (25+ pts) | V8 ensemble | 55.8% |
| Starters (18-25) | JAN_DEC_ONLY | 59.9% |
| Rotation (12-18) | JAN_DEC_ONLY | 63.0% |
| Bench (<12) | V8 ensemble | 57.5% |

### 4. Build Model Drift Detection
Session 52 wanted this but ran out of context:
- Early warning signals for when model starts degrading
- Monitor: variance in actuals, star performance deviation, surprise game %
- Goal: Catch issues before they cost money

### 5. Cross-Year January Analysis
Does January ALWAYS have these patterns?
- Compare January 2024, 2025, 2026
- If consistent, build seasonal adjustments

---

## Key Questions to Answer

1. **Architecture:** How does V8 ensemble combine XGBoost + LightGBM + CatBoost?
2. **Recency + Ensemble:** Does recency weighting help ensemble or hurt it?
3. **Tier Selection:** Can we route predictions to different models by player tier?
4. **Drift Signals:** What metrics predict when model will struggle?
5. **Seasonality:** Is January consistently weird across years?

---

## Start Here

```bash
# Read both handoff docs
cat docs/09-handoff/2026-01-31-SESSION-52-CATBOOST-EXPERIMENTS-HANDOFF.md
cat docs/09-handoff/2026-01-31-SESSION-53-MODEL-EXPERIMENTS-HANDOFF.md

# Understand V8 architecture
cat predictions/worker/prediction_systems/catboost_v8.py

# Check experiment results
ls ml/experiments/results/*.json | tail -10
```

---

## Files Reference

**Handoffs:**
- `docs/09-handoff/2026-01-31-SESSION-52-CATBOOST-EXPERIMENTS-HANDOFF.md` - Recency experiments
- `docs/09-handoff/2026-01-31-SESSION-53-MODEL-EXPERIMENTS-HANDOFF.md` - Ensemble discovery

**Projects:**
- `docs/08-projects/current/catboost-v12-v13-experiments/` - Session 52 experiments
- `docs/08-projects/current/model-ensemble-research/` - Session 53 research

**Experiment Results:**
```
ml/experiments/results/
├── mega_experiment_20260131_*.json          # Session 52: 30+ experiments
├── catboost_v9_exp_JAN_DEC_ONLY_*.cbm       # Best for rotation (63%)
├── catboost_v9_exp_JAN_LAST_SEASON_*.cbm    # Best single model
└── *_metadata.json
```

---

## Success Criteria

- [ ] Document V8 ensemble architecture (weights, combination method)
- [ ] Test recency weighting on ensemble (not just single CatBoost)
- [ ] Backtest tier-based selection on January 2026
- [ ] Create drift detection queries/monitoring
- [ ] Compare: V8 vs Tier-based vs Recency-ensemble vs Vegas blend
- [ ] Write implementation plan for production changes

---

## Key Numbers to Beat

| Approach | Overall Hit Rate | High-Conf Hit Rate | Notes |
|----------|------------------|-------------------|-------|
| V8 Production | 57.3% | ~57% | Current baseline |
| Single CatBoost + 60d recency | 51.3% | **65.0%** | Session 52 best |
| Tier-based (proposed) | ~59% | TBD | Session 53 proposal |
| Combined (proposed) | TBD | TBD | Tier + recency + ensemble |

**Target:** Beat V8's 57.3% overall while maintaining 65%+ on high-confidence picks.

---

## Recommendation: Use Sonnet

This is primarily execution work:
- Running queries and experiments
- Reading/understanding code
- Implementing tier-based selection

Escalate to Opus if:
- Deep causal analysis needed (WHY does recency help?)
- Novel drift detection system design
- Synthesis across complex findings
