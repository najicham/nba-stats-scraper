# Session 34 Handoff - CatBoost V9 Experiments

**Date:** 2026-01-30
**Focus:** CatBoost V9 implementation and recency weighting experiments
**Status:** Experiments complete, key insight gained, code uncommitted

---

## Executive Summary

Session 34 implemented CatBoost V9 and ran 6 experiments testing recency weighting.

**Key Finding:** Recency weighting **hurts** performance. But this tested the WRONG hypothesis.

**The Real Insight:** The original observation was about **seasonal patterns** (stars playing more in January/All-Star), not uniform recency. The next session should test **seasonal features**, not recency weighting.

---

## Version History

| Version | Features | Status | Notes |
|---------|----------|--------|-------|
| V7 | 31 features | Deprecated | Older model |
| V8 | 33 features | **PRODUCTION** | Champion (MAE ~3.40) |
| V9 | 36 features (trajectory) | Code exists, not deployed | This session |
| V10 | 33 features | Model file only | No prediction system |
| **V11** | TBD (seasonal) | **RECOMMENDED NEXT** | See below |

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

**Conclusion:** Recency weighting uniformly hurts performance. More aggressive = worse.

---

## Critical Insight: Recency vs. Seasonality

### What We Tested (WRONG)
**Uniform recency weighting**: "Recent games matter more for all players"
- Every experiment with recency weighting performed worse
- Historical patterns from 2021-2024 are still valuable

### What We Should Test (RIGHT)
**Seasonal patterns**: "Stars play more in January/All-Star, bench rotations tighten"

This is fundamentally different:
- **Recency**: All recent games weighted higher (uniform)
- **Seasonality**: Specific time-of-year effects (targeted)

The observation was:
> "Stars get more minutes near All-Star break, bench rotations tighten"

This is a **seasonal effect** that varies by player tier, not a uniform recency effect.

---

## Recommendation: Create V11 with Seasonal Features

### Why V11, Not Modify V9?

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Modify V9** | Less code | V9 already has trajectory features, mixing concerns | NO |
| **Create V11** | Clean separation, clear purpose | More files | **YES** |

V9 was designed for trajectory features (pts_slope, zscore, breakout_flag). Seasonal features are a different hypothesis. Keep them separate for clean A/B testing.

### V11 Proposed Features

Add these **seasonal features** to V8's 33 base features:

```python
V11_SEASONAL_FEATURES = [
    # Time-of-season (4 features)
    'month_of_season',        # 1-12 (Oct=1, Jun=12)
    'pct_season_completed',   # 0.0-1.0
    'days_to_all_star',       # Days until break (negative after)
    'is_post_all_star',       # Boolean

    # Minutes trend (2 features)
    'minutes_slope_10g',      # Linear slope of minutes over L10
    'minutes_vs_season_avg',  # Current minutes vs season average

    # Player tier context (2 features) - OPTIONAL
    'is_star_player',         # season_avg > 20 pts
    'is_rotation_player',     # season_avg 10-20 pts
]
```

**Total: 33 + 8 = 41 features** (or 33 + 6 = 39 without player tier)

### V11 Implementation Steps

1. **Add seasonal features to feature store**
   - File: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
   - Add calculation methods for each seasonal feature
   - Update `feature_count` to 39 or 41

2. **Backfill feature store** (optional for training)
   - Can calculate seasonal features at training time from `game_date`

3. **Create V11 prediction system**
   - File: `predictions/worker/prediction_systems/catboost_v11.py`
   - Copy V8, add seasonal features

4. **Train V11 model**
   ```bash
   PYTHONPATH=. python ml/experiments/train_walkforward.py \
       --experiment-id V11_SEASONAL \
       --train-start 2021-11-01 --train-end 2025-12-31 \
       --feature-count 39 \
       --verbose
   ```

5. **Deploy V11 in shadow mode** alongside V8

---

## Current Code Status

### Created (NOT COMMITTED)

| File | Status | Action |
|------|--------|--------|
| `predictions/worker/prediction_systems/catboost_v9.py` | Created | **KEEP** - useful for trajectory experiments |
| `predictions/worker/worker.py` | Modified | **REVERT** V9 integration until model is ready |

### Recommendation

```bash
# Option A: Keep V9 code, revert worker integration
git checkout predictions/worker/worker.py

# Option B: Commit V9 as experimental (not loaded by default)
# This preserves the work for future trajectory experiments
```

V9's trajectory features (`pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag`) could still be valuable - they just weren't tested WITHOUT recency weighting yet.

---

## Experiment Files

### Models (in `ml/experiments/results/`)
```
catboost_v9_exp_A1_V8_BASELINE_20260130_080724.cbm  # Best: MAE 4.0235
catboost_v9_exp_A2_RECENCY_180_20260130_080724.cbm
catboost_v9_exp_A3_RECENCY_90_20260130_080724.cbm
catboost_v9_exp_A4_RECENCY_365_20260130_080725.cbm
catboost_v9_exp_C2_RECENT_2YR_RECENCY_20260130_080735.cbm
catboost_v9_exp_C3_CURRENT_SEASON_20260130_080735.cbm
```

### Metadata (same directory, `*_metadata.json`)
Each contains MAE, feature list, hyperparameters, training config.

---

## Next Session Checklist

### Priority 1: Decide on V9/V11 Strategy
- [ ] Review this handoff
- [ ] Decide: Keep V9 code? Create V11?
- [ ] If keeping V9: Revert worker.py changes (V9 not ready for shadow mode)

### Priority 2: Create Seasonal Features
- [ ] Design seasonal feature calculations
- [ ] Add to feature store processor OR calculate at training time
- [ ] Create `catboost_v11.py` if going V11 route

### Priority 3: Run Seasonal Experiments
```bash
# Experiment: V11 with seasonal features, no recency
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id V11_SEASONAL_NO_RECENCY \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --verbose
```

### Priority 4: Test Trajectory Features Without Recency
If keeping V9, test trajectory features alone:
```bash
# Experiment: V9 trajectory features, NO recency weighting
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id V9_TRAJECTORY_NO_RECENCY \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --feature-count 36 \
    --verbose
```

---

## Key Learnings

1. **Test the right hypothesis**: Recency ≠ seasonality. We tested uniform recency when the observation was about seasonal patterns.

2. **Historical data is valuable**: Models trained on 2021-2025 data outperform recent-only models.

3. **More aggressive ≠ better**: 90-day half-life performed worse than 365-day, which performed worse than no recency at all.

4. **V8 is well-optimized**: MAE of 4.02 with standard training is hard to beat with simple tricks.

5. **Separate hypotheses cleanly**: V9 (trajectory) and V11 (seasonal) should be separate to enable clean A/B testing.

---

## Quick Reference

### Commands to Check Experiment Results
```bash
# View all MAEs
for f in ml/experiments/results/catboost_v9_exp_*_20260130_*.json; do
  jq -r '.experiment_id + ": MAE=" + (.training_results.validation_mae|tostring)' "$f"
done | sort -t= -k2 -n

# Best model info
jq '.' ml/experiments/results/catboost_v9_exp_A1_V8_BASELINE_20260130_080724_metadata.json
```

### Current Git Status
```bash
# Modified (uncommitted)
predictions/worker/worker.py          # V9 integration - REVERT or KEEP?

# Untracked (new)
predictions/worker/prediction_systems/catboost_v9.py  # V9 system - KEEP
docs/08-projects/current/catboost-v9-experiments/     # Documentation
ml/experiments/results/catboost_v9_exp_*_20260130_*   # Experiment results
```

### Documentation
- Project docs: `docs/08-projects/current/catboost-v9-experiments/`
- This handoff: `docs/09-handoff/2026-01-30-SESSION-34-CATBOOST-V9-EXPERIMENTS-HANDOFF.md`

---

## Summary for Next Session

**What happened:** Ran 6 recency weighting experiments. All performed worse than baseline.

**Key insight:** We tested the wrong hypothesis. The observation about "stars playing more in January" is a **seasonal effect**, not a **recency effect**.

**Recommendation:**
1. Keep V9 code for future trajectory experiments
2. Revert worker.py (don't deploy V9 yet)
3. Create V11 with **seasonal features** (month, days_to_all_star, minutes_slope)
4. Test V11 without recency weighting

**Bottom line:** Don't deploy recency-weighted models. Test seasonal features instead.

---

*Session 34 complete. Recency weighting experiments failed, but revealed we need to test seasonal features instead.*
