# Session 55 Handoff - Combined Model Research

**Date:** 2026-01-31
**Focus:** Stacked ensemble experiments, drift detection, cross-year analysis
**Status:** COMPLETE - All hypotheses tested, recommendations ready

---

## Executive Summary

Session 55 tested whether recency weighting helps the stacked ensemble (from Session 52's findings) and built drift detection (from Session 52's wishlist). Key conclusions:

1. **Recency weighting on historical data does NOT help** - 50.1% hit rate (same as baseline)
2. **Stacked ensemble provides no benefit over single CatBoost** - 50.0% vs 49.4%
3. **Training on RECENT data only is the key** - JAN_DEC at 54.7% beats all old-data models
4. **January patterns are consistent across years** - Stars always underperform in January
5. **Model drift is CRITICAL** - 60% drift score, 6/10 signals in alert

---

## Experiments Completed

### 1. Stacked Ensemble with Recency Weighting

| Configuration | Training Data | Recency | Hit Rate (3+ edge) | MAE |
|--------------|--------------|---------|-------------------|-----|
| V8 Production | 2021-2024 | None | 49.4% | 4.89 |
| ENS_BASELINE | 2021-2024 | None | 50.0% | 6.47 |
| ENS_REC60 | 2021-2024 | 60d half-life | 50.1% | 6.71 |
| **JAN_DEC_ONLY** | Dec 2025 | Implicit | **54.7%** | **4.53** |

**Conclusion:** Recency weighting historical data doesn't help. Training on recent data only is better.

### 2. Cross-Year January Analysis

| Year | Star Deviation | Star Underperform % | Surprise Rate | V8 Hit Rate |
|------|---------------|---------------------|--------------|-------------|
| 2024 | -2.18 pts | 37.2% | 11.4% | N/A |
| 2025 | -0.65 pts | 30.3% | 11.1% | 55.5% |
| 2026 | -1.70 pts | 31.9% | 9.7% | **41.9%** |

**Conclusion:** January patterns are consistent (stars underperform), but V8 degraded from 55.5% → 41.9% because player roster/role changes accumulated over 18 months.

### 3. Drift Detection System

Created `bin/monitoring/model_drift_detection.py` that monitors:
- Rolling hit rates (7d, 14d, 30d)
- Star player performance deviation
- Surprise game rate
- Prediction error distribution
- Tier-specific performance

**Current Status:** CRITICAL (60% drift score)
- 7-day hit rate: 45.1% (ALERT)
- 14-day hit rate: 46.9% (ALERT)
- Starter tier: 45.2% (ALERT)
- Bench tier: 33.3% (ALERT)

---

## Architecture Finding Confirmed

**Production V8 uses ONLY CatBoost, not the full stacked ensemble.**

The training script (`ml/train_final_ensemble_v8.py`) creates XGBoost + LightGBM + CatBoost + Ridge, but production (`catboost_v8.py`) only loads CatBoost. The stacked ensemble's 0.8% MAE improvement was left on the table, but our experiments show it wouldn't matter - both perform ~50% on January 2026.

Ridge meta-learner coefficients from V8 training:
- XGBoost: 0.38
- LightGBM: -0.10 (penalized)
- CatBoost: 0.74 (dominant)

---

## Key Learnings

1. **Training data recency > Recency weights** - Use recent data only, not weighted old data
2. **Ensemble complexity isn't worth it** - Single CatBoost performs the same as stacked ensemble
3. **Small sample results are unreliable** - Session 52's 65% on 40 bets didn't replicate
4. **Player behavior drifts significantly** - 18 months = stale model
5. **January patterns are predictable** - Stars always underperform (30-37% by 5+ pts)

---

## Recommendations

### Immediate (This Week)

1. **Deploy JAN_DEC_ONLY model** - Best performer at 54.7% vs V8's 49.4%
2. **Increase edge threshold to 5+** - V8 at 5+ edge: ~54% vs 45% at 3+ edge
3. **Run drift detection daily** - `PYTHONPATH=. python bin/monitoring/model_drift_detection.py`

### Short-Term (Next 2 Weeks)

4. **Set up monthly retraining** - Train on last 60 days at start of each month
5. **Add seasonal adjustment for January** - Stars get -1.5pt prediction penalty

### Long-Term

6. **Abandon stacked ensemble** - Complexity for no gain
7. **Consider weekly retraining** - During volatile periods like trade deadline

---

## Files Created/Modified

### New Scripts
| File | Purpose |
|------|---------|
| `ml/experiments/train_stacked_ensemble_recency.py` | Train stacked ensemble with recency |
| `ml/experiments/evaluate_stacked_ensemble.py` | Evaluate stacked ensemble |
| `bin/monitoring/model_drift_detection.py` | Drift detection system |

### Documentation
| File | Purpose |
|------|---------|
| `docs/08-projects/current/model-ensemble-research/V8-ARCHITECTURE-ANALYSIS.md` | V8 architecture findings |
| `docs/08-projects/current/model-ensemble-research/SESSION-55-FINDINGS.md` | Detailed experiment results |

### Experiment Results
| File | Description |
|------|-------------|
| `ml/experiments/results/ensemble_exp_ENS_REC60_*.cbm` | Recency-weighted ensemble |
| `ml/experiments/results/ensemble_exp_ENS_BASELINE_*.cbm` | Baseline ensemble |
| `ml/experiments/results/ENS_REC60_eval_*.json` | January 2026 evaluation |
| `ml/experiments/results/ENS_BASELINE_eval_*.json` | January 2026 evaluation |

---

## Commands Reference

```bash
# Run drift detection
PYTHONPATH=. python bin/monitoring/model_drift_detection.py

# Train new ensemble with recency
PYTHONPATH=. python ml/experiments/train_stacked_ensemble_recency.py \
    --train-start 2021-11-01 --train-end 2024-06-30 \
    --experiment-id TEST --use-recency-weights --half-life 60

# Evaluate ensemble
PYTHONPATH=. python ml/experiments/evaluate_stacked_ensemble.py \
    --metadata-path "ml/experiments/results/ensemble_exp_*.json" \
    --eval-start 2026-01-01 --eval-end 2026-01-30

# Train recent-only model (recommended approach)
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 --train-end 2026-01-31 \
    --experiment-id FEB_2026
```

---

## Continuity with Previous Sessions

| Session | Finding | Status |
|---------|---------|--------|
| 52 | 60-day recency helps single CatBoost | **Disproven** - small sample noise |
| 53 | V8 ensemble outperforms single CatBoost | **Clarified** - only in training, not production |
| 54 | JAN_DEC beats V8 for all tiers | **Confirmed** |
| 54 | Tier-based routing provides no benefit | **Confirmed** |
| 55 | Recency weighting helps ensemble | **Disproven** |
| 55 | Train on recent data only | **Confirmed as best approach** |

---

## Next Session Priorities

1. **Deploy JAN_DEC model to production** - Shadow mode then rollout
2. **Implement monthly retraining pipeline** - Automate the winning approach
3. **Add January seasonal adjustment** - -1.5pt for stars
4. **Monitor drift after deployment** - Validate JAN_DEC maintains 54%+ hit rate

---

## Success Metrics

| Metric | V8 Current | Target | JAN_DEC Expected |
|--------|------------|--------|-----------------|
| Hit rate (3+ edge) | 49.4% | 54%+ | **54.7%** |
| ROI | -5.6% | +2%+ | **+4.4%** |
| MAE | 4.89 | <4.6 | **4.53** |

---

*Session 55 Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
