# Session 34 Handoff - CatBoost V9 Experiments

**Date:** 2026-01-30
**Focus:** CatBoost V9 implementation and recency weighting experiments

---

## Executive Summary

Session 34 implemented CatBoost V9 prediction system and ran 6 experiments testing recency weighting.

**Key Finding:** Recency weighting **hurts** performance. The more aggressive the weighting, the worse the MAE. Historical data is valuable.

**Current Status:** V9 code implemented but experiments show recency weighting should NOT be used.

---

## Experiment Results

| Experiment | MAE | vs Baseline | Configuration |
|------------|-----|-------------|---------------|
| A1_V8_BASELINE | **4.0235** | - | No recency (BEST) |
| C3_CURRENT_SEASON | 4.0330 | +0.2% | Current season only, 90-day half-life |
| A4_RECENCY_365 | 4.0760 | +1.3% | Full data, 365-day half-life |
| A2_RECENCY_180 | 4.1681 | +3.6% | Full data, 180-day half-life |
| A3_RECENCY_90 | 4.1816 | +3.9% | Full data, 90-day half-life |
| C2_RECENT_2YR | 4.1820 | +3.9% | 2-year data, 180-day half-life |

### Key Insights

1. **Recency weighting degrades performance** - Every experiment with recency weighting performed worse than the baseline
2. **More aggressive = worse** - The shorter the half-life, the worse the MAE
3. **Historical data matters** - Models trained on full 2021-2025 data outperform recent-only models
4. **V8 baseline is hard to beat** - 4.0235 MAE is the target to beat

---

## Files Created/Modified

### Created
| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v9.py` | V9 prediction system with trajectory features |
| `docs/08-projects/current/catboost-v9-experiments/README.md` | Project documentation |
| `docs/08-projects/current/catboost-v9-experiments/EXPERIMENT-TRACKER.md` | Experiment tracking |
| `ml/experiments/results/catboost_v9_exp_*_20260130_*.json` | 6 experiment results |

### Modified
| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Added V9 in shadow mode (System 8) |

---

## Code Changes Detail

### CatBoost V9 System (`catboost_v9.py`)
- 36 features: V8's 33 + 3 trajectory features
- Trajectory features: `pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag`
- Runtime calculation of trajectory features from existing data
- Shadow mode: runs alongside V8 without affecting production
- Environment variable: `CATBOOST_V9_MODEL_PATH`

### Worker Integration (`worker.py`)
- Added System 8 block for CatBoost V9
- V9 predictions logged but not used in ensemble
- Health endpoint includes V9 status
- 8 systems now: MA, Zone, Similarity, XGBoost, CatBoost V8, CatBoost V9, Ensemble V1, Ensemble V1.1

---

## NOT Committed

The following changes are staged but NOT committed:
- `predictions/worker/worker.py` - V9 integration
- `predictions/worker/prediction_systems/catboost_v9.py` - V9 system

**Recommendation:** Given experiment results show recency weighting doesn't help, consider:
1. Keeping V9 code for future trajectory feature experiments
2. NOT deploying recency-weighted models
3. Focusing next experiments on trajectory features WITHOUT recency weighting

---

## Next Steps

### Immediate
- [ ] Decide: Commit V9 code or revert?
- [ ] If keeping: Test V9 imports work correctly
- [ ] Run `/validate-daily` to ensure today's pipeline is healthy

### Critical Insight: Seasonality vs. Recency

The recency weighting experiments tested **uniform recency** (all recent games weighted higher). But the original hypothesis was about **seasonal patterns**:

> "Stars get more minutes in January/near All-Star break, while bench rotations tighten"

These are **different effects**:
- **Recency weighting**: Recent games matter more (tested - DOESN'T HELP)
- **Seasonality**: Specific patterns around All-Star break (NOT YET TESTED)

### Recommended Next Experiments

**1. Seasonal Features (Test All-Star Effect)**
Add explicit seasonal features to the model:
```python
seasonal_features = [
    'is_january',              # Boolean: January games
    'is_february',             # Boolean: February games
    'days_to_all_star',        # Days until All-Star break
    'pct_season_completed',    # 0.0 to 1.0
    'is_post_all_star',        # Boolean: After break
]
```
*Hypothesis: Model can learn seasonal patterns explicitly*

**2. Minutes Trend Feature**
Add `minutes_slope_10g` to capture if a player is getting more/less playing time:
```python
'minutes_slope_10g'  # Linear slope of minutes over L10
```
*Hypothesis: Stars' minutes trending UP should predict higher points*

**3. Player-Tier Segmentation**
Train separate models for different player tiers:
- **Stars** (season avg > 20 pts): Different dynamics near All-Star
- **Role players** (10-20 pts): More stable
- **Bench** (<10 pts): Rotations tightening
*Hypothesis: Single model can't capture tier-specific patterns*

**4. Trajectory Features Only (No Recency)**
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id B1_TRAJECTORY_NO_RECENCY \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --feature-count 36 \
    --verbose
```
*The V9 trajectory features (pts_slope_10g, zscore, breakout_flag) already capture some of this*

---

## Model Files

Experiment models saved to:
```
ml/experiments/results/catboost_v9_exp_*_20260130_*.cbm
```

Best performing model:
```
ml/experiments/results/catboost_v9_exp_A1_V8_BASELINE_20260130_080724.cbm
```
(MAE: 4.0235, no recency weighting)

---

## Verification Commands

### Check experiment results
```bash
for f in ml/experiments/results/catboost_v9_exp_*_20260130_*.json; do
  jq -r '.experiment_id + ": MAE=" + (.training_results.validation_mae|tostring)' "$f"
done | sort -t= -k2 -n
```

### Test V9 import
```bash
python -c "from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9; v9=CatBoostV9(); print(v9.info())"
```

### Check V9 model loads
```bash
ls -la models/catboost_v9_*.cbm
```

---

## Key Learnings

1. **Don't assume recency helps** - The hypothesis was that weighting recent games higher would improve predictions. Data proved otherwise.

2. **Historical patterns are valuable** - NBA player scoring patterns from 2021-2024 are still relevant for 2025 predictions.

3. **Test hypotheses before implementation** - We ran experiments before deploying, which saved us from deploying a worse model.

4. **V8 is already well-optimized** - MAE of 4.02 without any tricks suggests the feature set and hyperparameters are solid.

---

## Quick Reference

### Current Production
- CatBoost V8: 33 features, MAE ~3.40 (production)
- V9: Implemented but NOT deployed

### Experiment Models Location
```
ml/experiments/results/
```

### Documentation
```
docs/08-projects/current/catboost-v9-experiments/
```

---

*Session 34 complete. Recency weighting experiments show it hurts performance. Historical data is valuable.*
