# Session 54 Handoff - Model Ensemble Research

**Date:** 2026-01-31
**Focus:** Model ensemble research and tier-based prediction testing
**Status:** Research complete, key finding contradicts Session 53 hypothesis

---

## Executive Summary

Session 54 investigated the tier-based model selection hypothesis from Session 53 and found it to be **incorrect**. The simpler approach (using JAN_DEC_only for all tiers) outperforms both V8 and the tier-based routing strategy.

### Key Finding

| Strategy | Hit Rate (3+ edge) | ROI |
|----------|-------------------|-----|
| **JAN_DEC_only** | **54.7%** | **+4.4%** |
| Tier-based | 54.1% | +3.3% |
| V8-only | 49.4% | -5.6% |

**Recommendation: Deploy JAN_DEC_only model instead of V8**

---

## Research Completed

### 1. V8 Architecture Analysis

**Finding:** Production V8 is NOT using the full stacked ensemble!

- Training creates: XGBoost + LightGBM + CatBoost + Ridge meta-learner
- Production deploys: CatBoost only
- Gap: 0.027 MAE left on the table (3.40 vs 3.43)

Ridge meta-learner coefficients:
```python
stacked_coefs = [0.38, -0.10, 0.74]  # XGB, LGB, CB
```

### 2. Tier-Based Backtest

Tested hypothesis: V8 for stars/bench, JAN_DEC for starters/rotation

**Result:** Hypothesis DISPROVED

JAN_DEC outperforms V8 for ALL tiers:
- Stars: 53.5% vs 50.0% (+3.5%)
- Starters: 55.8% vs 46.4% (+9.4%)
- Rotation: 52.1% vs 49.1% (+3.0%)
- Bench: 63.5% vs 62.8% (+0.7%)

### 3. Why JAN_DEC Wins

1. **Recency** - Trained on December 2025, captures current roles
2. **More features** - 37 features vs 33 (includes DNP rate, trajectory)
3. **Better calibration** - MAE 4.53 vs 4.89 for V8

---

## Files Created

| File | Purpose |
|------|---------|
| `ml/experiments/tier_based_backtest.py` | Tier-based evaluation script |
| `ml/experiments/results/tier_based_backtest_*.json` | Backtest results |
| `docs/08-projects/current/model-ensemble-research/SESSION-54-FINDINGS.md` | Full research findings |
| `docs/08-projects/current/model-ensemble-research/V8-ARCHITECTURE-ANALYSIS.md` | V8 architecture docs |

---

## Production Recommendations

### Immediate (Low Risk)

1. **Shadow mode JAN_DEC** - Log JAN_DEC predictions alongside V8
2. **Monitor for 1 week** - Compare hit rates on real bets
3. **Stricter edge filtering** - Only bet when edge >= 3.0 (78.6% hit rate per Session 53)

### Short-term (Medium Risk)

1. **Deploy JAN_DEC model** - Better than V8 across all metrics
2. **Monthly retraining** - Train on rolling 60-day window
3. **Update catboost_v8.py docstring** - Accurately describe what's deployed

### Long-term (Higher Effort)

1. **True stacked ensemble** - Deploy XGB + LGB + CB + Ridge in production
2. **Automated model selection** - Train challenger models, auto-promote if better
3. **Confidence calibration** - V8's confidence doesn't match actual accuracy

---

## Commands Reference

```bash
# Run tier-based backtest
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/tier_based_backtest.py \
    --eval-start 2026-01-01 \
    --eval-end 2026-01-30 \
    --min-edge 3.0

# Read research findings
cat docs/08-projects/current/model-ensemble-research/SESSION-54-FINDINGS.md
```

---

## Next Session Checklist

1. [ ] Review JAN_DEC deployment strategy
2. [ ] Consider implementing true stacked ensemble
3. [ ] Set up monthly retraining pipeline
4. [ ] Run /validate-daily to check system health

---

## Key Learnings

1. **Test hypotheses rigorously** - Session 53's tier-based hypothesis didn't hold up to backtest
2. **Simpler is often better** - JAN_DEC alone beats complex tier routing
3. **Recency matters** - Recent training data (Dec 2025) outperforms historical (2021-2024)
4. **Check production code** - V8 docstring says "stacked ensemble" but only uses CatBoost

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
