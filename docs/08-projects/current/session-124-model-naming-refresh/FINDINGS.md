# Session 124 Findings - Model Analysis & Subset System Review

**Date:** 2026-02-04
**Status:** In Progress

---

## Major Finding: Tier Bias is Minimal

Fresh analysis shows the CatBoost V9 model is **well-calibrated**:

| Tier | Predictions | Avg Predicted | Avg Actual | Bias | Hit Rate |
|------|-------------|---------------|------------|------|----------|
| Stars (25+) | 142 | 26.2 | 26.1 | **+0.1** | 59.9% |
| Starters (15-24) | 481 | 18.0 | 18.9 | -0.9 | 55.3% |
| Role (8-14) | 783 | 11.4 | 11.4 | -0.1 | 54.7% |
| Bench (<8) | 249 | 6.4 | 5.8 | +0.6 | 50.0% |

**Key insight:** The -8.6 star bias reported earlier was from a different query method (using `actual_points` to define tier instead of `points_avg_season`). When using pre-game tier definition, the model is accurate.

---

## Subset Performance Analysis (30-day)

| Subset | Bets | Hit Rate |
|--------|------|----------|
| All Picks | 1655 | 54.3% |
| Edge >= 5 | 154 | 74.0% |
| Edge >= 5 + OVER | 91 | **81.3%** |
| Edge >= 5 + UNDER | 63 | 63.5% |

**OVER significantly outperforms UNDER** at high edge (81.3% vs 63.5%).

---

## New Subsets Created

Added to `dynamic_subset_definitions` table:

| subset_id | Filter | Purpose |
|-----------|--------|---------|
| `v9_high_edge_over_only` | edge ≥5, OVER | Exploit OVER advantage |
| `v9_high_edge_under_only` | edge ≥5, UNDER | Tracking comparison |
| `v9_high_edge_all_directions` | edge ≥5, any | Baseline |

Updated `subset_public_names.py` with public IDs 10, 11, 12.

---

## Opus Agent Recommendations

### Consensus: Model is Good, Focus on Filtering

Three Opus agents analyzed the system and agreed:

1. **Don't build stars-only model** - Only 687-1000 star samples (too few)
2. **Current OVER strategy works** - 81% hit rate, keep exploiting it
3. **Model calibration is not urgent** - Tier bias is minimal
4. **Isotonic regression available if needed** - Simple post-processing fix

### Ranked Model Improvement Approaches

| Rank | Approach | Effort | Risk | Impact |
|------|----------|--------|------|--------|
| 1 | Isotonic Regression | 30 min | Very Low | Medium |
| 2 | Two-Stage (Talent + Deviation) | 4-6 hrs | Low | High |
| 3 | Quantile Regression (0.52) | 1 hr | Very Low | Low-Medium |
| 4 | Tier-Aware Features (V10) | 1-2 days | Medium | Medium |
| 5 | Stars-Only Model | 1-2 days | High | Uncertain |

---

## Model Naming Decision

### Original Plan
Rename `catboost_v9` to `catboost_v9_20251102_20260108` format.

### Revised Approach (Per Opus Agents)
- **Don't rename** - 1,148 code references would need updating
- **Add `model_artifact_id` field** - Track specific trained model
- **Keep `system_id = 'catboost_v9'`** - Logical model family stays same

This is additive, not breaking.

---

## Experiment Results

### Experiment 1: V9_20251102_20260108
- Training: Nov 2 → Jan 8 (68 days)
- Eval: Jan 9 → Jan 31 (23 days)
- MAE: 4.79 (✅ better than baseline 5.14)
- Hit Rate Overall: 50.4% (❌ below baseline)
- Hit Rate Edge 5+: 80% (✅ but n=20, small sample)

### Experiment 2: V9_20251102_20260131
- Training: Nov 2 → Jan 31 (91 days)
- Eval: Feb 1 → Feb 3 (3 days)
- MAE: 5.09 (✅ slightly better)
- Hit Rate Overall: 60% (✅ but only 271 samples)
- **Eval window too short for reliable stats**

---

## Action Items

### Completed
- [x] Created 3 new direction-specific subsets
- [x] Updated subset_public_names.py
- [x] Verified tier bias is minimal
- [x] Ran model experiments

### Remaining
- [ ] Monitor new subsets for 1 week
- [ ] Decide on model naming approach
- [ ] Consider isotonic calibration if needed
- [ ] Update daily Slack report to include subset performance

---

## Key Learnings

1. **Query method matters** - Tier bias varies based on how you define tiers
2. **OVER >> UNDER at high edge** - 81% vs 63% is a structural edge
3. **Model is better than thought** - +0.1 star bias, not -8.6
4. **Don't over-engineer** - Current filtering already achieves 81%

---

## CRITICAL BUG FOUND: quick_retrain.py Tier Bias Calculation

**File:** `ml/experiments/quick_retrain.py`
**Function:** `compute_tier_bias()` (line 324)

**Bug:** Uses `actuals >= 25` to define stars (WRONG - hindsight)
**Should be:** Use `points_avg_season` from features (pre-game info)

**Impact:** Models are flagged as "BLOCKED: Critical tier bias" when they're actually fine.

**Fix needed:** Update `compute_tier_bias()` to accept season averages from feature data.

---

## Opus Agent Insight: UNDER Problem is Volatility, Not Bias

The poor UNDER performance on Role/Bench (47%) isn't model bias - it's player volatility:
- Role players have high std dev (5-7 pts)
- They're "breakout capable" (max is 2-3x average)
- UNDER bets carry asymmetric risk

**Recommendation:** Add volatility filter, not new model:
```python
if recommendation == 'UNDER' and line_value < 14 and player_volatility > 5.0:
    recommendation = 'PASS'
```

---

*Session 124 - Model Naming Refresh & Subset Review*
