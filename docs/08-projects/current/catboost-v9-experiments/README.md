# CatBoost V9 Experiments

**Status**: CLOSED - V9 code removed, recency weighting doesn't help
**Started**: 2026-01-30
**Completed**: 2026-01-30
**Next Step**: Create V11 with seasonal features (separate project)

---

## Summary

We ran 6 experiments testing recency weighting. **All performed worse than baseline.**

The original hypothesis was about **seasonal patterns** (stars playing more in January), but we tested **uniform recency weighting** instead. These are different things.

**Decision:** V9 code deleted. Moving to V11 with seasonal features.

---

## Experiment Results

| Experiment | MAE | vs Baseline | Configuration |
|------------|-----|-------------|---------------|
| **A1_V8_BASELINE** | **4.0235** | - | No recency (BEST) |
| C3_CURRENT_SEASON | 4.0330 | +0.2% | Current season, 90-day |
| A4_RECENCY_365 | 4.0760 | +1.3% | Full data, 365-day |
| A2_RECENCY_180 | 4.1681 | +3.6% | Full data, 180-day |
| A3_RECENCY_90 | 4.1816 | +3.9% | Full data, 90-day |
| C2_RECENT_2YR | 4.1820 | +3.9% | 2-year, 180-day |

### Key Finding

**Recency weighting HURTS performance.** More aggressive weighting = worse MAE.

Historical data from 2021-2024 is valuable. Don't discard it.

---

## Why Recency Weighting Failed

### What We Tested (Wrong Approach)
**Uniform recency weighting**: "All recent games matter more for all players"
- Exponential decay with half-life (90/180/365 days)
- Treats all players the same
- Discounts valuable historical patterns

### What We Should Have Tested
**Seasonal patterns**: "Stars play more in January/All-Star, bench rotations tighten"
- Specific time-of-year effects
- Player-tier differences
- Minutes trends (not just points)

The observation was:
> "Stars get more minutes near All-Star break, bench rotations tighten"

This is a **seasonal effect** that varies by player tier, not a uniform "recent = better" effect.

---

## Version History

| Version | Features | Status | Notes |
|---------|----------|--------|-------|
| V7 | 31 | Deprecated | Older |
| V8 | 33 | **PRODUCTION** | Champion (MAE ~3.40) |
| V9 | 36 (trajectory) | **DELETED** | Recency weighting failed |
| V10 | 33 | Model file only | No system |
| **V11** | ~39 (seasonal) | **NEXT** | Seasonal features |

---

## V9 Code Status

### Deleted (Session 35)

| File | Action | Reason |
|------|--------|--------|
| `predictions/worker/prediction_systems/catboost_v9.py` | **DELETED** | Recency weighting failed experiments |
| `predictions/worker/worker.py` | **REVERTED** | V9 shadow mode removed |

V9's trajectory features (`pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag`) could be revisited in a future version without recency weighting, but the code complexity wasn't justified by experiment results.

---

## Files

### Experiment Models (archived)
```
ml/experiments/results/catboost_v9_exp_A1_V8_BASELINE_20260130_080724.cbm
ml/experiments/results/catboost_v9_exp_A2_RECENCY_180_20260130_080724.cbm
ml/experiments/results/catboost_v9_exp_A3_RECENCY_90_20260130_080724.cbm
ml/experiments/results/catboost_v9_exp_A4_RECENCY_365_20260130_080725.cbm
ml/experiments/results/catboost_v9_exp_C2_RECENT_2YR_RECENCY_20260130_080735.cbm
ml/experiments/results/catboost_v9_exp_C3_CURRENT_SEASON_20260130_080735.cbm
```

### Documentation
- Handoff: `docs/09-handoff/2026-01-30-SESSION-34-CATBOOST-V9-EXPERIMENTS-HANDOFF.md`
- This file: `docs/08-projects/current/catboost-v9-experiments/README.md`

---

## Learnings

1. **Recency ≠ Seasonality**: Different hypotheses need different approaches
2. **Historical data matters**: 2021-2024 patterns are still relevant
3. **More aggressive ≠ better**: 90-day half-life was worst
4. **V8 is well-optimized**: Hard to beat with simple tricks
5. **Test hypotheses before deploying**: Saved us from deploying worse models
6. **Clean up failed experiments**: Don't keep dead code "just in case"

---

*V9 experiments closed. Recency weighting failed. V9 code deleted. Next: V11 with seasonal features.*
